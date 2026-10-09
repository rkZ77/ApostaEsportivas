"""Reavaliacao dos picks publicados perto do apito (2026-10-08).

POR QUE EXISTE
--------------
O pick e' decidido de manha. Ate' o apito saem noticias (lesao no
aquecimento, suspensao confirmada), a escalacao oficial e o movimento de
preco. Nada disso voltava ao pick: ele ficava anunciado com a conta da manha.

QUANDO RODA
-----------
Dentro do `fechamento` (capturar_fechamento.py), logo depois do retrato de
odds de 30 min antes do apito -- a mesma passada, o mesmo jogo. Custo extra:
UMA requisicao de /injuries por partida (devolve os dois times). A escalacao
oficial vem de `fixture_lineups` quando a varredura do site ja' a gravou;
odds vem do retrato que o fechamento acabou de tirar. `MOTOR_REAVALIAR=off`
desliga.

O QUE FAZ
---------
Pra cada pick pendente de VIP e Free do jogo:
  1. ODD DE AGORA  mediana das casas no retrato de fechamento. Linha que
                   nenhuma casa cota mais vira alerta.
  2. NOTICIA NOVA  quem esta' "Missing Fixture" AGORA e NAO estava no
                   instante da previsao (engine_debug.contexto_atual.partida.
                   desfalques_ids), mais titular habitual fora do XI oficial.
                   So' o que e' novo: o que ja' estava na conta nao conta duas
                   vezes.
  3. CONTA         a mesma do contexto atual: fracao da producao que a
                   familia conta perdida com os novos ausentes -> amostra
                   efetiva -> probabilidade puxada pro preco de agora na mesma
                   proporcao do encolhimento (contexto_atual.
                   ajuste_para_modelo_proprio). EV de agora com ela.
  4. REGISTRO      linha em `reavaliacao_picks` com tudo isso e um `alerta`
                   quando a linha sumiu ou o EV reavaliado deixou de ser
                   positivo.

O QUE NAO FAZ
-------------
Nao cancela nem altera pick publicado. Anular aposta que o assinante ja' pode
ter seguido e' decisao de produto, nao do motor; o alerta fica gravado pra
essa decisao (e pra medir se os alertados de fato rendem menos).

Sem vazamento: tudo aqui e' consultado ANTES do apito, e a linha guarda o
instante. Liquidacao e medicao leem o resultado depois.
"""
from __future__ import annotations

import json
import os
from statistics import median

from services.pick_engine import contexto_atual
from services.pick_engine.config import DEFAULT_CONFIG

DDL = (
    """CREATE TABLE IF NOT EXISTS reavaliacao_picks (
        id               BIGSERIAL PRIMARY KEY,
        pick_table       TEXT NOT NULL,
        pick_id          INTEGER NOT NULL,
        fixture_id       INTEGER NOT NULL,
        reavaliado_em    TIMESTAMP DEFAULT NOW(),
        odd_publicada    NUMERIC,
        odd_agora        NUMERIC,
        prob_publicada   NUMERIC,
        prob_reavaliada  NUMERIC,
        ev_publicado     NUMERIC,
        ev_agora         NUMERIC,
        ev_reavaliado    NUMERIC,
        novos_ausentes   JSONB,
        fracao_perdida   NUMERIC,
        alerta           TEXT,
        detalhe          JSONB
    )""",
    "CREATE INDEX IF NOT EXISTS idx_reavaliacao_pick ON reavaliacao_picks (pick_table, pick_id)",
)

#: Retrato de odd mais velho que isto nao e' "de agora".
_RETRATO_MAX_MIN = 45


def habilitada() -> bool:
    return os.getenv("MOTOR_REAVALIAR", "on").strip().lower() != "off"


def _injuries_da_partida(fixture_id: int) -> tuple:
    """({team_id: set(ids fora)}, falha ou None). Uma requisicao, dois times."""
    try:
        from utils.api_client import buscar
        resposta = buscar("injuries", {"fixture": fixture_id}, origem="motor_reavaliacao")
    except Exception as e:
        return None, str(e)[:200]
    fora: dict = {}
    for item in resposta or []:
        jogador = item.get("player") or {}
        time_ = (item.get("team") or {}).get("id")
        if (time_ and jogador.get("id")
                and (jogador.get("type") or item.get("type") or "").lower() == "missing fixture"):
            fora.setdefault(time_, set()).add(jogador["id"])
    return fora, None


def _fora_do_xi(cur, fixture_id: int, team_id: int, quando) -> set:
    """Titular habitual (2+ inicios nos ultimos 5) que nao esta' no XI oficial.
    Vazio quando a escalacao oficial ainda nao foi gravada."""
    try:
        cur.execute("SELECT titulares FROM fixture_lineups WHERE fixture_id = %s AND oficial",
                    (fixture_id,))
        linha = cur.fetchone()
        if not linha or not linha[0]:
            return set()
        xi = set(linha[0])
        cur.execute("""
            SELECT titulares FROM team_lineups
             WHERE team_id = %s AND match_date < %s
             ORDER BY match_date DESC LIMIT 5
        """, (team_id, quando))
        inicios: dict = {}
        for (titulares,) in cur.fetchall():
            for pid in titulares or []:
                inicios[pid] = inicios.get(pid, 0) + 1
        return {pid for pid, n in inicios.items() if n >= 2 and pid not in xi}
    except Exception:
        cur.connection.rollback()
        return set()


_OPOSTO = {"over": "under", "under": "over", "yes": "no", "no": "yes"}


def _mediana_no_retrato(cur, fixture_id: int, market_id, value_name: str) -> float | None:
    cur.execute("""
        SELECT odd_value FROM odds_snapshots
         WHERE fixture_id = %s AND market_id = %s
           AND LOWER(TRIM(value_name)) = LOWER(TRIM(%s))
           AND captured_at >= NOW() - (%s * INTERVAL '1 minute')
    """, (fixture_id, market_id, value_name, _RETRATO_MAX_MIN))
    odds = [float(r[0]) for r in cur.fetchall() if r[0] and float(r[0]) > 1]
    return round(median(odds), 3) if odds else None


def _tem_xi_oficial(cur, fixture_id: int) -> bool:
    try:
        cur.execute("SELECT 1 FROM fixture_lineups WHERE fixture_id = %s AND oficial",
                    (fixture_id,))
        return cur.fetchone() is not None
    except Exception:
        cur.connection.rollback()
        return False


def esperando_escalacao(cur, fixture_ids) -> list:
    """Jogos ja' reavaliados SEM o XI oficial, cuja escalacao saiu depois, e
    que ainda nao comecaram. O fechamento tira o retrato a ~30 min do apito e
    a escalacao sai de 20 a 40 min antes -- na maioria dos jogos a primeira
    reavaliacao chega antes dela. Esta e' a segunda passada."""
    if not fixture_ids:
        return []
    try:
        cur.execute("""
            SELECT r.fixture_id
              FROM reavaliacao_picks r
              JOIN fixture_lineups fl ON fl.fixture_id = r.fixture_id AND fl.oficial
              JOIN fixtures f ON f.fixture_id = r.fixture_id
             WHERE r.fixture_id = ANY(%s)
               AND f.status IN ('NS', 'TBD')
             GROUP BY r.fixture_id, fl.atualizado_em
            HAVING BOOL_AND(NOT COALESCE((r.detalhe->>'xi_oficial')::boolean, FALSE))
               AND fl.atualizado_em > MAX(r.reavaliado_em)
        """, (list(fixture_ids),))
        return [r[0] for r in cur.fetchall()]
    except Exception:
        cur.connection.rollback()
        return []


def _odd_de_agora(cur, fixture_id: int, market_id, linha: str) -> tuple:
    """(mediana da linha, probabilidade justa sem margem ou None). A justa sai
    do par (Over/Under, Sim/Nao) no mesmo retrato; sem o par, None -- e quem
    chama cai em 1/odd."""
    odd = _mediana_no_retrato(cur, fixture_id, market_id, linha)
    partes = (linha or "").strip().split(" ", 1)
    oposto = _OPOSTO.get(partes[0].lower()) if partes else None
    if odd is None or not oposto:
        return odd, None
    nome_oposto = oposto.capitalize() + (" " + partes[1] if len(partes) > 1 else "")
    odd_oposta = _mediana_no_retrato(cur, fixture_id, market_id, nome_oposto)
    if not odd_oposta:
        return odd, None
    from services.pick_engine.market_model import no_vig_pair_prob
    return odd, no_vig_pair_prob(odd, odd_oposta)[0]


def reavaliar_pick(pick: dict, odd_agora: float | None, novos_por_lado: dict,
                   producao_por_lado: dict, config=DEFAULT_CONFIG,
                   prob_justa: float | None = None) -> dict:
    """A conta, sem banco. `pick` = {prob, odd, ev, market_type, scope, amostra}.
    `novos_por_lado` = {lado: [ids]}; `producao_por_lado` = {lado: producao_perdida}.

    `prob_justa` (sem margem) e' o alvo do encolhimento, como no motor. Com
    1/odd no lugar (fallback), o EV reavaliado nunca fica negativo -- o alvo ja'
    embute a margem da casa -- e o alerta quase nunca dispararia."""
    p = float(pick["prob"])
    saida = {"prob_publicada": p, "odd_publicada": pick.get("odd"),
             "ev_publicado": pick.get("ev"), "odd_agora": odd_agora,
             "novos_ausentes": {l: sorted(v) for l, v in novos_por_lado.items() if v}}
    if odd_agora is None:
        saida["alerta"] = "linha sem cotacao no fechamento"
        return saida
    saida["ev_agora"] = round(p * odd_agora - 1, 4)
    p_reav = p
    lados = (("home",) if pick.get("scope") == "home" else ("away",)
             if pick.get("scope") == "away" else ("home", "away"))
    desf = contexto_atual.fracao_perdida(
        [producao_por_lado.get(l) for l in lados], pick.get("market_type") or "")
    if desf and desf["fracao"] > 0 and pick.get("amostra"):
        n = float(pick["amostra"])
        n_eff = n * (1 - desf["fracao"])
        k = contexto_atual._K_PRIOR
        w = (n_eff / (n_eff + k)) / (n / (n + k)) if n_eff > 0 else 0.0
        prior = prob_justa if prob_justa is not None else 1 / odd_agora
        p_reav = round(prior + (p - prior) * min(1.0, w), 4)
        saida["fracao_perdida"] = desf["fracao"]
        saida["detalhe"] = {"desfalques": desf, "amostra": n, "amostra_efetiva": round(n_eff, 2),
                            "alvo": "sem margem" if prob_justa is not None else "1/odd"}
    saida["prob_reavaliada"] = p_reav
    saida["ev_reavaliado"] = round(p_reav * odd_agora - 1, 4)
    if saida["ev_reavaliado"] <= config.min_ev:
        saida["alerta"] = ("EV deixou de ser positivo"
                           + (" com os desfalques novos" if p_reav < p else " com a odd de agora"))
    return saida


def reavaliar_fixture(cur, fixture_id: int) -> list:
    """Reavalia e grava os picks pendentes de VIP e Free do jogo."""
    if not habilitada():
        return []
    for sql in DDL:
        cur.execute(sql)
    cur.execute("SELECT home_team_id, away_team_id, match_datetime FROM fixtures "
                "WHERE fixture_id = %s", (fixture_id,))
    fx = cur.fetchone()
    if not fx:
        return []
    casa, fora, quando = fx
    picks = []
    # A Free grava a probabilidade em `prob_real` e nao tem coluna de EV.
    colunas = {"picks_vip": "probability, ev",
               "picks_free": "prob_real, prob_real * odd - 1"}
    for tabela, cols in colunas.items():
        try:
            cur.execute(f"""
                SELECT id, market_type, market_id, line, odd, {cols}, engine_debug
                  FROM {tabela}
                 WHERE fixture_id = %s AND result IS NULL
            """, (fixture_id,))
            picks += [(tabela, *r) for r in cur.fetchall()]
        except Exception:
            cur.connection.rollback()
    if not picks:
        return []

    agora_fora, falha = _injuries_da_partida(fixture_id)
    xi_oficial = _tem_xi_oficial(cur, fixture_id)
    resultados = []
    producao_cache: dict = {}
    for tabela, pid, mt, market_id, linha, odd, prob, ev, debug in picks:
        if isinstance(debug, str):
            try:
                debug = json.loads(debug)
            except ValueError:
                debug = {}
        debug = debug or {}
        partida = ((debug.get("contexto_atual") or {}).get("partida") or {})
        antes = partida.get("desfalques_ids") or {}
        novos = {}
        for lado, team_id in (("home", casa), ("away", fora)):
            ja = set(antes.get(lado) or [])
            atual = set((agora_fora or {}).get(team_id) or ())
            novos[lado] = (atual - ja) | (_fora_do_xi(cur, fixture_id, team_id, quando) - ja)
        producao = {}
        for lado, team_id in (("home", casa), ("away", fora)):
            if not novos[lado]:
                continue
            chave = (team_id, frozenset(novos[lado]))
            if chave not in producao_cache:
                try:
                    producao_cache[chave] = contexto_atual.producao_perdida(
                        contexto_atual._linhas_de_producao(cur, team_id, quando), novos[lado])
                except Exception:
                    cur.connection.rollback()
                    producao_cache[chave] = None
            producao[lado] = producao_cache[chave]
        odd_agora, justa = _odd_de_agora(cur, fixture_id, market_id, linha)
        r = reavaliar_pick(
            {"prob": prob, "odd": float(odd) if odd else None,
             "ev": float(ev) if ev is not None else None, "market_type": mt,
             "scope": debug.get("scope"), "amostra": debug.get("amostra")},
            odd_agora, novos, producao, prob_justa=justa)
        if falha:
            r.setdefault("detalhe", {})["falha_injuries"] = falha
        # Se a escalacao oficial ja' estava na conta. Sem ela, o fechamento
        # reavalia de novo quando ela sair (esperando_escalacao).
        r.setdefault("detalhe", {})["xi_oficial"] = xi_oficial
        cur.execute("""
            INSERT INTO reavaliacao_picks (pick_table, pick_id, fixture_id, odd_publicada,
                odd_agora, prob_publicada, prob_reavaliada, ev_publicado, ev_agora,
                ev_reavaliado, novos_ausentes, fracao_perdida, alerta, detalhe)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb)
        """, (tabela, pid, fixture_id, r.get("odd_publicada"), r.get("odd_agora"),
              r.get("prob_publicada"), r.get("prob_reavaliada"), r.get("ev_publicado"),
              r.get("ev_agora"), r.get("ev_reavaliado"),
              json.dumps(r.get("novos_ausentes") or {}), r.get("fracao_perdida"),
              r.get("alerta"), json.dumps(r.get("detalhe") or {}, default=str)))
        if r.get("alerta"):
            print(f"[REAVALIACAO] {tabela} #{pid} (fixture {fixture_id}): {r['alerta']} "
                  f"-- odd {r.get('odd_publicada')} -> {r.get('odd_agora')}, "
                  f"EV reavaliado {r.get('ev_reavaliado')}")
        resultados.append({"pick_table": tabela, "pick_id": pid, **r})
    cur.connection.commit()
    return resultados
