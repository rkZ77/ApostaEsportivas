"""Log de decisao do motor deterministico -- registra, pra cada fixture
processado por qualquer engine_pipelines/*.py, TODOS os candidatos
avaliados (nao so o escolhido) com seus scores completos. Objetivo:
dar visibilidade real do "por que" um mercado venceu outro, sem precisar
reproduzir manualmente toda vez que algo parecer estranho (ex: motor
"só escolhendo cartão" -- com esse log da pra ver na hora se e sinal
real ou algum termo do Score Final dominando os outros).

ONDE GRAVA (mudou em 2026-08-07)
--------------------------------
Tres destinos, em ordem de durabilidade:

  1. tabela `engine_decisions` no Postgres  <- fonte de verdade
  2. logs/engine_decisions.jsonl            <- conveniencia local
  3. resumo legivel no stdout               <- acompanhar a rodada ao vivo

O arquivo era o unico destino ate 2026-08-07 e em producao ele nao existe na
pratica: o Dockerfile copia `src/` pra `/app/pipeline/`, entao LOGS_DIR resolve
pra `/app/logs`, que e' filesystem de container sem volume no Railway -- some
em todo deploy e todo restart. O resultado era que a pergunta "por que o Free
nao gerou hoje?" so' tinha resposta se alguem estivesse olhando o stdout na
hora. Foi exatamente o que aconteceu em 07/08 (ver log_skip abaixo).

O QUE MAIS FALTAVA
------------------
Registrar o fixture que o pipeline AVALIOU nao bastava: o motor descarta jogo
antes disso, em `continue` mudo (sem odds estruturadas, sem historico,
historico reprovado). Em 07/08 o unico jogo livre do dia (Estoril x Famalicao)
caiu num desses -- os dois times tinham zero jogos coletados -- e o dia inteiro
ficou sem Free sem nenhuma linha de log explicando. `log_skip` cobre esse caso,
e `log_run` cobre o pipeline que termina sem candidato nenhum.

Nada aqui derruba pipeline: toda falha de log e' engolida e so' avisada.
"""
import os
import json
from datetime import datetime

from utils.db_utils import get_connection
from utils.data_br import HOJE_BR
from utils.paths import LOGS_DIR as LOG_DIR, log_path

LOG_PATH = log_path("engine_decisions.jsonl")

# Status possiveis de uma linha em engine_decisions.
STATUS_AVALIADO = "avaliado"      # fixture rodou o motor; candidates preenchido
STATUS_DESCARTADO = "descartado"  # fixture caiu antes do motor; reason explica
STATUS_SEM_PICK = "sem_pick"      # pipeline terminou sem candidato (fixture NULL)

_tabela_pronta = False


#: Colunas que a auditoria acrescentou em 2026-08-27, e que o INSERT deste
#: modulo escreve. Vira tambem a CONFERENCIA de "o banco ja esta em dia?".
_COLUNAS_DA_AUDITORIA = (
    ("run_id", "TEXT"), ("engine", "TEXT"), ("method", "TEXT"),
    ("engine_version", "TEXT"), ("score", "NUMERIC"),
    ("probability", "NUMERIC"), ("odd", "NUMERIC"),
    ("pick_table", "TEXT"), ("pick_id", "BIGINT"),
)


def _ja_esta_em_dia(cur) -> bool:
    """A tabela existe e tem todas as colunas? Pergunta barata, SEM LOCK.

    POR QUE ISTO EXISTE (2026-09-05) -- ELE TRAVAVA O SITE
    ------------------------------------------------------
    Esta funcao emitia CREATE TABLE IF NOT EXISTS + nove ALTER TABLE ADD COLUMN
    IF NOT EXISTS + tres CREATE INDEX A CADA EXECUCAO de motor. Os "IF NOT
    EXISTS" fazem o comando nao ter EFEITO quando esta tudo no lugar, mas nao
    o impedem de PEDIR o lock: ALTER TABLE pede ACCESS EXCLUSIVE, que nao
    convive com nada -- nem com leitura.

    O estrago nao e' a lentidao do motor, e' o que acontece com quem le':
    basta o site ter UMA transacao aberta na tabela (qualquer consulta da aba
    de Auditoria) pra o ALTER entrar na fila -- e, uma vez na fila, TODA
    leitura que chega depois fica atras dele. Medido em DEV: leitura simples
    que roda em 0,2s levou 118,7 segundos, e o proprio ALTER morreu de
    statement timeout aos 122s.

    Perguntar ao catalogo antes custa uma consulta e nao pega lock nenhum.
    Num banco que ja esta em dia -- que e' TODA execucao depois da primeira --
    nenhum DDL e' emitido e o site nao sente o motor rodar.
    """
    cur.execute("SELECT to_regclass('public.engine_decisions') IS NOT NULL")
    if not cur.fetchone()[0]:
        return False
    cur.execute("""SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'engine_decisions'""")
    existentes = {r[0] for r in cur.fetchall()}
    return all(coluna in existentes for coluna, _ in _COLUNAS_DA_AUDITORIA)


def _ensure_table() -> None:
    global _tabela_pronta
    if _tabela_pronta:
        return
    conn = get_connection()
    cur = conn.cursor()
    if _ja_esta_em_dia(cur):
        cur.close()
        conn.close()
        _tabela_pronta = True
        return
    # SO' O CAMINHO DE MIGRACAO CHEGA AQUI, e ele nao pode esperar em fila:
    # `lock_timeout` faz o DDL desistir em 3s em vez de bloquear o site. Se
    # desistir, `_tabela_pronta` fica False e a proxima execucao tenta de novo
    # -- e o INSERT que vem a seguir cai no except que ja existe, com aviso.
    cur.execute("SET lock_timeout = '3s'")
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
    # As colunas ficam aqui, e nao so' em services/engine_audit, porque QUEM
    # CHEGA PRIMEIRO no banco cria: um pipeline de pre-jogo rodando sozinho
    # comeca por este modulo, e o INSERT logo abaixo ja' escreve
    # run_id/engine/method. Sem os ALTER aqui, um banco com a tabela antiga
    # quebraria em toda linha de log ate' alguem rodar um motor novo.
    for coluna, tipo in _COLUNAS_DA_AUDITORIA:
        cur.execute(f"ALTER TABLE engine_decisions ADD COLUMN IF NOT EXISTS {coluna} {tipo}")
    # A consulta real e' sempre "o que aconteceu no dia X no pipeline Y".
    cur.execute("CREATE INDEX IF NOT EXISTS idx_engine_decisions_dia "
                "ON engine_decisions (match_date DESC, pipeline)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_engine_decisions_run "
                "ON engine_decisions (run_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_engine_decisions_fixture "
                "ON engine_decisions (fixture_id)")
    conn.commit()
    cur.close()
    conn.close()
    _tabela_pronta = True


def _carimbo_da_execucao(pipeline: str) -> tuple:
    """(run_id, engine, method, engine_version) da execucao em andamento.

    ACRESCENTADO EM 2026-08-27, e de proposito ninguem precisa passar nada.
    O Engine Audit mantem a execucao corrente num ContextVar, entao embrulhar
    `run_vip_engine()` num `with EngineRun(...)` basta pra TODAS as linhas que
    este modulo ja' gravava passarem a ter run_id -- sem tocar em nenhuma das
    chamadas de log_skip/log_decision espalhadas pelo fundo dos pipelines.

    Fora de uma execucao auditada (rodar o pipeline direto, backtest, teste),
    devolve o motor/metodo resolvidos pelo nome do pipeline e run_id None. A
    linha continua sendo gravada: o log e' anterior a auditoria e nao pode
    passar a depender dela.
    """
    try:
        from services.engine_audit import audit as _audit
        from services.engine_audit import registry as _registry

        run = _audit.run_atual()
        if run is not None and run.pipeline == pipeline:
            return (run.run_id, run.motor, run.metodo, run.versao)
        motor, metodo, versao = _registry.resolver_pipeline(pipeline)
        return (run.run_id if run is not None else None, motor, metodo, versao)
    except Exception:
        # Auditoria indisponivel nao pode impedir o log de decisao, que
        # funciona sozinho desde 07/08.
        return (None, None, None, None)


def _contabilizar_na_execucao(pipeline: str, status: str) -> None:
    """Soma este jogo nas contagens da execucao auditada, se houver uma.

    Mesmo raciocinio do carimbo de run_id logo acima: o pipeline nao passa
    nada, quem sabe da execucao e' o ContextVar. Sem isto, a aba de Auditoria
    lia zero em analisados/descartados pra todo motor de pre-jogo -- eles
    gravam a linha por jogo por aqui, nunca por EngineRun.analisado().
    """
    try:
        from services.engine_audit import audit as _audit

        run = _audit.run_atual()
        if run is not None and run.pipeline == pipeline:
            run.contabilizar(status)
    except Exception:
        # Auditoria nunca derruba log, que nunca derruba motor.
        pass


def registrar_selecao(pipeline: str, fixtures, pick_id: int | None = None) -> None:
    """Os jogos desta execucao que viraram pick. Chamar DEPOIS de gravar.

    `fixtures` e' a lista de fixture_id que entraram no pick (uma so' nos
    produtos de perna unica, as pernas todas na multipla e na alavancagem).

    FAZ DUAS COISAS, e a segunda e' a que importa
    ---------------------------------------------
    Alem de mover a contagem da aba de Auditoria, carimba na linha de
    `engine_decisions` daquele jogo o vinculo com o pick gerado: status
    'selecionado', `pick_table` e `pick_id`.

    Sem esse vinculo a aba responde "o que o motor viu naquele dia", que e'
    uma pergunta de arqueologia. Com ele responde a pergunta que se faz de
    verdade: PEGUEI UM RED, POR QUE O MOTOR ESCOLHEU ISSO -- a linha do pick
    leva direto ao candidato escolhido, aos que perderam, aos scores parciais
    e ao contexto do instante da decisao. Ate' aqui so' o Pick Boost e o
    Player Stats gravavam esse vinculo (eles chamam EngineRun.analisado com
    pick_id); todo produto de pre-jogo dependia de casar por partida, que
    erra sempre que o mesmo jogo produz pick em dois produtos.

    `pick_id` explicito e' pra o bilhete combinado: multipla e alavancagem tem
    UM pick pra varias pernas, entao todas as pernas apontam pro mesmo id. Nos
    produtos de perna unica ele sai de uma busca por (fixture_id, match_date)
    na tabela do proprio produto -- evita fazer cada pipeline devolver o id do
    INSERT, que em tres deles e' um INSERT ... SELECT com guarda de duplicata.

    Fora de uma execucao auditada, no-op. Nada aqui pode derrubar o motor.
    """
    fixtures = [f for f in (fixtures if isinstance(fixtures, (list, tuple, set))
                            else [fixtures]) if f]
    try:
        from services.engine_audit import audit as _audit

        run = _audit.run_atual()
        if run is None or run.pipeline != pipeline:
            return
        # Lista vazia com pick_id vazio = nao salvou nada. Chamar assim mesmo e'
        # o caso normal do VIP, que avisa uma vez depois do laco -- inclusive
        # nos dias em que o laco nao salvou pick nenhum. O `or 1` que estava
        # aqui transformava esse dia em "1 selecionado" e a aba de Auditoria
        # contradizia a propria saida do motor ("0 picks salvos").
        if not fixtures and pick_id is None:
            return
        run.selecionou(len(fixtures) or 1)
        if not run.run_id or not fixtures or not run.tabela_picks:
            return
        _vincular_pick(run, fixtures, pick_id)
    except Exception as e:
        print(f"[DECISION_LOG] Aviso: falha ao vincular pick (não afeta o pick): {e}")


def _vincular_pick(run, fixtures: list, pick_id: int | None) -> None:
    """UPDATE nas linhas desta execucao · status, pick_table e pick_id."""
    tabela = run.tabela_picks
    if pick_id is not None:
        # Bilhete combinado: todas as pernas apontam pro mesmo pick.
        alvo, params = "%s", [tabela, pick_id]
    else:
        # Perna unica: o id sai da propria tabela do produto. `ORDER BY id
        # DESC` porque um jogo pode ter pick antigo do mesmo dia (re-execucao);
        # o vinculo e' com o mais recente, que e' o que acabou de ser gravado.
        alvo = (f"(SELECT p.id FROM {tabela} p "
                " WHERE p.fixture_id = d.fixture_id AND p.match_date = d.match_date"
                " ORDER BY p.id DESC LIMIT 1)")
        params = [tabela]

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"""
            UPDATE engine_decisions d
               SET status = 'selecionado',
                   pick_table = %s,
                   pick_id = {alvo}
             WHERE d.run_id = %s AND d.fixture_id = ANY(%s)
        """, (*params, run.run_id, list(fixtures)))
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _gravar(pipeline: str, fixture: dict | None, status: str, reason: str | None,
            candidates: list, matchup: dict | None, context_data: dict | None) -> None:
    """Um INSERT por chamada. Conexao propria de proposito: log_decision e'
    chamado de dentro de funcoes que nao tem cursor a mao
    (_best_candidate_across_fixtures, _gather_leg_candidates), e passar cursor
    por parametro ate' la' acoplaria o motor ao log."""
    fixture = fixture or {}
    run_id, engine, method, versao = _carimbo_da_execucao(pipeline)
    _contabilizar_na_execucao(pipeline, status)
    try:
        _ensure_table()
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            f"""INSERT INTO engine_decisions
            (match_date, pipeline, fixture_id, home_team, away_team, status, reason,
             candidates, matchup, context, run_id, engine, method, engine_version)
            VALUES ({HOJE_BR}, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s)""",
            (pipeline, fixture.get("fixture_id"), fixture.get("home_team"),
             fixture.get("away_team"), status, reason,
             json.dumps(candidates, ensure_ascii=False, default=str),
             json.dumps(matchup, ensure_ascii=False, default=str) if matchup else None,
             json.dumps(context_data, ensure_ascii=False, default=str) if context_data else None,
             run_id, engine, method, versao),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[DECISION_LOG] Aviso: falha ao gravar no banco (não afeta o pick): {e}")


def _gravar_arquivo(entry: dict) -> bool:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        return True
    except Exception as e:
        print(f"[DECISION_LOG] Aviso: falha ao gravar arquivo (não afeta o pick): {e}")
        return False


def _candidate_summary(c: dict) -> dict:
    # faltas/goleiros nao passam pelo caminho generico do motor: os candidatos
    # deles vem de fouls_model/goalkeeper_model, com outro formato (`line` e
    # `probability` no lugar de `value_label` e `taxa_real`, sem `final_score`
    # nem os scores parciais). Sem esses fallbacks o resumo quebrava em toda
    # chamada desses dois pipelines -- o log em disco ate' era gravado, mas a
    # excecao no _print_summary caia no except de log_decision e imprimia
    # "falha ao gravar log", mensagem que apontava pro lugar errado.
    return {
        "market_type": c.get("market_type") or c.get("modelo"),
        "line": c.get("value_label") or c.get("line"),
        "odd": c.get("odd"),
        "taxa_real": c.get("taxa_real", c.get("probability")),
        "amostra": c.get("amostra", c.get("faixa_amostra")),
        "confidence": c.get("confidence", c.get("probability")),
        "ev": c.get("ev"),
        "edge": c.get("edge"),
        "context_score": c.get("context_score"),
        "profile_score": c.get("profile_score"),
        "news_score": c.get("news_score"),
        "line_score": c.get("line_score"),
        "final_score": c.get("final_score"),
        "is_best_pick": c.get("is_best_pick", False),
        # Sobrescrito em log_decision() com a presenca real em eligible_picks.
        "eligible": c.get("final_score") is not None,
    }


def _rastro_summary(item: dict) -> dict:
    """Uma linha/familia do rastro do motor, no molde de candidato.

    Vai pro MESMO array `candidates` de proposito. A tela do admin ja' sabe
    desenhar essa lista, e o que faltava nela nao era um bloco novo -- era o
    resto dos mercados. Cada item traz `nivel` ('linha' | 'familia') e
    `rastro_status` pra a tela poder separar "morreu antes da conta" de
    "perdeu depois de calculada".
    """
    return {
        "origem": "rastro",
        "nivel": item.get("nivel"),
        "rastro_status": item.get("status"),
        "market_type": item.get("market_type"),
        "scope": item.get("scope"),
        "market_name": item.get("market_name"),
        "line": item.get("line"),
        "direcao": item.get("direcao"),
        "odd": item.get("odd"),
        "taxa_real": item.get("taxa_real"),
        "amostra": item.get("amostra"),
        "ev": item.get("ev"),
        "edge": item.get("edge"),
        "line_score": item.get("line_score"),
        "confidence": None,
        "final_score": None,
        "eligible": False,
        "is_best_pick": False,
        "motivos_reprovacao": [item["motivo"]] if item.get("motivo") else [],
    }


def log_decision(pipeline: str, fixture: dict, all_candidates: list,
                  eligible_picks: list, matchup: dict | None = None,
                  context_data: dict | None = None,
                  rastro: list | None = None) -> None:
    """Chamar logo depois de analyze_fixture_markets()+rank_market_candidates()
    pra cada fixture. `all_candidates` = saida de analyze_fixture_markets
    (todos os mercados, mesmo os que nao passaram no filtro minimo -- esses
    nao tem 'final_score' calculado, aparecem com eligible=False).
    `eligible_picks` = saida de rank_market_candidates (so os aprovados).

    `rastro` = a lista que o motor preencheu (orchestrator._rastrear). Sem
    ela o log guardava UMA linha por familia -- a vencedora -- e a tela do
    admin mostrava "gols Under 2.5" como se o mercado de gols fosse so'
    aquilo. Com ela entram tambem as outras linhas do mesmo mercado (o Over
    que perdeu, a linha vizinha), as que nem foram calculadas (odd fora da
    faixa do pipeline) e as familias inteiras eliminadas antes -- cada uma
    com o motivo nomeado.
    """
    try:
        candidates_summary = []
        for c in all_candidates:
            key = (c.get("market_type"), c.get("value_label"))
            matched = next((p for p in eligible_picks
                            if (p.get("market_type"), p.get("value_label")) == key), None)
            summary = _candidate_summary(matched if matched else c)
            # Aprovado e' quem saiu em eligible_picks, nao quem tem
            # final_score. Faltas/goleiros nao calculam final_score (modelo
            # proprio, ver _candidate_summary), entao pelo criterio antigo o
            # pick ESCOLHIDO aparecia no log como "REJEITADO".
            summary["eligible"] = matched is not None
            summary["origem"] = "candidato"
            summary["nivel"] = "mercado"
            candidates_summary.append(summary)
        # A linha vencedora de cada mercado ja' entrou acima, como candidato.
        # Repeti-la aqui faria a tela mostrar o mesmo pick duas vezes.
        for item in (rastro or []):
            if item.get("escolhida_do_mercado"):
                continue
            candidates_summary.append(_rastro_summary(item))
    except Exception as e:
        print(f"[DECISION_LOG] Aviso: falha ao montar resumo (não afeta o pick): {e}")
        return

    _gravar(pipeline, fixture, STATUS_AVALIADO, None, candidates_summary, matchup, context_data)
    _gravar_arquivo({
        "logged_at": datetime.now().isoformat(),
        "pipeline": pipeline,
        "status": STATUS_AVALIADO,
        "fixture_id": fixture.get("fixture_id"),
        "home_team": fixture.get("home_team"),
        "away_team": fixture.get("away_team"),
        "matchup": matchup,
        "context": context_data,
        "candidates": candidates_summary,
    })

    # Fora do try do arquivo de proposito: falha ao IMPRIMIR nao e' falha ao
    # GRAVAR, e a mensagem generica acima ja' mandou investigar o lugar errado
    # uma vez (ver _candidate_summary).
    try:
        # So' os MERCADOS no stdout. O rastro pode ter 40 linhas por partida
        # (toda linha de todo mercado cotado) -- no banco isso e' o que se
        # queria, no terminal de uma rodada com 14 jogos e' ilegivel.
        _print_summary(pipeline, fixture,
                       [c for c in candidates_summary if c.get("origem") != "rastro"])
    except Exception as e:
        print(f"[DECISION_LOG] Aviso: log gravado, falha só ao imprimir o resumo: {e}")


def log_skip(pipeline: str, fixture: dict, reason: str,
             context_data: dict | None = None) -> None:
    """Fixture descartado ANTES de rodar o motor.

    Todo `continue` mudo do pipeline passa a ter uma linha aqui. Sem isso, o
    jogo simplesmente nao aparecia em lugar nenhum -- nem como avaliado, nem
    como rejeitado -- e a unica leitura possivel era "o motor ignorou o jogo",
    que nao diz se faltou odd, faltou historico ou o historico reprovou.

    `reason` e' texto curto e estavel (vira filtro em SQL depois): use as
    constantes MOTIVO_* abaixo em vez de escrever a frase na mao.
    """
    _gravar(pipeline, fixture, STATUS_DESCARTADO, reason, [], None, context_data)
    _gravar_arquivo({
        "logged_at": datetime.now().isoformat(),
        "pipeline": pipeline,
        "status": STATUS_DESCARTADO,
        "fixture_id": fixture.get("fixture_id"),
        "home_team": fixture.get("home_team"),
        "away_team": fixture.get("away_team"),
        "reason": reason,
        "context": context_data,
    })
    print(f"[DECISION_LOG] {pipeline} | {fixture.get('home_team')} x {fixture.get('away_team')} "
          f"(fixture {fixture.get('fixture_id')}) DESCARTADO: {reason}")


def log_run(pipeline: str, reason: str,
            context_data: dict | None = None) -> None:
    """Pipeline terminou sem candidato nenhum (fixture_id NULL).

    Faltas e goleiros precisam disso mais que os outros: os dois so' chamavam
    log_decision dentro do loop de candidatos, entao dia sem candidato nao
    gerava linha nenhuma e ficava impossivel distinguir "avaliou e nao achou"
    de "nem rodou" -- especialmente em goleiros, onde defesa aparece em 0.86%
    das atuacoes e o dia vazio e' o caso NORMAL, nao a excecao.
    """
    _gravar(pipeline, None, STATUS_SEM_PICK, reason, [], None, context_data)
    _gravar_arquivo({
        "logged_at": datetime.now().isoformat(),
        "pipeline": pipeline,
        "status": STATUS_SEM_PICK,
        "reason": reason,
        "context": context_data,
    })


# Motivos de descarte. Constantes porque viram filtro de SQL ("quantos jogos o
# motor perdeu por falta de historico esta semana?") -- frase escrita na mao em
# cada pipeline nao agrupa.
MOTIVO_SEM_ODDS = "sem odds estruturadas"
MOTIVO_SEM_HISTORICO = "sem historico coletado para um dos times"
MOTIVO_HISTORICO_REPROVADO = "historico reprovado na validacao (amostra curta ou inconsistente)"
MOTIVO_SEM_CANDIDATO = "nenhum candidato passou nos criterios do modelo"
MOTIVO_ERRO = "erro ao avaliar o fixture"


# ─────────────────────────────────────────────────────────────────────────
# MOTOR AO VIVO
# ─────────────────────────────────────────────────────────────────────────
#
# POR QUE O LIVE PRECISAVA ENTRAR AQUI (2026-08-24)
# -------------------------------------------------
# Os seis pipelines de pre-jogo gravam em `engine_decisions` desde 07/08. O
# motor ao vivo era o unico que nao gravava -- e e' justamente o que mais
# precisa, por tres motivos que os outros nao tem:
#
#   1. ele roda em laco. Uma noite de 23/08 deu 91 rodadas; a unica coisa que
#      sobrevivia delas era o stdout da ULTIMA, guardado em memoria no
#      processo do site (`routers/live_picks.py::_run_status`, 6000 chars) e
#      perdido no primeiro deploy. 90 rodadas sem rastro nenhum;
#   2. a decisao dele depende do MINUTO. A mesma partida aos 20' e aos 70' e'
#      outra decisao, e "por que nao saiu pick" nao tem resposta sem saber em
#      que minuto cada leg morreu;
#   3. ele nasceu em dry run. Em dry run `picks_live` fica vazia POR
#      CONSTRUCAO, entao a tabela de picks nao distingue "o motor nao achou
#      nada" de "o motor achou e nao tinha permissao de gravar". Este log
#      distingue: o candidato aprovado aparece aqui mesmo quando o pick nao e'
#      gravado.
#
# O `context` carrega o minuto e o retrato da rodada, e nao uma coluna nova:
# `engine_decisions` ja' existe em PROD com dados dos outros pipelines, e
# acrescentar coluna a uma tabela viva por causa de um consumidor novo custa
# mais que um campo JSONB que ja' esta' la'.
PIPELINE_LIVE = "LIVE_ENGINE"

#: Motivos de descarte do ao vivo. Curtos e estaveis, mesma regra dos MOTIVO_*
#: de cima: viram GROUP BY depois ("onde as partidas estao morrendo?").
LIVE_SEM_ESTATISTICA = "provedor nao publicou estatistica das familias"
LIVE_REPROVOU_TRIAGEM = "triagem: projecao colada no esperado"
LIVE_SEM_ORCAMENTO = "orcamento de API esgotado antes da odd"
LIVE_SEM_LINHA = "sem linha ativa nas familias triadas"
LIVE_NENHUM_APROVADO = "nenhum candidato passou nos gates"
LIVE_DUPLICATA = "pick equivalente ja' existe nesta partida"


def _live_candidate_summary(c: dict) -> dict:
    """Candidato do motor ao vivo, no formato dele.

    Nao reusa `_candidate_summary` de proposito: ao vivo nao existe
    `final_score` nem `taxa_real`. Existe uma probabilidade RESIDUAL (do tempo
    que falta), o quanto ela foi encolhida contra o mercado, e a lista de
    gates que reprovaram. Passar isso pelo molde do pre-jogo produziria um log
    de campos nulos sem a unica coluna que responde a pergunta -- que e'
    `motivos_reprovacao`.

    `prob_modelo_puro` e `probability` ficam os dois no log de proposito: a
    subtracao entre eles e' a medida do encolhimento contra o mercado, e sem
    as duas ela exige reproduzir a rodada.
    """
    return {
        "market_type": c.get("market") or c.get("familia"),
        "line": c.get("line"),
        "direcao": c.get("direcao"),
        "odd": c.get("odd"),
        "probability": c.get("probability"),
        "prob_modelo_puro": c.get("prob_modelo_puro"),
        "peso_modelo": c.get("peso_modelo"),
        "prob_mercado": c.get("prob_mercado"),
        "origem_prob_mercado": c.get("origem_prob_mercado"),
        "ev": c.get("ev"),
        "edge": c.get("edge"),
        "confidence": c.get("confidence"),
        "live_signal_score": c.get("live_signal_score"),
        "observado_na_criacao": c.get("observado_na_criacao"),
        "projecao_total": c.get("projecao_total"),
        "distancia_da_linha": c.get("distancia_da_linha"),
        "eligible": bool(c.get("aprovado")),
        # A razao inteira deste log existir. `avaliar()` devolve TODOS os
        # motivos, sem short-circuit -- um candidato pode cair por EV e por
        # convergencia, e saber os dois e' o que diz qual limiar mexer.
        "motivos_reprovacao": c.get("motivos_reprovacao") or [],
        "is_best_pick": bool(c.get("is_best_pick")),
    }


def log_live_decision(fixture: dict, avaliados: list,
                      context_data: dict | None = None,
                      escolhido: dict | None = None) -> None:
    """Uma linha por partida AVALIADA numa rodada do motor ao vivo.

    Chamar depois de `orchestrator.avaliar()`, com a lista inteira -- aprovados
    e reprovados. Nao imprime nada: `live_pipeline._processar_partida` ja'
    imprime o resumo da partida, e duplicar isso no stdout de um laco que roda
    de 3 em 3 minutos so' torna o log ao vivo ilegivel.
    """
    try:
        chave = None
        if escolhido:
            chave = (escolhido.get("market"), escolhido.get("line"),
                     escolhido.get("direcao"))
        resumo = []
        for c in avaliados:
            item = _live_candidate_summary(c)
            if chave and (c.get("market"), c.get("line"), c.get("direcao")) == chave:
                item["is_best_pick"] = True
            resumo.append(item)
    except Exception as e:
        print(f"[DECISION_LOG] Aviso: falha ao montar resumo do live (não afeta o pick): {e}")
        return

    _gravar(PIPELINE_LIVE, fixture, STATUS_AVALIADO, None, resumo, None, context_data)
    _gravar_arquivo({
        "logged_at": datetime.now().isoformat(),
        "pipeline": PIPELINE_LIVE,
        "status": STATUS_AVALIADO,
        "fixture_id": fixture.get("fixture_id"),
        "home_team": fixture.get("home_team"),
        "away_team": fixture.get("away_team"),
        "context": context_data,
        "candidates": resumo,
    })


def _pct(v) -> str:
    """Campo ausente vira '  n/d' em vez de estourar o format (candidatos de
    faltas/goleiros nao tem todos os campos do caminho generico)."""
    return f"{v * 100:5.1f}%" if isinstance(v, (int, float)) else "  n/d"


def _print_summary(pipeline: str, fixture: dict, candidates_summary: list) -> None:
    print(f"[DECISION_LOG] {pipeline} | {fixture.get('home_team')} x {fixture.get('away_team')} "
          f"(fixture {fixture.get('fixture_id')})")
    for c in sorted(candidates_summary, key=lambda x: x.get("final_score") or -1, reverse=True):
        marker = " <== ESCOLHIDO" if c["is_best_pick"] else ""
        mt   = str(c.get("market_type") or "?")
        line = str(c.get("line") or "?")
        if c["eligible"]:
            print(f"    [{mt:<12}] {line:<14} taxa={_pct(c['taxa_real'])} "
                  f"amostra={str(c['amostra'] or '-'):<3} conf={_pct(c['confidence'])} ev={_pct(c['ev'])} "
                  f"ctx={c['context_score']} perfil={c['profile_score']} line_score={c['line_score']} "
                  f"score_final={c['final_score']}{marker}")
        else:
            print(f"    [{mt:<12}] {line:<14} REJEITADO (não passou nos critérios mínimos: "
                  f"taxa={_pct(c['taxa_real'])} amostra={c['amostra']} conf={_pct(c['confidence'])})")
