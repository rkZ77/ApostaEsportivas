"""O site roda sozinho todo dia · AGENDADOR DE VOLTA (2026-10-08, pedido do usuario).

O QUE ACONTECEU EM 01/08. Havia um scheduler aqui (pipeline 00:10, resolver a
cada 5 min, reconferir a cada 3h...). A chave da API-Football e' UMA conta pros
tres ambientes, e o mesmo scheduler subindo em dev, noprod e producao estourou
a cota. Ele foi removido e tudo virou botao no /admin -- o que deixou o site
dependendo de alguem clicar todo dia, inclusive pra liquidar resultado e pra
coletar o fechamento que mede o CLV.

O QUE MUDA PRA NAO REPETIR 01/08:
  1. SO' NO SERVICO DE PRODUCAO. Tres travas juntas: `RAILWAY_ENVIRONMENT_NAME`
     igual a "production" (o noprod roda o mesmo codigo no mesmo banco),
     `runtime_env.is_production()` e `side_effects_enabled()`. Fora disso o
     laco nem sobe. `AGENDADOR=off` desliga em qualquer lugar, sem deploy.
  2. TETO DE COTA. Tarefa que gasta API so' roda se o consumo oficial do dia
     (o /status da propria API, que nao gasta cota) estiver abaixo de
     `AGENDADOR_TETO_COTA` (padrao 80%). Acima disso ela e' pulada e o painel
     diz por que.
  3. UMA VEZ POR DIA, MESMO COM VARIOS WORKERS. Cada tarefa reivindica o dia
     com INSERT ... ON CONFLICT DO NOTHING em `agendador_execucoes`: so' o
     processo que inseriu roda. O botao manual do "Rodar Tudo" reivindica
     tambem, entao quem ja' clicou de manha nao ganha uma segunda geracao.
  4. MESMOS CAMINHOS DO BOTAO. Nada aqui reimplementa pipeline: chama o
     `_run_tudo` e o `_run_and_track` do /admin.

As medicoes do motor (scripts/medir_*.py) so' leem o banco e gravam a saida em
`medicoes_do_motor`, que a aba Pipeline mostra.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

BR = ZoneInfo("America/Sao_Paulo")
_INTERVALO_SEG = 60


@dataclass(frozen=True)
class Tarefa:
    nome: str
    rotulo: str
    comando: str           # "tudo", um comando de admin._PIPELINE_SCRIPTS ou "medicoes"
    inicio: time           # horario de Brasilia a partir do qual roda
    ate: time              # depois disso, se nao rodou, fica pro dia seguinte
    gasta_api: bool
    depois_de: str | None = None   # so' roda quando esta outra terminou HOJE


#: A ordem e' a do dia. "ate" larga de proposito: um deploy de manha nao pode
#: fazer o dia ficar sem picks, entao o "Rodar Tudo" ainda vale ate' as 16h.
TAREFAS: tuple[Tarefa, ...] = (
    Tarefa("tudo", "Rodar Tudo (coleta, odds e picks)", "tudo",
           time(9, 0), time(16, 0), True),
    # O laco do fechamento fica de pe' ate' o ultimo jogo com pick comecar
    # (capturar_fechamento.TETO_HORAS) · por isso depende do Rodar Tudo.
    Tarefa("fechamento", "Odds de fechamento (CLV)", "coleta_fechamento",
           time(9, 30), time(20, 0), True, depois_de="tudo"),
    Tarefa("resultados_tarde", "Resultados (tarde)", "atualizar_resultados",
           time(18, 30), time(21, 0), True),
    Tarefa("resultados_noite", "Resultados (noite)", "atualizar_resultados",
           time(23, 45), time(23, 59), True),
    Tarefa("resultados_madrugada", "Resultados (madrugada)", "atualizar_resultados",
           time(3, 0), time(6, 0), True),
    Tarefa("medicoes", "Medições do motor", "medicoes",
           time(6, 0), time(8, 30), False),
)

#: Scripts de medicao, na ordem em que aparecem no painel. Todos so' leem.
MEDICOES = (
    ("primeiro_tempo", "1º tempo x resto", "scripts/medir_primeiro_tempo.py", []),
    ("calibracao", "Calibração por faixa", "scripts/medir_calibracao_dos_picks.py", []),
    ("recalibracao", "Recalibração (fora da amostra)", "scripts/medir_recalibracao.py", []),
    ("segundo_tempo", "2º tempo (backtest)", "scripts/medir_segundo_tempo.py", []),
    ("dixon_coles", "Dixon-Coles (gols em sombra)", "scripts/medir_dixon_coles.py", []),
    ("contexto_atual", "Contexto atual (técnico, forma, desfalques)",
     "scripts/medir_contexto_atual.py", []),
    # --gravar: re-estima os coeficientes todo dia com o que entrou na base. O
    # motor so' APLICA o que vier aprovado, e so' com MOTOR_TATICO=on.
    ("efeito_tatico", "Efeito tático do confronto (por mercado e competição)",
     "scripts/medir_efeito_tatico.py", ["--gravar"]),
)


# ── travas ───────────────────────────────────────────────────────────────────

def habilitado() -> bool:
    if os.getenv("AGENDADOR", "on").strip().lower() in ("off", "0", "false", "no"):
        return False
    if os.getenv("RAILWAY_ENVIRONMENT_NAME", "").strip().lower() != "production":
        return False
    import runtime_env
    return runtime_env.is_production() and runtime_env.side_effects_enabled()


def teto_de_cota() -> float:
    try:
        return min(max(float(os.getenv("AGENDADOR_TETO_COTA", "0.8")), 0.1), 1.0)
    except ValueError:
        return 0.8


def cota_permite(status: dict | None, teto: float) -> tuple[bool, str | None]:
    """(pode, motivo). Sem leitura da cota, NAO roda: o erro de 01/08 foi
    gastar sem saber quanto restava."""
    if not status or not status.get("limite"):
        return False, "cota da API indisponivel pra conferir"
    usado, limite = float(status.get("usado") or 0), float(status["limite"])
    if usado / limite >= teto:
        return False, f"cota em {usado / limite:.0%} (teto {teto:.0%})"
    return True, None


def na_janela(t: Tarefa, agora: datetime) -> bool:
    h = agora.astimezone(BR).time()
    return t.inicio <= h <= t.ate


# ── banco ────────────────────────────────────────────────────────────────────

def _conexao():
    from database import get_connection
    return get_connection()


def garantir_tabelas(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agendador_execucoes (
            tarefa       TEXT NOT NULL,
            dia          DATE NOT NULL,
            origem       TEXT NOT NULL DEFAULT 'agendador',
            iniciado_em  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            terminado_em TIMESTAMPTZ,
            status       TEXT NOT NULL DEFAULT 'rodando',
            detalhe      TEXT,
            PRIMARY KEY (tarefa, dia)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS medicoes_do_motor (
            nome      TEXT NOT NULL,
            dia       DATE NOT NULL,
            saida     TEXT,
            ok        BOOLEAN,
            criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (nome, dia)
        )
    """)


def reivindicar(tarefa: str, dia: date, origem: str = "agendador") -> bool:
    """True se ESTE processo ficou com a tarefa do dia."""
    conn = _conexao()
    try:
        cur = conn.cursor()
        garantir_tabelas(cur)
        cur.execute("""
            INSERT INTO agendador_execucoes (tarefa, dia, origem)
            VALUES (%s, %s, %s) ON CONFLICT (tarefa, dia) DO NOTHING
            RETURNING tarefa
        """, (tarefa, dia, origem))
        ganhou = cur.fetchone() is not None
        conn.commit()
        return ganhou
    finally:
        conn.close()


def concluir(tarefa: str, dia: date, status: str, detalhe: str | None = None) -> None:
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE agendador_execucoes
               SET status = %s, detalhe = %s, terminado_em = NOW()
             WHERE tarefa = %s AND dia = %s
        """, (status, (detalhe or "")[:2000] or None, tarefa, dia))
        conn.commit()
    finally:
        conn.close()


def terminou_hoje(tarefa: str, dia: date) -> bool:
    conn = _conexao()
    try:
        cur = conn.cursor()
        garantir_tabelas(cur)
        cur.execute("""
            SELECT 1 FROM agendador_execucoes
             WHERE tarefa = %s AND dia = %s AND terminado_em IS NOT NULL
        """, (tarefa, dia))
        return cur.fetchone() is not None
    finally:
        conn.close()


# ── execucao ─────────────────────────────────────────────────────────────────

async def _rodar_comando(t: Tarefa) -> tuple[str, str | None]:
    from routers import admin
    if t.comando == "tudo":
        await admin._run_tudo()
        st = admin._pipeline_status.get("tudo") or {}
    else:
        script = os.path.join(admin._PIPELINE_DIR, admin._PIPELINE_SCRIPTS[t.comando])
        await admin._run_and_track(t.comando, script, args=admin._PIPELINE_ARGS.get(t.comando))
        st = admin._pipeline_status.get(t.comando) or {}
    return ("ok" if st.get("status") == "ok" else "erro"), st.get("error")


async def rodar_medicoes(dia: date) -> tuple[str, str | None]:
    """Roda cada script de medicao e guarda a saida inteira. Um que falha nao
    impede os outros."""
    from routers import admin
    falhas = []
    for nome, _, caminho, args in MEDICOES:
        script = os.path.join(admin._PIPELINE_DIR, caminho)
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, script, *args, cwd=admin._PIPELINE_DIR,
                env={**os.environ, "PYTHONPATH": admin._PIPELINE_DIR, "PYTHONUNBUFFERED": "1"},
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            saida, _ = await asyncio.wait_for(proc.communicate(), timeout=900)
            texto, ok = saida.decode(errors="replace")[-60000:], proc.returncode == 0
        except Exception as e:   # timeout, script ausente
            texto, ok = f"Falhou: {e}", False
        if not ok:
            falhas.append(nome)
        conn = _conexao()
        try:
            cur = conn.cursor()
            garantir_tabelas(cur)
            cur.execute("""
                INSERT INTO medicoes_do_motor (nome, dia, saida, ok) VALUES (%s, %s, %s, %s)
                ON CONFLICT (nome, dia) DO UPDATE
                   SET saida = EXCLUDED.saida, ok = EXCLUDED.ok, criado_em = NOW()
            """, (nome, dia, texto, ok))
            conn.commit()
        finally:
            conn.close()
    return ("ok" if not falhas else "erro"), (f"falharam: {', '.join(falhas)}" if falhas else None)


async def executar(t: Tarefa, dia: date) -> None:
    try:
        if t.gasta_api:
            from routers import admin
            status_cota = await asyncio.to_thread(admin._api_football_status)
            pode, motivo = cota_permite(status_cota, teto_de_cota())
            if not pode:
                concluir(t.nome, dia, "pulada", motivo)
                logger.warning("[AGENDADOR] %s pulada: %s", t.nome, motivo)
                return
        if t.comando == "medicoes":
            status, detalhe = await rodar_medicoes(dia)
        else:
            status, detalhe = await _rodar_comando(t)
        concluir(t.nome, dia, status, detalhe)
        logger.info("[AGENDADOR] %s: %s", t.nome, status)
    except Exception as e:
        logger.exception("[AGENDADOR] %s quebrou", t.nome)
        try:
            concluir(t.nome, dia, "erro", str(e))
        except Exception:
            pass


async def uma_volta(agora: datetime | None = None) -> list[str]:
    """Dispara o que esta' na hora. Devolve o nome do que disparou (teste)."""
    agora = agora or datetime.now(BR)
    dia = agora.astimezone(BR).date()
    disparadas = []
    for t in TAREFAS:
        if not na_janela(t, agora):
            continue
        if t.depois_de and not terminou_hoje(t.depois_de, dia):
            continue
        if not reivindicar(t.nome, dia):
            continue
        disparadas.append(t.nome)
        asyncio.create_task(executar(t, dia))
    # Motor Ao Vivo: liga quando um jogo das nossas ligas esta' em campo e
    # desliga sozinho quando nao sobra nenhum (ver live_picks.supervisionar_automatico).
    try:
        from routers import live_picks
        if await live_picks.supervisionar_automatico():
            disparadas.append("ao_vivo")
    except Exception:
        logger.exception("[AGENDADOR] supervisao do ao vivo falhou")
    return disparadas


async def laco() -> None:
    logger.info("[AGENDADOR] ligado: %s", ", ".join(f"{t.nome} {t.inicio:%H:%M}" for t in TAREFAS))
    while True:
        try:
            await uma_volta()
        except Exception:
            logger.exception("[AGENDADOR] volta falhou")
        await asyncio.sleep(_INTERVALO_SEG)


def iniciar() -> bool:
    """Chamado no startup. Nao sobe nada fora do servico de producao."""
    if not habilitado():
        logger.info("[AGENDADOR] desligado neste ambiente")
        return False
    asyncio.create_task(laco())
    return True


# ── leitura pro painel ───────────────────────────────────────────────────────

def estado(dia: date | None = None) -> dict:
    dia = dia or datetime.now(BR).date()
    conn = _conexao()
    try:
        cur = conn.cursor()
        garantir_tabelas(cur)
        conn.commit()
        cur.execute("""
            SELECT tarefa, dia, origem, iniciado_em, terminado_em, status, detalhe
              FROM agendador_execucoes WHERE dia >= %s::date - 1
             ORDER BY iniciado_em DESC
        """, (dia,))
        execucoes = [dict(r) for r in cur.fetchall()]
        cur.execute("""
            SELECT DISTINCT ON (nome) nome, dia, saida, ok, criado_em
              FROM medicoes_do_motor ORDER BY nome, dia DESC
        """)
        medicoes = {r["nome"]: dict(r) for r in cur.fetchall()}
    finally:
        conn.close()
    hoje = {e["tarefa"]: e for e in execucoes if e["dia"] == dia}
    return {
        "ligado": habilitado(),
        "teto_cota": teto_de_cota(),
        "tarefas": [{
            "nome": t.nome, "rotulo": t.rotulo, "inicio": t.inicio.strftime("%H:%M"),
            "gasta_api": t.gasta_api,
            "hoje": {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                     for k, v in (hoje.get(t.nome) or {}).items()} or None,
        } for t in TAREFAS],
        "medicoes": [{
            "nome": nome, "rotulo": rotulo,
            **({k: (v.isoformat() if hasattr(v, "isoformat") else v)
                for k, v in medicoes[nome].items()} if nome in medicoes else {}),
        } for nome, rotulo, _, _ in MEDICOES],
    }
