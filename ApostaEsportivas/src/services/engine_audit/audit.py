"""Engine Audit -- a camada de auditoria dos motores.

REGRA QUE DEFINE ESTE ARQUIVO: NAO EXISTE SEGUNDA PASSADA
---------------------------------------------------------
A auditoria e' gravada DURANTE a execucao do motor, com os numeros que o
motor ja' calculou. Nada aqui reabre historico, recalcula probabilidade ou
chama a API pra "conferir" o que o motor decidiu. Um auditor que recalcula
vira um segundo motor -- com bugs proprios, custo proprio de API e a
possibilidade de discordar do primeiro, que e' o pior desfecho possivel pra
uma tela cujo proposito e' explicar.

Custo por execucao: 1 INSERT no inicio (engine_runs), 1 INSERT por jogo
analisado (engine_decisions, que os pipelines de pre-jogo JA' faziam desde
07/08), 1 UPDATE no fim, e um INSERT por erro. Nada em laco quente.

ONDE CADA COISA MORA
--------------------
    engine_runs       uma linha por execucao de motor+metodo
    engine_decisions  uma linha por JOGO analisado naquela execucao
    engine_errors     so' quando ha erro

`engine_decisions` ja' existia (criada por engine_pipelines/decision_log.py em
07/08) e ja' significava exatamente "um jogo analisado, com os candidatos e o
motivo". A estrutura minima sugerida pedia `engine_analysis` separada de
`engine_decisions`; criar as duas duplicaria a mesma linha, entao a tabela
existente absorve os dois papeis e ganha as colunas que faltavam (run_id,
engine, method, engine_version, score, probability, odd, pick_table, pick_id).
A linha com status 'selecionado' E' a decisao, e aponta pro pick.

Isso preserva de graca tres coisas que ja' funcionavam: as semanas de
historico ja' gravado, a aba Motor do painel e scripts/funil_motor_ao_vivo.py.

NADA AQUI PODE DERRUBAR UM MOTOR
--------------------------------
Toda gravacao e' engolida e so' avisada, mesmo padrao do decision_log. Um
motor que para de gerar pick porque a auditoria falhou seria uma auditoria que
custa mais do que informa.
"""
from __future__ import annotations

import json
import textwrap
import traceback
from contextvars import ContextVar
from datetime import datetime

from utils.data_br import HOJE_BR
from utils.db_utils import get_connection, get_log_connection

from services.engine_audit import registry

# -- Status de execucao ------------------------------------------------------
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
PARTIAL = "PARTIAL"

# -- Status de um jogo analisado ---------------------------------------------
# 'avaliado', 'descartado' e 'sem_pick' vem do decision_log e continuam
# valendo. 'selecionado' e' novo: e' a linha que virou pick.
SELECIONADO = "selecionado"
DESCARTADO = "descartado"

_tabelas_prontas = False

#: Execucao corrente do processo. E' assim que `decision_log` carimba run_id
#: nas linhas que ele ja' gravava, sem que nenhum pipeline precise passar o
#: run_id de funcao em funcao ate' o fundo do motor.
_run_atual: ContextVar = ContextVar("engine_audit_run", default=None)


def run_atual():
    """A execucao em andamento neste processo, ou None."""
    return _run_atual.get()


def auditar(motor: str, metodo: str, **resumo):
    """Decorador -- embrulha a funcao de entrada de um pipeline numa execucao.

        @auditar("PRE_LIVE", "vip")
        def run_vip_engine():
            ...

    E' a forma que os pipelines JA' EXISTENTES usam, e a escolha e'
    deliberada: o Pre Live esta' congelado, entao a auditoria nao pode custar
    uma reindentacao do corpo inteiro da funcao dentro de um `with`. Duas
    linhas no topo, zero linha mexida no meio -- e o `run` chega ate' o fundo
    do motor pelo ContextVar, que e' o que faz o `decision_log` carimbar
    run_id sem nenhum pipeline passar parametro.

    Motores novos usam `with EngineRun(...)` direto, porque eles precisam
    chamar `run.analisado()` e o decorador nao entrega o objeto.
    """
    def envolver(fn):
        from functools import wraps

        @wraps(fn)
        def executar(*args, **kwargs):
            with EngineRun(motor, metodo, resumo=resumo or None):
                return fn(*args, **kwargs)
        return executar
    return envolver


def _ensure_tables() -> None:
    global _tabelas_prontas
    if _tabelas_prontas:
        return
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""CREATE TABLE IF NOT EXISTS engine_runs (
            run_id          TEXT PRIMARY KEY,
            engine          TEXT NOT NULL,
            method          TEXT NOT NULL,
            engine_version  TEXT NOT NULL,
            match_date      DATE NOT NULL,
            started_at      TIMESTAMP NOT NULL DEFAULT NOW(),
            finished_at     TIMESTAMP,
            status          TEXT NOT NULL,
            analisados      INTEGER NOT NULL DEFAULT 0,
            selecionados    INTEGER NOT NULL DEFAULT 0,
            descartados     INTEGER NOT NULL DEFAULT 0,
            erros           INTEGER NOT NULL DEFAULT 0,
            -- Retrato curto do que a execucao usou/produziu (limiares do dia,
            -- calibragem, dry run). NAO e' pra despejar dado de jogo aqui:
            -- jogo tem linha propria em engine_decisions.
            resumo          JSONB
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_engine_runs_recentes "
                    "ON engine_runs (started_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_engine_runs_motor "
                    "ON engine_runs (engine, method, match_date DESC)")

        cur.execute("""CREATE TABLE IF NOT EXISTS engine_errors (
            id          BIGSERIAL PRIMARY KEY,
            run_id      TEXT,
            engine      TEXT,
            method      TEXT,
            fixture_id  INTEGER,
            contexto    TEXT,
            erro        TEXT NOT NULL,
            traceback   TEXT,
            created_at  TIMESTAMP NOT NULL DEFAULT NOW()
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_engine_errors_run "
                    "ON engine_errors (run_id, created_at DESC)")

        # engine_decisions pode nao existir ainda num banco que nunca rodou
        # pipeline: o CREATE aqui repete o do decision_log (IF NOT EXISTS nos
        # dois lados, entao quem chegar primeiro cria).
        cur.execute("""CREATE TABLE IF NOT EXISTS engine_decisions (
            id          BIGSERIAL PRIMARY KEY,
            match_date  DATE NOT NULL,
            pipeline    TEXT NOT NULL,
            fixture_id  INTEGER,
            home_team   TEXT,
            away_team   TEXT,
            status      TEXT NOT NULL,
            reason      TEXT,
            candidates  JSONB NOT NULL DEFAULT '[]'::jsonb,
            matchup     JSONB,
            context     JSONB,
            created_at  TIMESTAMP DEFAULT NOW()
        )""")
        # Colunas novas da arquitetura de 27/08. Uma por ALTER: um IF NOT
        # EXISTS que falha nao pode arrastar os outros (mesmo motivo do
        # rollback por migracao em main.py::run_migrations).
        for coluna, tipo in (
            ("run_id", "TEXT"), ("engine", "TEXT"), ("method", "TEXT"),
            ("engine_version", "TEXT"), ("score", "NUMERIC"),
            ("probability", "NUMERIC"), ("odd", "NUMERIC"),
            ("pick_table", "TEXT"), ("pick_id", "BIGINT"),
        ):
            cur.execute(f"ALTER TABLE engine_decisions "
                        f"ADD COLUMN IF NOT EXISTS {coluna} {tipo}")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_engine_decisions_run "
                    "ON engine_decisions (run_id)")
        conn.commit()
        _tabelas_prontas = True
    except Exception as e:
        conn.rollback()
        print(f"[ENGINE_AUDIT] Aviso: falha ao provisionar tabelas (nao afeta o motor): {e}")
    finally:
        cur.close()
        conn.close()


def _um_valor(linha):
    """Primeira coluna da linha, seja o cursor de tupla (motor) ou de dict (site)."""
    if not linha:
        return 0
    if isinstance(linha, dict):
        return next(iter(linha.values()))
    return linha[0]


def _proximo_run_id(cur, prefixo: str) -> str:
    """`PB-20260827-001` -- sequencial por MOTOR e por DIA.

    Conta o que ja' existe com o mesmo prefixo e data. Concorrencia nao e'
    problema real aqui (os motores rodam um de cada vez, na mao ou pelo laco
    do live), mas se dois processos colidirem o INSERT bate na PK e o chamador
    tenta o proximo numero -- ver `_abrir`.
    """
    dia = datetime.now().strftime("%Y%m%d")
    cur.execute(f"""SELECT COUNT(*) FROM engine_runs
                     WHERE run_id LIKE %s AND match_date = {HOJE_BR}""",
                (f"{prefixo}-{dia}-%",))
    n = int(_um_valor(cur.fetchone()) or 0)
    return f"{prefixo}-{dia}-{n + 1:03d}"


class EngineRun:
    """Uma execucao de motor+metodo, com a auditoria embutida.

        with EngineRun("PICK_BOOST", "over15_under25ht") as run:
            ...
            run.analisado(fixture, score=94, probabilidade=0.91, odd=1.42,
                          selecionado=True, motivo="...", dados={...})

    Sair do `with` fecha a execucao: COMPLETED sem erro, PARTIAL com erro mas
    com algum jogo analisado, FAILED se a excecao escapou do corpo.

    Modo silencioso: se o banco nao responder, `run_id` fica None e todos os
    metodos viram no-op. O motor roda igual, so' fica sem auditoria -- que e'
    exatamente a troca certa quando o alternativo e' nao gerar pick.
    """

    def __init__(self, motor: str, metodo: str, resumo: dict | None = None):
        self.motor = motor
        self.metodo = metodo
        met = registry.metodo(motor, metodo)
        self.versao = met.versao if met else "0.0.0"
        self.pipeline = met.pipeline if met else motor
        self.tabela_picks = met.tabela_picks if met else ""
        motor_obj = registry.MOTOR_POR_SLUG.get(motor)
        self.prefixo = motor_obj.prefixo if motor_obj else motor[:2].upper()
        self.run_id: str | None = None
        self.resumo: dict = dict(resumo or {})
        self.analisados = 0
        self.selecionados = 0
        self.descartados = 0
        self.erros = 0
        self._token = None

    # -- ciclo de vida ------------------------------------------------------
    def __enter__(self) -> "EngineRun":
        self._abrir()
        self._token = _run_atual.set(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.erro(exc, contexto="execucao interrompida")
            self.finalizar(FAILED)
        else:
            self.finalizar()
        if self._token is not None:
            _run_atual.reset(self._token)
        return False  # nunca engole a excecao do motor

    def _abrir(self) -> None:
        _ensure_tables()
        try:
            conn = get_connection()
            cur = conn.cursor()
            try:
                for _ in range(3):
                    candidato = _proximo_run_id(cur, self.prefixo)
                    try:
                        cur.execute(f"""INSERT INTO engine_runs
                            (run_id, engine, method, engine_version, match_date,
                             status, resumo)
                            VALUES (%s, %s, %s, %s, {HOJE_BR}, %s, %s::jsonb)""",
                            (candidato, self.motor, self.metodo, self.versao,
                             RUNNING, json.dumps(self.resumo, ensure_ascii=False,
                                                 default=str)))
                        conn.commit()
                        self.run_id = candidato
                        break
                    except Exception:
                        # PK batida: outro processo pegou este numero. Tenta o
                        # proximo em vez de derrubar o motor por causa do log.
                        conn.rollback()
                if self.run_id:
                    print(f"[ENGINE_AUDIT] {self.motor}/{self.metodo} "
                          f"v{self.versao} - run {self.run_id}")
            finally:
                cur.close()
                conn.close()
        except Exception as e:
            print(f"[ENGINE_AUDIT] Aviso: execucao sem auditoria ({e}).")

    def finalizar(self, status: str | None = None) -> None:
        if not self.run_id:
            return
        if status is None:
            if self.erros and self.analisados:
                status = PARTIAL
            elif self.erros:
                status = FAILED
            else:
                status = COMPLETED
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""UPDATE engine_runs
                              SET finished_at = NOW(), status = %s,
                                  analisados = %s, selecionados = %s,
                                  descartados = %s, erros = %s, resumo = %s::jsonb
                            WHERE run_id = %s""",
                        (status, self.analisados, self.selecionados,
                         self.descartados, self.erros,
                         json.dumps(self.resumo, ensure_ascii=False, default=str),
                         self.run_id))
            conn.commit()
            cur.close()
            conn.close()
            print(f"[ENGINE_AUDIT] {self.run_id} {status} - {self.analisados} analisados, "
                  f"{self.selecionados} selecionados, {self.descartados} descartados, "
                  f"{self.erros} erro(s).")
        except Exception as e:
            print(f"[ENGINE_AUDIT] Aviso: falha ao fechar a execucao: {e}")

    # -- registro -----------------------------------------------------------
    def anotar(self, **campos) -> None:
        """Acrescenta ao `resumo` da execucao (limiares, calibragem, dry run).

        Gravado so' no `finalizar()`: sao poucos campos e um UPDATE por
        anotacao seria escrita em laco por nada.
        """
        self.resumo.update(campos)

    def analisado(self, fixture: dict | None, *, selecionado: bool = False,
                  score=None, probabilidade=None, odd=None,
                  motivo: str | None = None, dados: dict | None = None,
                  candidatos: list | None = None, pick_id=None) -> None:
        """UM jogo analisado nesta execucao.

        `dados` e' o que sustenta a explicacao da pick: os indicadores REAIS
        que entraram na conta, no formato que o motor calculou. Vai inteiro pra
        coluna `context`, e e' dele que a tela "Por que essa pick?" e' montada
        -- por isso a regra e' guardar o que foi USADO, nao tudo que foi lido.
        """
        fixture = fixture or {}
        self.analisados += 1
        if selecionado:
            self.selecionados += 1
        else:
            self.descartados += 1
        if not self.run_id:
            return
        try:
            # Conexao REAPROVEITADA (2026-09-05): este INSERT roda uma vez por
            # JOGO ANALISADO, e abrir conexao custa ~1,7s contra
            # milissegundos de INSERT. Ver `get_log_connection`.
            conn = get_log_connection()
            cur = conn.cursor()
            cur.execute(f"""INSERT INTO engine_decisions
                (match_date, pipeline, fixture_id, home_team, away_team, status,
                 reason, candidates, context, run_id, engine, method,
                 engine_version, score, probability, odd, pick_table, pick_id)
                VALUES ({HOJE_BR}, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (self.pipeline, fixture.get("fixture_id"), fixture.get("home_team"),
                 fixture.get("away_team"),
                 SELECIONADO if selecionado else DESCARTADO, motivo,
                 json.dumps(candidatos or [], ensure_ascii=False, default=str),
                 json.dumps(dados, ensure_ascii=False, default=str) if dados else None,
                 self.run_id, self.motor, self.metodo, self.versao,
                 score, probabilidade, odd,
                 self.tabela_picks if selecionado else None,
                 pick_id if selecionado else None))
            conn.commit()
            cur.close()
        except Exception as e:
            print(f"[ENGINE_AUDIT] Aviso: falha ao gravar jogo analisado: {e}")

    def contabilizar(self, status: str) -> None:
        """So' as contagens, sem gravar linha -- pro caso em que a linha de
        `engine_decisions` ja' vai ser gravada por outro caminho.

        Existe pelo `decision_log` (2026-08-28). Os motores de pre-jogo nao
        chamam `analisado()`: eles ja' gravavam a linha por jogo antes da
        auditoria existir, e o decorador `@auditar` so' carimba run_id no que
        eles ja' faziam. O efeito colateral era a aba de Auditoria mostrar
        "0 analisados, 0 selecionados, 0 descartados" numa execucao que tinha
        lido tres jogos e salvo uma pick -- numeros que faziam o motor
        PARECER quebrado.

        `sem_pick` nao conta jogo nenhum: a linha tem fixture NULL, e' um
        recado da execucao, nao uma partida.
        """
        if status == "descartado":
            self.analisados += 1
            self.descartados += 1
        elif status == "avaliado":
            self.analisados += 1
            self.descartados += 1  # vira selecionado se a pick for salva

    def selecionou(self, quantos: int = 1) -> None:
        """`quantos` jogos analisados viraram pick nesta execucao.

        Move a contagem de descartado pra selecionado, em vez de somar num
        terceiro balde: analisados = selecionados + descartados e' a relacao
        que a aba de Auditoria exibe, e ela tem que fechar.
        """
        movidos = min(quantos, self.descartados)
        self.selecionados += movidos
        self.descartados -= movidos

    def erro(self, exc: BaseException | str, contexto: str = "",
             fixture_id: int | None = None) -> None:
        self.erros += 1
        texto = str(exc)
        tb = ("".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
              if isinstance(exc, BaseException) else None)
        rotulo = f" - {contexto}" if contexto else ""
        print(f"[ENGINE_AUDIT] ERRO {self.motor}/{self.metodo}{rotulo}: {texto}")
        if tb:
            print(textwrap.indent(tb, "    "))
        if not self.run_id:
            return
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""INSERT INTO engine_errors
                (run_id, engine, method, fixture_id, contexto, erro, traceback)
                VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (self.run_id, self.motor, self.metodo, fixture_id,
                 contexto or None, texto[:2000], (tb or "")[:8000] or None))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[ENGINE_AUDIT] Aviso: falha ao gravar erro: {e}")
