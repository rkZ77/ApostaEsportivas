"""Resumo de IA no Raio-X de cada jogo (12/10/2026, pedido do usuario).

O Raio-X mostra os numeros; o resumo diz em poucas linhas o que eles apontam:
quais mercados de over/under os dois times sustentam, como chegam na tabela,
quem esta' no banco e se o jogo e' de liga ou de mata-mata.

CUSTO, QUE E' A CONDICAO DO PEDIDO ("nada muito gastar com IA"):
  - Gerado na PRIMEIRA abertura do jogo no dia e guardado em
    `raio_x_resumo_ia` (uma linha por jogo por dia). Quem abre depois le' o
    banco. Prod e noprod usam o mesmo banco, entao tambem dividem o resumo.
  - Modelo barato (Haiku 5.5), esforco baixo, saida curta e em JSON.
  - So' os dados que o site ja' tem · nenhuma chamada a API-Football.
  - So' jogo com amostra: mandante com 3+ jogos em casa e visitante com 3+
    fora na temporada (na liga, quando e' liga; em qualquer competicao,
    quando e' copa · mata-mata nao junta 3 jogos dentro da propria copa).
  - Teto por dia (RESUMO_IA_MAX_DIA) e desligamento por RESUMO_IA=off.

Falhou ou nao tem amostra: a linha fica gravada com o motivo, e o Raio-X
segue sem o bloco · nada aqui pode derrubar a tela.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

BRT = timezone(timedelta(hours=-3))

MODELO = os.getenv("RESUMO_IA_MODEL", "claude-haiku-5-5")
#: Jogos minimos do mandante em casa e do visitante fora na temporada.
MIN_JOGOS = 3
#: Falha da API nao trava o jogo o dia inteiro: depois disto tenta de novo.
_REPETIR_FALHA_MIN = 30
_ENCERRADO = ("FT", "AET", "PEN", "CANC", "ABD", "PST", "AWD", "WO")

_locks: dict[int, threading.Lock] = {}
_locks_guarda = threading.Lock()
_client = None


def ligado() -> bool:
    return os.getenv("RESUMO_IA", "on").strip().lower() != "off" \
        and bool(os.getenv("ANTHROPIC_API_KEY"))


def max_por_dia() -> int:
    try:
        return int(os.getenv("RESUMO_IA_MAX_DIA", "300"))
    except ValueError:
        return 300


def _hoje():
    return datetime.now(BRT).date()


def _lock(fixture_id: int) -> threading.Lock:
    with _locks_guarda:
        return _locks.setdefault(fixture_id, threading.Lock())


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    return _client


# ─────────────────────────────────────────────────────────────────────────────
# Formato da partida
# ─────────────────────────────────────────────────────────────────────────────
_MATA_MATA = ("round of", "quarter", "semi", "final", "play-off", "playoff",
              "third place", "preliminary", "qualifying")


def formato_da_partida(round_txt: str | None, tem_tabela: bool) -> str:
    """'liga' | 'grupos' | 'mata-mata ida e volta' | 'mata-mata' | 'copa'.

    Mesma leitura do texto do round que o motor faz em
    competition_profile.classify_round_phase ("leg" antes de "final": a final
    de ida e volta nao e' jogo unico). Sem round e sem tabela, 'copa': nao da'
    pra afirmar o formato, e o resumo nao pode inventar.
    """
    r = (round_txt or "").strip().lower()
    if "leg" in r:
        return "mata-mata ida e volta"
    if "group" in r:
        return "grupos"
    if any(k in r for k in _MATA_MATA):
        return "mata-mata"
    if "regular season" in r or tem_tabela:
        return "liga"
    return "copa"


# ─────────────────────────────────────────────────────────────────────────────
# Fatos: o que vai para o modelo
# ─────────────────────────────────────────────────────────────────────────────
def _pct(jogos: list, cond) -> int | None:
    validos = [j for j in jogos if cond(j) is not None]
    if not validos:
        return None
    return round(100 * sum(1 for j in validos if cond(j)) / len(validos))


def _media(valores: list) -> float | None:
    v = []
    for x in valores:
        try:
            v.append(float(str(x).rstrip("%")) if x is not None else None)
        except ValueError:
            v.append(None)
    v = [x for x in v if x is not None]
    return round(sum(v) / len(v), 2) if v else None


def _soma(j: dict, a: str, b: str):
    if j.get(a) is None or j.get(b) is None:
        return None
    return j[a] + j[b]


def _acima(j, a, b, linha):
    s = _soma(j, a, b)
    return None if s is None else s > linha


def _valor(j: dict, contador: str, quem: str, periodo: str = "total"):
    """O numero de um jogo · a mesma conta de lib/raioX.numero na tela.

    quem: 'pro' | 'contra' | 'jogo' (soma dos dois). periodo: 'total' | '1t' |
    '2t' (2o tempo = total - 1o, so' com os dois)."""
    def lado(q):
        total = j.get(f"{contador}_{q}")
        if periodo == "total":
            return total
        prim = j.get(f"{contador}_{q}_1t")
        if periodo == "1t":
            return prim
        return None if total is None or prim is None else total - prim
    if quem != "jogo":
        return lado(quem)
    a, b = lado("pro"), lado("contra")
    return None if a is None or b is None else a + b


def _mercado(jogos: list, contador: str, quem: str, linhas: tuple, periodo: str = "total",
             corte: tuple | None = (35, 65)) -> dict | None:
    """Media e "% de jogos acima de cada linha" de um mercado do Raio-X.

    `jogos` = quantos tem o numero (jogo antigo sem a folha do 1o tempo, ou
    sem faltas, nao conta nem a favor nem contra · igual a tela).
    `corte` (baixo, alto): so' vao as linhas fora da faixa; None = todas."""
    valores = [_valor(j, contador, quem, periodo) for j in jogos]
    validos = [v for v in valores if v is not None]
    if not validos:
        return None
    pcts = {str(l): round(100 * sum(1 for v in validos if v > l) / len(validos)) for l in linhas}
    return {
        "media": round(sum(validos) / len(validos), 1),
        "jogos": len(validos),
        # CUSTO (19/10/2026): linha entre 36 e 64 nao vira mercado (regra do
        # SYSTEM), entao nao vai · corta ~metade da entrada. A media fica.
        "pct_mais_de": pcts if corte is None else {k: v for k, v in pcts.items()
                                                    if v <= corte[0] or v >= corte[1]},
    }


#: TODOS OS MERCADOS DA ABA MERCADOS (19/10/2026, pedido do usuario: "a
#: leitura tem que ler todos os mercados do Raio-X e dos jogadores"). Antes a
#: IA so' via gols, escanteios e amarelos. (nome, contador, quem, periodo,
#: linhas) · as linhas cobrem as que a tela abre e as vizinhas que a casa
#: oferece. Faltas, chutes, impedimentos e defesas so' tem o jogo todo.
_MERCADOS_DO_TIME = (
    ("gols_feitos", "gols", "pro", "total", (0.5, 1.5, 2.5)),
    ("gols_sofridos", "gols", "contra", "total", (0.5, 1.5, 2.5)),
    ("gols_feitos_1t", "gols", "pro", "1t", (0.5, 1.5)),
    ("gols_feitos_2t", "gols", "pro", "2t", (0.5, 1.5)),
    ("gols_sofridos_1t", "gols", "contra", "1t", (0.5,)),
    ("gols_sofridos_2t", "gols", "contra", "2t", (0.5,)),
    ("escanteios_a_favor", "escanteios", "pro", "total", (2.5, 3.5, 4.5, 5.5, 6.5)),
    ("escanteios_cedidos", "escanteios", "contra", "total", (2.5, 3.5, 4.5, 5.5, 6.5)),
    ("escanteios_a_favor_1t", "escanteios", "pro", "1t", (1.5, 2.5, 3.5)),
    ("escanteios_a_favor_2t", "escanteios", "pro", "2t", (1.5, 2.5, 3.5)),
    ("cartoes_amarelos_recebidos", "amarelos", "pro", "total", (0.5, 1.5, 2.5, 3.5)),
    ("cartoes_amarelos_recebidos_1t", "amarelos", "pro", "1t", (0.5, 1.5)),
    ("chutes_no_alvo_a_favor", "chutes_alvo", "pro", "total", (2.5, 3.5, 4.5, 5.5)),
    ("chutes_no_alvo_cedidos", "chutes_alvo", "contra", "total", (2.5, 3.5, 4.5, 5.5)),
    ("chutes_no_alvo_a_favor_1t", "chutes_alvo", "pro", "1t", (0.5, 1.5, 2.5)),
    ("chutes_a_favor", "chutes", "pro", "total", (8.5, 10.5, 12.5, 14.5)),
    ("chutes_cedidos", "chutes", "contra", "total", (8.5, 10.5, 12.5, 14.5)),
    ("faltas_cometidas", "faltas", "pro", "total", (9.5, 10.5, 11.5, 12.5, 13.5)),
    ("faltas_sofridas", "faltas", "contra", "total", (9.5, 10.5, 11.5, 12.5, 13.5)),
    ("impedimentos", "impedimentos", "pro", "total", (0.5, 1.5, 2.5)),
    ("defesas_do_goleiro", "defesas", "pro", "total", (1.5, 2.5, 3.5, 4.5)),
)
_MERCADOS_DO_JOGO = (
    ("gols", "gols", "jogo", "total", (0.5, 1.5, 2.5, 3.5, 4.5)),
    ("gols_1t", "gols", "jogo", "1t", (0.5, 1.5, 2.5)),
    ("gols_2t", "gols", "jogo", "2t", (0.5, 1.5, 2.5)),
    ("escanteios", "escanteios", "jogo", "total", (7.5, 8.5, 9.5, 10.5, 11.5)),
    ("escanteios_1t", "escanteios", "jogo", "1t", (3.5, 4.5, 5.5)),
    ("escanteios_2t", "escanteios", "jogo", "2t", (4.5, 5.5, 6.5)),
    ("cartoes_amarelos", "amarelos", "jogo", "total", (2.5, 3.5, 4.5, 5.5)),
    ("cartoes_amarelos_1t", "amarelos", "jogo", "1t", (0.5, 1.5, 2.5)),
    ("chutes_no_alvo", "chutes_alvo", "jogo", "total", (6.5, 7.5, 8.5, 9.5, 10.5)),
    ("chutes_no_alvo_1t", "chutes_alvo", "jogo", "1t", (2.5, 3.5, 4.5)),
    ("chutes", "chutes", "jogo", "total", (18.5, 20.5, 22.5, 24.5, 26.5)),
    ("faltas", "faltas", "jogo", "total", (18.5, 20.5, 22.5, 24.5, 26.5)),
    ("impedimentos", "impedimentos", "jogo", "total", (1.5, 2.5, 3.5, 4.5)),
    ("defesas_dos_goleiros", "defesas", "jogo", "total", (4.5, 5.5, 6.5, 7.5)),
)


def numeros_do_time(jogos: list) -> dict | None:
    """Taxas sobre a serie jogo a jogo, do ponto de vista do time.

    Dois blocos (12/10/2026, pedido do usuario: "mostrando por time,
    respeitando mandante"): as linhas do JOGO (total dos dois) e as do proprio
    TIME (o que ele faz e o que cede), que e' o que diz se ele domina, ataca
    ou se defende. Desde 19/10/2026, todos os mercados da aba Mercados.
    """
    if not jogos:
        return None
    # Forma = os 5 mais recentes: com a temporada inteira na serie, a faixa
    # da tela viraria 19 letras.
    forma = "".join(
        "V" if j["gols_pro"] > j["gols_contra"] else "E" if j["gols_pro"] == j["gols_contra"] else "D"
        for j in jogos if j.get("gols_pro") is not None and j.get("gols_contra") is not None)[:5]
    gp, gc = "gols_pro", "gols_contra"
    ap, ac = "amarelos_pro", "amarelos_contra"

    def resultado(j):
        if j.get(gp) is None or j.get(gc) is None:
            return None
        return "V" if j[gp] > j[gc] else "E" if j[gp] == j[gc] else "D"

    def cartoes(j, q):
        if j.get(f"amarelos_{q}") is None:
            return None
        return j[f"amarelos_{q}"] + (j.get(f"vermelhos_{q}") or 0)

    return {
        "jogos": len(jogos),
        "forma_recente_primeiro": forma,
        "resultado": {
            "pct_vitoria": _pct(jogos, lambda j: None if resultado(j) is None else resultado(j) == "V"),
            "pct_empate": _pct(jogos, lambda j: None if resultado(j) is None else resultado(j) == "E"),
            "pct_derrota": _pct(jogos, lambda j: None if resultado(j) is None else resultado(j) == "D"),
        },
        "posse_media": _media([j.get("posse") for j in jogos]),
        # Sempre, mesmo entre 36 e 64: e' a faixa de numeros da tela.
        "pct_marcou": _pct(jogos, lambda j: None if j.get(gp) is None else j[gp] > 0),
        "pct_sofreu": _pct(jogos, lambda j: None if j.get(gc) is None else j[gc] > 0),
        "time": {nome: _mercado(jogos, c, q, linhas, p) for nome, c, q, p, linhas in _MERCADOS_DO_TIME},
        "jogo": {
            **{nome: _mercado(jogos, c, q, linhas, p) for nome, c, q, p, linhas in _MERCADOS_DO_JOGO},
            "pct_ambas_marcam": _pct(jogos, lambda j: None if j.get(gp) is None or j.get(gc) is None
                                     else j[gp] > 0 and j[gc] > 0),
            "pct_ambos_recebem_cartao": _pct(
                jogos, lambda j: None if cartoes(j, "pro") is None or cartoes(j, "contra") is None
                else min(cartoes(j, "pro"), cartoes(j, "contra")) >= 1),
            "pct_teve_vermelho": _pct(
                jogos, lambda j: None if j.get(ap) is None or j.get(ac) is None
                else (j.get("vermelhos_pro") or 0) + (j.get("vermelhos_contra") or 0) > 0),
        },
    }


#: Linhas de jogador ("X ou mais" no jogo dele), as mesmas da aba Jogadores.
_LINHAS_DO_JOGADOR = (
    ("chutes", (1, 2, 3)), ("chutes_alvo", (1, 2)), ("gols", (1,)), ("assistencias", (1,)),
    ("faltas", (1, 2)), ("faltas_sofridas", (1, 2, 3)), ("desarmes", (1, 2, 3)),
    ("amarelos", (1,)), ("dribles", (1, 2)),
)
_LINHAS_DO_GOLEIRO = (("defesas", (2, 3, 4, 5)),)
#: Jogos minimos do jogador no recorte pra entrar na leitura.
MIN_JOGOS_JOGADOR = 4
#: Jogadores por time que vao pro modelo (titulares provaveis primeiro).
MAX_JOGADORES = 11


def numeros_dos_jogadores(lista: list, jogos_do_mando: set) -> list:
    """Os jogadores de um time pra IA (19/10/2026, pedido do usuario).

    Mesma conta da aba Jogadores com "Casa / Fora": so' os jogos do time NO
    MANDO DESTA PARTIDA. Jogador com menos de MIN_JOGOS_JOGADOR nesse recorte
    fica fora. So' vao as linhas em que bateu em 65% ou mais dos jogos (prop
    de jogador e' sempre "X ou mais") · o resto e' token pago a toa.
    """
    saida = []
    for p in lista:
        jogos = [g for g in p.get("jogos") or [] if g.get("fixture_id") in jogos_do_mando]
        if len(jogos) < MIN_JOGOS_JOGADOR:
            continue
        goleiro = (p.get("posicao") or "").upper().startswith("G")
        mercados = {}
        for estat, minimos in (_LINHAS_DO_GOLEIRO if goleiro else _LINHAS_DO_JOGADOR):
            valores = [g.get(estat) for g in jogos if g.get(estat) is not None]
            if not valores:
                continue
            pcts = {f"{m}+": round(100 * sum(1 for v in valores if v >= m) / len(valores))
                    for m in minimos}
            pcts = {k: v for k, v in pcts.items() if v >= 65}
            if pcts:
                mercados[estat] = {"media": round(sum(valores) / len(valores), 1),
                                   "pct_jogos_com": pcts}
        if not mercados:
            continue
        saida.append({
            "nome": p.get("nome"), "posicao": p.get("posicao"),
            "titular_provavel": bool(p.get("titular_provavel")),
            "jogos": len(jogos),
            "minutos_media": round(sum(g.get("minutos") or 0 for g in jogos) / len(jogos)),
            "mercados": mercados,
        })
        if len(saida) >= MAX_JOGADORES:
            break
    return saida


def numeros_curtos(jogos: list) -> dict | None:
    """So' as medias, sem as linhas (19/10/2026): "ultimos 5" e "geral" so'
    contrastam o mando. Com todos os mercados completos nos tres blocos, a
    entrada triplicava · e e' paga em todo jogo aberto no dia."""
    n = numeros_do_time(jogos)
    if not n:
        return None
    return {
        "jogos": n["jogos"], "forma_recente_primeiro": n["forma_recente_primeiro"],
        "resultado": n["resultado"], "posse_media": n["posse_media"],
        "medias_do_time": {k: v["media"] for k, v in n["time"].items() if v},
        "medias_do_jogo": {k: v["media"] for k, v in n["jogo"].items() if isinstance(v, dict)},
    }


#: Linhas de time da liga (dois por partida) minimas pra media valer: 10 jogos.
MIN_LIGA = 20


def media_da_liga(liga_jogos: list) -> dict | None:
    """A regua da liga (19/10/2026, pedido do usuario): so' as medias por
    jogo, pra IA dizer "o Goias faz 13 faltas; a liga, 11". Sai da mesma
    lista que o Raio-X usa na chance ajustada (fixtures._jogos_da_liga), sem
    consulta nova. Um time medio da liga = "time"; a partida = "jogo"."""
    if len(liga_jogos) < MIN_LIGA:
        return None
    n = numeros_curtos(liga_jogos)
    return {"jogos": len(liga_jogos) // 2,
            "media_de_um_time": n["medias_do_time"], "media_do_jogo": n["medias_do_jogo"]}


def serie_por_mando(cur, team_id: int, em_casa: bool, season, league_id,
                    so_na_liga: bool, antes_de, n: int = 60) -> list[dict]:
    """Os jogos do time SO' NO MANDO DESTA PARTIDA, na temporada INTEIRA
    (60 cobre qualquer liga · 17/10/2026, pedido do usuario):
    o mandante em casa, o visitante fora. A serie geral do Raio-X tem 10 jogos
    misturando os dois, e a leitura saia com "4 jogos em casa" achando que
    eram 10. Sai de routers/fixtures._serie_do_time, com as MESMAS colunas
    da tela (19/10/2026): faltas, chutes, impedimentos, defesas, vermelhos e
    o 1o tempo de escanteios, cartoes e chutes no alvo entraram."""
    from routers.fixtures import _COLUNAS_DO_JOGO, _serie_do_time
    lado = "home" if em_casa else "away"
    cur.execute(f"""
        SELECT {_COLUNAS_DO_JOGO}
          FROM match_statistics
         WHERE {lado}_team_id = %s AND season = %s
           AND status IN ('FT','AET','PEN')
           AND (NOT %s OR league_id = %s)
           AND (%s::timestamp IS NULL OR match_date < %s::timestamp)
         ORDER BY match_date DESC LIMIT %s
    """, (team_id, season, so_na_liga, league_id, antes_de, antes_de, n))
    return _serie_do_time([{**r, "team_id": team_id} for r in cur.fetchall()], team_id)

def _sem_vazios(d):
    if isinstance(d, dict):
        return {k: _sem_vazios(v) for k, v in d.items() if v not in (None, "", [], {})}
    if isinstance(d, list):
        return [_sem_vazios(x) for x in d]
    return d


def fato_do_arbitro(arb: dict | None) -> dict | None:
    """O arbitro pra IA (18/10/2026): temporada inteira em todas as
    competicoes (todas as grafias), contra a media da liga, e o cartao do
    confronto direto. Sai de arbitro_do_jogo, a mesma conta da tela."""
    if not arb or arb.get("status") != "ok":
        return None
    r = (arb.get("temporada_toda") or {}).get("resumo") or {}
    ctx = arb.get("contexto") or {}

    def m(k):
        return (r.get(k) or {}).get("media")
    conf = ctx.get("confronto")
    return _sem_vazios({
        "nome": arb.get("nome"),
        "jogos_na_temporada": r.get("jogos"),
        "pontos_de_cartao_por_jogo": m("pontos_de_cartao"),
        "pontos_de_cartao_da_liga": ctx.get("pontos_de_cartao_da_liga"),
        "amarelos_por_jogo": m("amarelos"),
        "vermelhos_por_jogo": m("vermelhos"),
        "faltas_por_jogo": m("faltas"),
        "faltas_da_liga": ctx.get("faltas_da_liga"),
        "pct_jogos_mais_de_4_5_amarelos": r.get("pct_mais_de_4_5_amarelos"),
        "penaltis_por_jogo": m("penaltis"),
        "perfil": ctx.get("perfil"),
        "perfil_de_faltas": ctx.get("perfil_de_faltas"),
        "confronto_direto_cartoes": {
            "confrontos": conf["confrontos"], "pontos_por_confronto": conf["media_h2h"],
            "esperado_pelos_times": conf["baseline"], "leitura": conf["label"],
        } if conf else None,
        "temperatura": ctx.get("temperatura"),
    })


def _arbitro_seguro(cur, fixture_id: int) -> dict | None:
    """fato_do_arbitro sem nunca derrubar a leitura: sem ele, a IA fica com o
    bloco antigo (nome, jogos e amarelos)."""
    try:
        import arbitro_do_jogo
        return fato_do_arbitro(arbitro_do_jogo.arbitro_do_jogo(cur, fixture_id))
    except Exception:
        cur.connection.rollback()
        logger.warning("[RESUMO IA] arbitro indisponivel no jogo %s", fixture_id, exc_info=True)
        return None


def montar_fatos(dados: dict, liga: str | None, formato: str, tabela: dict,
                 tecnicos: dict, amostra: dict,
                 casa_em_casa: list | None = None, fora_fora: list | None = None,
                 arbitro: dict | None = None) -> dict:
    """Tudo que o modelo pode usar, ja' contado · ele interpreta, nao calcula.

    `casa_em_casa`/`fora_fora`: a serie do mando desta partida na temporada
    (serie_por_mando). Sem ela, o recorte de mando sai da serie geral.

    TEMPORADA INTEIRA (17/10/2026, pedido do usuario): o modelo ve' todos os
    jogos da temporada, mas a leitura e' pelo mando · o geral so' contrasta, e
    os 5 ultimos no mando dizem se o time mudou de fase.
    """
    f = dados["fixture"]
    times = dados["times"]
    casa = times["home"]["jogos"]
    fora = times["away"]["jogos"]
    if casa_em_casa is None:
        casa_em_casa = [j for j in casa if j["em_casa"]]
    if fora_fora is None:
        fora_fora = [j for j in fora if not j["em_casa"]]
    hid, aid = f["home_team_id"], f["away_team_id"]
    h2h = [{
        "data": (j.get("data") or "")[:10],
        "placar": f'{j["home_goals"]}x{j["away_goals"]}',
        "mandante": f["home_team"] if j["home_team_id"] == hid else f["away_team"],
        "escanteios": j.get("escanteios"),
    } for j in (dados.get("h2h") or [])[:6] if j.get("home_goals") is not None]
    arb = dados.get("arbitro") or {}
    arb_jogos = arb.get("jogos") or []
    # Placar da ida, quando este e' o jogo de volta · e' o que decide como os
    # dois vao jogar (14/10/2026).
    competicao = dados.get("competicao") or {}
    ida = competicao.get("ida")
    # Qual perna e' esta (14/10/2026): sem isso, no jogo de IDA o modelo
    # escrevia "nao da' pra saber se e' ida ou volta".
    perna = {"ida": "jogo de IDA: a vaga se decide na volta, os dois jogam sem precisar de um resultado especifico",
             "volta": "jogo de VOLTA: o placar da ida (jogo_de_ida) define quem precisa do resultado"
             }.get(competicao.get("perna"))
    jogo_de_ida = ({
        "placar": f'{f["home_team"]} {ida["gols_mandante"]} x {ida["gols_visitante"]} {f["away_team"]}',
        "quem_esta_na_frente": (f["home_team"] if ida["gols_mandante"] > ida["gols_visitante"]
                                else f["away_team"] if ida["gols_visitante"] > ida["gols_mandante"]
                                else "empate"),
    } if ida else None)
    # Jogadores no mando desta partida, como a aba Jogadores com "Casa / Fora".
    jog = dados.get("jogadores") or {}
    mando_casa = {j.get("fixture_id") for j in casa if j.get("em_casa")}
    mando_fora = {j.get("fixture_id") for j in fora if not j.get("em_casa")}
    return _sem_vazios({
        "jogo": {
            "mandante": f["home_team"], "visitante": f["away_team"],
            "competicao": liga, "rodada": f.get("round"), "formato": formato,
            "data": (f.get("match_datetime") or "")[:16],
            "perna": perna,
            "jogo_de_ida": jogo_de_ida,
        },
        "amostra_na_temporada": amostra,
        "mandante": {
            "nome": f["home_team"],
            "EM_CASA_na_temporada": numeros_do_time(casa_em_casa),
            "ultimos_5_em_casa": numeros_curtos(casa_em_casa[:5]),
            "temporada_geral": numeros_curtos(casa),
            "jogadores_em_casa": numeros_dos_jogadores(
                (jog.get("home") or {}).get("lista") or [], mando_casa),
            "tabela": tabela.get(hid),
            "tecnico": tecnicos.get(hid),
        },
        "visitante": {
            "nome": f["away_team"],
            "FORA_na_temporada": numeros_do_time(fora_fora),
            "ultimos_5_fora": numeros_curtos(fora_fora[:5]),
            "temporada_geral": numeros_curtos(fora),
            "jogadores_fora": numeros_dos_jogadores(
                (jog.get("away") or {}).get("lista") or [], mando_fora),
            "tabela": tabela.get(aid),
            "tecnico": tecnicos.get(aid),
        },
        "media_da_liga": media_da_liga(dados.get("liga_jogos") or []),
        "confronto_direto": h2h,
        "arbitro": arbitro or ({
            "nome": arb.get("nome"), "jogos": len(arb_jogos),
            "amarelos_media": _media([j["amarelos"] for j in arb_jogos]),
        } if arb_jogos else None),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Leituras do banco
# ─────────────────────────────────────────────────────────────────────────────
def amostra_da_temporada(cur, home_id, away_id, league_id, season, so_na_liga: bool) -> dict:
    """Jogos encerrados do mandante EM CASA e do visitante FORA na temporada."""
    cur.execute("""
        SELECT
          (SELECT COUNT(*) FROM match_statistics
            WHERE home_team_id = %(h)s AND season = %(s)s
              AND status IN ('FT','AET','PEN')
              AND (NOT %(liga)s OR league_id = %(l)s)) AS casa,
          (SELECT COUNT(*) FROM match_statistics
            WHERE away_team_id = %(a)s AND season = %(s)s
              AND status IN ('FT','AET','PEN')
              AND (NOT %(liga)s OR league_id = %(l)s)) AS fora
    """, {"h": home_id, "a": away_id, "s": season, "l": league_id, "liga": so_na_liga})
    r = cur.fetchone() or {}
    return {"mandante_em_casa": int(r.get("casa") or 0),
            "visitante_fora": int(r.get("fora") or 0),
            "contagem": "na liga" if so_na_liga else "todas as competicoes"}


def tabela_dos_times(cur, league_id, ids: list) -> dict:
    if not league_id:
        return {}
    try:
        cur.execute("""
            SELECT team_id, rank, points, played, goals_diff, form, description,
                   home_played, home_win, home_draw, home_lose,
                   away_played, away_win, away_draw, away_lose,
                   (SELECT COUNT(*) FROM league_standings x
                     WHERE x.league_id = s.league_id AND x.season = s.season
                       AND x.group_name IS NOT DISTINCT FROM s.group_name) AS times_no_grupo
              FROM league_standings s
             WHERE league_id = %s AND team_id = ANY(%s)
               AND season = (SELECT MAX(season) FROM league_standings WHERE league_id = %s)
        """, (league_id, ids, league_id))
        saida = {}
        for r in cur.fetchall():
            saida[r["team_id"]] = {
                "posicao": r["rank"], "de": r["times_no_grupo"], "pontos": r["points"],
                "jogos": r["played"], "saldo": r["goals_diff"], "forma": r["form"],
                "zona": r["description"],
                "em_casa_ved": f'{r["home_win"]}-{r["home_draw"]}-{r["home_lose"]}',
                "fora_ved": f'{r["away_win"]}-{r["away_draw"]}-{r["away_lose"]}',
            }
        return saida
    except Exception:
        cur.connection.rollback()
        logger.warning("[RESUMO IA] tabela indisponivel", exc_info=True)
        return {}


def tecnicos_dos_times(cur, ids: list) -> dict:
    """Quem dirigiu os ultimos jogos e ha' quantos jogos seguidos.

    `team_lineups` traz o tecnico de cada escalacao coletada · contar os
    jogos seguidos com o mesmo nome diz se e' tecnico novo (o "efeito do
    tecnico novo" e' contexto que o usuario pediu). Nenhuma chamada a API.
    """
    saida = {}
    try:
        cur.execute("""
            SELECT team_id, coach_name FROM (
                SELECT team_id, coach_name,
                       ROW_NUMBER() OVER (PARTITION BY team_id ORDER BY match_date DESC) AS n
                  FROM team_lineups
                 WHERE team_id = ANY(%s) AND coach_name IS NOT NULL
            ) t WHERE n <= 15
            ORDER BY team_id, n
        """, (ids,))
        por_time: dict = {}
        for r in cur.fetchall():
            por_time.setdefault(r["team_id"], []).append(r["coach_name"])
        for tid, nomes in por_time.items():
            seguidos = 0
            for nome in nomes:
                if nome != nomes[0]:
                    break
                seguidos += 1
            saida[tid] = {"nome": nomes[0],
                          "jogos_seguidos": f"{seguidos}+" if seguidos == len(nomes) else seguidos}
    except Exception:
        cur.connection.rollback()
        logger.warning("[RESUMO IA] tecnico indisponivel", exc_info=True)
    return saida


# ─────────────────────────────────────────────────────────────────────────────
# A chamada
# ─────────────────────────────────────────────────────────────────────────────
#: Formato da leitura. Sobe quando o formato muda: leitura guardada de versao
#: antiga e' gerada de novo na proxima abertura (ver _vale).
#: 4 (14/10/2026): entrou a perna do mata-mata (ida/volta) · a leitura do
#: jogo de ida dizia "nao da' pra saber se e' ida ou volta".
#: 5 (18/10/2026): o arbitro com a temporada inteira, contra a liga, e a
#: temperatura do confronto.
#: 6 (19/10/2026): todos os mercados da aba Mercados (faltas, chutes,
#: impedimentos, defesas, 1o e 2o tempo, resultado) e os jogadores.
#: 7 (19/10/2026): a media da liga como regua.
#: 8 (19/10/2026): o atalho de cada mercado pra aba Mercados.
VERSAO = 8

SYSTEM = """Você escreve a leitura de pré-jogo do Raio-X do PickIA, um site brasileiro de análise de apostas esportivas. Quem lê está no celular, decidindo se aposta, e quer saber em segundos como cada time joga e quais mercados os números sustentam.

Fonte:
- Use SOMENTE os números do JSON. Não invente lesão, escalação, notícia, odd, motivação ou história. Dado que não veio não existe.
- RESPEITE O MANDO. Do mandante, leia "EM_CASA_na_temporada"; do visitante, "FORA_na_temporada". Esses dois cobrem a temporada inteira no mando, trazem TODOS os mercados e são a base de toda leitura. "ultimos_5_em_casa"/"ultimos_5_fora" (só médias) dizem se o time mudou de fase no mando: cite quando divergirem da temporada. "temporada_geral" (casa e fora juntos, só médias) serve só para confirmar ou contrastar, e quando usar diga que é o geral. Diga a amostra do jeito certo ("em 14 jogos em casa").
- Cada mercado traz "media", "jogos" (quantos têm o número) e "pct_mais_de": {"4.5": 70} = passou de 4,5 em 70% dos jogos. Under da linha = 100 menos esse número. Só vêm as linhas com 65 ou mais ou 35 ou menos: linha que não veio ficou entre 36 e 64 e não serve. Todo "pct" é PERCENTUAL DE JOGOS, nunca de gols.
- "time" são os números do próprio time (o que ele faz e o que cede); "jogo" são totais das partidas dele (os dois times somados). Sufixo "_1t"/"_2t" = só aquele tempo.
- LEIA TODOS os mercados antes de escolher: gols, escanteios, cartões, chutes no alvo, chutes, faltas, impedimentos, defesas do goleiro, 1º e 2º tempo, resultado, ambas marcam, ambos recebem cartão. Escolha os mais fortes, não os de sempre.
- Jogadores ("jogadores_em_casa"/"jogadores_fora"): só os jogos do time neste mando. "pct_jogos_com": {"1+": 80} = fez 1 ou mais em 80% dos jogos que jogou. Prefira "titular_provavel": true.
- "media_da_liga" é a régua: "media_de_um_time" é o que um time médio da liga faz por jogo (compare com "time"), "media_do_jogo" é a partida média (compare com "jogo"). Use para dizer se o número do time é alto ou baixo ("faz 13 faltas por jogo em casa; a liga, 11"). Fora da liga (copa, mata-mata) a régua é da própria competição.
- Só chame a amostra de curta quando o mando tiver menos de 8 jogos.

O que escrever:
- "resumo": no máximo 2 frases sobre o confronto: quem chega melhor no mando e o que os números apontam.
- "times": um item para o mandante e um para o visitante, nessa ordem.
  - "perfil": dominante (posse alta, mais chutes e escanteios a favor que contra), ofensivo (marca muito, mas também sofre), equilibrado, defensivo (sofre pouco e marca pouco), reativo (pouca posse, cede escanteios e chutes, joga no contra-ataque). Escolha pelo mando desta partida.
  - "leitura": 1 ou 2 frases sobre como o time joga NESTE mando, com números.
  - "mercados": até 3 mercados DO PRÓPRIO TIME com pct de 65 ou mais ("over") ou 35 ou menos ("under"). Ex.: "Chapecoense sofre gol", "Athletico-PR mais de 4,5 escanteios", "Ceará mais de 11,5 faltas". Nada entre 36 e 64. Um mercado por família (não repita escanteios em duas linhas): no over, a linha mais alta que ainda passa de 65; no under, a mais baixa que fica em 35 ou menos. Se nenhum passar, lista vazia.
  - "jogadores": até 3 mercados de jogador DESTE time com 65 ou mais, tendencia "over". "mercado" com o nome e a linha ("Pedro 1+ chute no alvo"), "leitura" com a amostra ("em 9 de 12 jogos em casa"). Um por jogador. Se nenhum passar, lista vazia.
- "mercados_do_jogo": até 3 linhas do JOGO (qualquer mercado de "jogo", inclusive 1º e 2º tempo) em que o mandante em casa E o visitante fora apontam para o mesmo lado. Discordaram, não entra.
- "atalho" (em "mercados" e "mercados_do_jogo") diz a mesma linha em campos: "mercado" (gols, escanteios, cartoes = amarelos, chutes_alvo, faltas, chutes, impedimentos; "outro" para resultado, ambas marcam, ambos recebem cartão e defesas), "de_quem" ("jogo" = os dois somados; "mandante"/"visitante" = o que esse time faz. "Goiás sofre gol" é gol do adversário: de_quem do adversário, lado "mais", linha 0.5), "periodo", "lado" ("mais" no over, "menos" no under) e "linha" (ex.: 4.5).
- Em todo mercado, "pct" é o percentual que sustenta a tendência (para "under", o percentual de jogos em que NÃO aconteceu), e "tendencia" tem que bater com a "leitura".
- "contexto": tabela, técnico e formato. Em "liga" posição e mando pesam; em mata-mata o jogo é decidido no placar e os times se fecham (na ida e volta, a 2ª partida depende da 1ª: "perna" diz se este é o jogo de ida ou de volta; na volta, com "jogo_de_ida", diga quem precisa do resultado e como isso muda o jogo); em "grupos" e "copa" a amostra mistura competições. Técnico só se tiver 3 ou menos jogos seguidos.
- Árbitro ("arbitro"): pesa SÓ em cartões e faltas, nunca em gols ou escanteios. Compare com a liga ("apita 6,2 pontos de cartão por jogo; a liga, 4,9"; pontos de cartão = amarelo + 2 x vermelho). "perfil_de_faltas" (contra as faltas da liga) vale para mercado de faltas. "perfil" rigoroso ou leniente e "temperatura" (o árbitro junto com o histórico de cartões do confronto direto) entram em "contexto" e podem sustentar ou derrubar um mercado de cartões do jogo; "amostra_curta" não sustenta nada.
- "alerta": o que deixa a leitura fraca (amostra curta, números que se contradizem, mata-mata). Vazio se não houver.

Estilo: português do Brasil com acentuação correta. Decimais com vírgula ("1,4 gol por jogo"). Escreva "1º tempo", "2º tempo", "4º colocado". Use o nome de cada time exatamente como está em "nome", sempre igual. Direto, sem jargão estatístico, sem certeza nem promessa ("vai sair", "garantido"). Fale em tendência."""

_MERCADO = {
    "type": "object",
    "properties": {
        "mercado": {"type": "string"},
        "tendencia": {"type": "string", "enum": ["over", "under"]},
        "pct": {"type": "integer"},
        "leitura": {"type": "string"},
    },
    "required": ["mercado", "tendencia", "pct", "leitura"],
    "additionalProperties": False,
}

#: ATALHO PRA ABA MERCADOS (19/10/2026, pedido do usuario): tocar no mercado
#: da leitura abre o Raio-X naquela linha. Os ids sao os de
#: lib/raioX.MERCADOS_PRINCIPAIS; "outro" = sem quadro de linha (ambas marcam,
#: resultado, defesas) e a tela nao liga o toque.
_ATALHO = {
    "type": "object",
    "properties": {
        "mercado": {"type": "string", "enum": ["gols", "escanteios", "cartoes", "chutes_alvo",
                                               "faltas", "chutes", "impedimentos", "outro"]},
        "de_quem": {"type": "string", "enum": ["jogo", "mandante", "visitante"]},
        "periodo": {"type": "string", "enum": ["total", "1t", "2t"]},
        "lado": {"type": "string", "enum": ["mais", "menos"]},
        "linha": {"type": "number"},
    },
    "required": ["mercado", "de_quem", "periodo", "lado", "linha"],
    "additionalProperties": False,
}
_MERCADO_COM_ATALHO = {
    **_MERCADO,
    "properties": {**_MERCADO["properties"], "atalho": _ATALHO},
    "required": [*_MERCADO["required"], "atalho"],
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "resumo": {"type": "string"},
        "times": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "lado": {"type": "string", "enum": ["mandante", "visitante"]},
                    "perfil": {"type": "string",
                               "enum": ["dominante", "ofensivo", "equilibrado", "defensivo", "reativo"]},
                    "leitura": {"type": "string"},
                    "mercados": {"type": "array", "items": _MERCADO_COM_ATALHO},
                    "jogadores": {"type": "array", "items": _MERCADO},
                },
                "required": ["lado", "perfil", "leitura", "mercados", "jogadores"],
                "additionalProperties": False,
            },
        },
        "mercados_do_jogo": {"type": "array", "items": _MERCADO_COM_ATALHO},
        "contexto": {"type": "string"},
        "alerta": {"type": "string"},
    },
    "required": ["resumo", "times", "mercados_do_jogo", "contexto", "alerta"],
    "additionalProperties": False,
}


def numeros_da_tela(fatos: dict) -> dict:
    """A faixa de números de cada time na aba (12/10/2026): sai da MESMA conta
    que foi pro modelo, e nao do texto dele · numero na tela nunca e'
    escrito pela IA."""
    saida = {}
    for lado, chave in (("mandante", "EM_CASA_na_temporada"), ("visitante", "FORA_na_temporada")):
        n = (fatos.get(lado) or {}).get(chave) or {}
        t = n.get("time") or {}

        def m(nome):
            return (t.get(nome) or {}).get("media")
        saida[lado] = {
            "jogos": n.get("jogos"), "forma": n.get("forma_recente_primeiro"),
            "gols_pro": m("gols_feitos"), "gols_contra": m("gols_sofridos"),
            "pct_marcou": n.get("pct_marcou"), "pct_sofreu": n.get("pct_sofreu"),
            "escanteios_pro": m("escanteios_a_favor"),
        }
    return saida

#: US$ por milhao de tokens do Haiku 5.5 (entrada, saida). So' pra estimar o
#: custo no /admin · a fatura de verdade e' a do console da Anthropic.
PRECO_POR_MTOK = (0.10, 0.50)


def uso_por_dia(cur, dias: int = 14) -> list[dict]:
    """Leituras por dia no /admin (12/10/2026): quantas sairam, quantas o
    filtro barrou, falhas, tokens e o custo estimado."""
    cur.execute("""
        SELECT dia,
               COUNT(*) FILTER (WHERE status = 'ok')         AS geradas,
               COUNT(*) FILTER (WHERE status = 'inelegivel') AS sem_amostra,
               COUNT(*) FILTER (WHERE status = 'falhou')     AS falhas,
               COALESCE(SUM(tokens_in), 0)  AS tokens_in,
               COALESCE(SUM(tokens_out), 0) AS tokens_out
          FROM raio_x_resumo_ia
         WHERE dia > CURRENT_DATE - make_interval(days => %s)
         GROUP BY dia ORDER BY dia DESC
    """, (dias,))
    saida = []
    for r in cur.fetchall():
        t_in, t_out = int(r["tokens_in"]), int(r["tokens_out"])
        saida.append({
            "dia": r["dia"].isoformat(), "geradas": r["geradas"],
            "sem_amostra": r["sem_amostra"], "falhas": r["falhas"],
            "tokens_in": t_in, "tokens_out": t_out,
            "custo_usd": round((t_in * PRECO_POR_MTOK[0] + t_out * PRECO_POR_MTOK[1]) / 1e6, 4),
        })
    return saida


def chamar_modelo(fatos: dict) -> tuple[dict, int, int]:
    """(conteudo, tokens de entrada, tokens de saida). Levanta em falha."""
    resposta = _get_client().messages.create(
        model=MODELO,
        # 8000, e nao 3500 (14/10/2026): com os numeros do time e a forca de
        # cada mercado (12/10) a leitura passou do teto e voltava cortada
        # ("resposta incompleta: max_tokens" nos logs de PROD) · a tela
        # mostrava "nao deu para gerar". O teto so' limita; paga-se o que sai.
        max_tokens=8000,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        output_config={"effort": "low",
                       "format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user",
                   "content": json.dumps(fatos, ensure_ascii=False, separators=(",", ":"))}],
    )
    if resposta.stop_reason != "end_turn":
        raise RuntimeError(f"resposta incompleta: {resposta.stop_reason}")
    texto = next(b.text for b in resposta.content if b.type == "text")
    conteudo = json.loads(texto)
    conteudo["times"] = (conteudo.get("times") or [])[:2]
    for t in conteudo["times"]:
        t["mercados"] = (t.get("mercados") or [])[:3]
        t["jogadores"] = (t.get("jogadores") or [])[:3]
    conteudo["mercados_do_jogo"] = (conteudo.get("mercados_do_jogo") or [])[:3]
    u = resposta.usage
    return conteudo, int(u.input_tokens or 0), int(u.output_tokens or 0)


# ─────────────────────────────────────────────────────────────────────────────
# Fluxo
# ─────────────────────────────────────────────────────────────────────────────
def _guardado(cur, fixture_id: int, dia) -> dict | None:
    cur.execute("""
        SELECT status, conteudo, motivo, criado_em,
               criado_em < NOW() - make_interval(mins => %s) AS velho
          FROM raio_x_resumo_ia WHERE fixture_id = %s AND dia = %s
    """, (_REPETIR_FALHA_MIN, fixture_id, dia))
    return cur.fetchone()


def _gravar(cur, fixture_id, dia, status, conteudo=None, motivo=None,
            tokens_in=None, tokens_out=None) -> None:
    cur.execute("""
        INSERT INTO raio_x_resumo_ia
            (fixture_id, dia, status, conteudo, motivo, modelo, tokens_in, tokens_out)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (fixture_id, dia) DO UPDATE SET
            status = EXCLUDED.status, conteudo = EXCLUDED.conteudo,
            motivo = EXCLUDED.motivo, modelo = EXCLUDED.modelo,
            tokens_in = EXCLUDED.tokens_in, tokens_out = EXCLUDED.tokens_out,
            criado_em = NOW()
    """, (fixture_id, dia, status,
          json.dumps(conteudo, ensure_ascii=False) if conteudo is not None else None,
          motivo, MODELO if status == "ok" else None, tokens_in, tokens_out))
    cur.connection.commit()


def _vale(linha) -> bool:
    """A linha guardada ainda serve? Falha velha nao; leitura de formato
    antigo tambem nao (VERSAO) · ela e' gerada de novo, uma vez."""
    if not linha:
        return False
    if linha["status"] == "falhou":
        return not linha["velho"]
    if linha["status"] == "ok":
        c = linha["conteudo"]
        if isinstance(c, str):
            try:
                c = json.loads(c)
            except ValueError:
                return False
        return (c or {}).get("versao", 1) >= VERSAO
    return True


def _resposta(linha: dict) -> dict:
    if linha["status"] == "ok":
        conteudo = linha["conteudo"]
        if isinstance(conteudo, str):
            conteudo = json.loads(conteudo)
        return {"status": "ok", **(conteudo or {})}
    return {"status": linha["status"], "motivo": linha.get("motivo")}


def resumo_do_jogo(cur, fixture_id: int, montar_raio_x) -> dict:
    """O resumo do dia: do banco, ou gerado agora se for a primeira abertura.

    `montar_raio_x()` devolve os dados do Raio-X (routers/fixtures.py) · so'
    e' chamado quando vai gerar. Um lock por jogo no processo: dez pessoas
    abrindo o mesmo jogo ao mesmo tempo viram UMA chamada ao modelo.
    """
    dia = _hoje()
    linha = _guardado(cur, fixture_id, dia)
    if _vale(linha):
        return _resposta(linha)
    if not ligado():
        return {"status": "desligado"}

    with _lock(fixture_id):
        linha = _guardado(cur, fixture_id, dia)
        if _vale(linha):
            return _resposta(linha)

        cur.execute("SELECT league_id, season, round, status, home_team_id, away_team_id, match_datetime "
                    "FROM fixtures WHERE fixture_id = %s", (fixture_id,))
        fix = cur.fetchone()
        if not fix:
            return {"status": "inelegivel", "motivo": "jogo fora da agenda"}
        if fix.get("status") in _ENCERRADO:
            return {"status": "inelegivel", "motivo": "jogo encerrado"}

        tabela = tabela_dos_times(cur, fix["league_id"],
                                  [fix["home_team_id"], fix["away_team_id"]])
        formato = formato_da_partida(fix["round"], bool(tabela))
        amostra = amostra_da_temporada(cur, fix["home_team_id"], fix["away_team_id"],
                                       fix["league_id"], fix["season"],
                                       so_na_liga=(formato == "liga"))
        if amostra["mandante_em_casa"] < MIN_JOGOS or amostra["visitante_fora"] < MIN_JOGOS:
            motivo = (f"amostra curta: mandante com {amostra['mandante_em_casa']} jogo(s) em casa "
                      f"e visitante com {amostra['visitante_fora']} fora na temporada")
            _gravar(cur, fixture_id, dia, "inelegivel", motivo=motivo)
            return {"status": "inelegivel", "motivo": motivo}

        cur.execute("SELECT COUNT(*) AS n FROM raio_x_resumo_ia WHERE dia = %s AND status = 'ok'",
                    (dia,))
        if (cur.fetchone() or {}).get("n", 0) >= max_por_dia():
            # Nao grava: amanha (ou com teto maior) o jogo ainda pode ganhar.
            return {"status": "limite", "motivo": "limite de resumos do dia"}

        try:
            dados = montar_raio_x()
            # Jogo de VOLTA que o texto da rodada nao entrega (Libertadores:
            # "Semi-finals"): o Raio-X achou a ida no banco (14/10/2026).
            if ((dados.get("competicao") or {}).get("perna")
                    and formato.startswith("mata-mata")):
                formato = "mata-mata ida e volta"
            cur.execute("SELECT name FROM leagues WHERE league_id = %s LIMIT 1",
                        (fix["league_id"],))
            liga = (cur.fetchone() or {}).get("name")
            na_liga = formato == "liga"
            casa_em_casa = serie_por_mando(cur, fix["home_team_id"], True, fix["season"],
                                           fix["league_id"], na_liga, fix.get("match_datetime"))
            fora_fora = serie_por_mando(cur, fix["away_team_id"], False, fix["season"],
                                        fix["league_id"], na_liga, fix.get("match_datetime"))
            fatos = montar_fatos(dados, liga, formato, tabela,
                                 tecnicos_dos_times(cur, [fix["home_team_id"], fix["away_team_id"]]),
                                 amostra, casa_em_casa, fora_fora,
                                 arbitro=_arbitro_seguro(cur, fixture_id))
            conteudo, t_in, t_out = chamar_modelo(fatos)
        except Exception as e:
            cur.connection.rollback()
            logger.warning("[RESUMO IA] jogo %s falhou: %s", fixture_id, e)
            _gravar(cur, fixture_id, dia, "falhou", motivo=str(e)[:300])
            return {"status": "falhou"}
        conteudo["numeros"] = numeros_da_tela(fatos)
        conteudo["versao"] = VERSAO
        _gravar(cur, fixture_id, dia, "ok", conteudo=conteudo, tokens_in=t_in, tokens_out=t_out)
        logger.info("[RESUMO IA] jogo %s gerado (%s in / %s out)", fixture_id, t_in, t_out)
        return {"status": "ok", **conteudo}
