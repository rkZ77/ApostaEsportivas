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
    v = [x for x in valores if x is not None]
    return round(sum(v) / len(v), 2) if v else None


def _soma(j: dict, a: str, b: str):
    if j.get(a) is None or j.get(b) is None:
        return None
    return j[a] + j[b]


def _acima(j, a, b, linha):
    s = _soma(j, a, b)
    return None if s is None else s > linha


def numeros_do_time(jogos: list) -> dict | None:
    """Taxas das linhas que o Raio-X mostra, sobre a serie jogo a jogo."""
    if not jogos:
        return None
    forma = "".join(
        "V" if j["gols_pro"] > j["gols_contra"] else "E" if j["gols_pro"] == j["gols_contra"] else "D"
        for j in jogos if j.get("gols_pro") is not None and j.get("gols_contra") is not None)
    gp, gc = "gols_pro", "gols_contra"
    ep, ec = "escanteios_pro", "escanteios_contra"
    ap, ac = "amarelos_pro", "amarelos_contra"
    return {
        "jogos": len(jogos),
        "forma_recente_primeiro": forma,
        "gols_pro_media": _media([j.get(gp) for j in jogos]),
        "gols_contra_media": _media([j.get(gc) for j in jogos]),
        "pct_over_1_5_gols": _pct(jogos, lambda j: _acima(j, gp, gc, 1.5)),
        "pct_over_2_5_gols": _pct(jogos, lambda j: _acima(j, gp, gc, 2.5)),
        "pct_over_3_5_gols": _pct(jogos, lambda j: _acima(j, gp, gc, 3.5)),
        "pct_ambas_marcam": _pct(jogos, lambda j: None if j.get(gp) is None or j.get(gc) is None
                                 else j[gp] > 0 and j[gc] > 0),
        "pct_gol_no_1t": _pct(jogos, lambda j: _acima(j, "gols_pro_1t", "gols_contra_1t", 0.5)),
        "escanteios_total_media": _media([_soma(j, ep, ec) for j in jogos]),
        "escanteios_pro_media": _media([j.get(ep) for j in jogos]),
        "pct_over_8_5_escanteios": _pct(jogos, lambda j: _acima(j, ep, ec, 8.5)),
        "pct_over_9_5_escanteios": _pct(jogos, lambda j: _acima(j, ep, ec, 9.5)),
        "pct_over_10_5_escanteios": _pct(jogos, lambda j: _acima(j, ep, ec, 10.5)),
        "amarelos_total_media": _media([_soma(j, ap, ac) for j in jogos]),
        "pct_over_3_5_amarelos": _pct(jogos, lambda j: _acima(j, ap, ac, 3.5)),
        "pct_over_4_5_amarelos": _pct(jogos, lambda j: _acima(j, ap, ac, 4.5)),
        "chutes_no_alvo_pro_media": _media([j.get("chutes_alvo_pro") for j in jogos]),
    }


def _sem_vazios(d):
    if isinstance(d, dict):
        return {k: _sem_vazios(v) for k, v in d.items() if v not in (None, "", [], {})}
    if isinstance(d, list):
        return [_sem_vazios(x) for x in d]
    return d


def montar_fatos(dados: dict, liga: str | None, formato: str, tabela: dict,
                 tecnicos: dict, amostra: dict) -> dict:
    """Tudo que o modelo pode usar, ja' contado · ele interpreta, nao calcula."""
    f = dados["fixture"]
    times = dados["times"]
    casa = times["home"]["jogos"]
    fora = times["away"]["jogos"]
    hid, aid = f["home_team_id"], f["away_team_id"]
    h2h = [{
        "data": (j.get("data") or "")[:10],
        "placar": f'{j["home_goals"]}x{j["away_goals"]}',
        "mandante": f["home_team"] if j["home_team_id"] == hid else f["away_team"],
        "escanteios": j.get("escanteios"),
    } for j in (dados.get("h2h") or [])[:6] if j.get("home_goals") is not None]
    arb = dados.get("arbitro") or {}
    arb_jogos = arb.get("jogos") or []
    return _sem_vazios({
        "jogo": {
            "mandante": f["home_team"], "visitante": f["away_team"],
            "competicao": liga, "rodada": f.get("round"), "formato": formato,
            "data": (f.get("match_datetime") or "")[:16],
        },
        "amostra_na_temporada": amostra,
        "mandante": {
            "ultimos_jogos": numeros_do_time(casa),
            "jogando_em_casa": numeros_do_time([j for j in casa if j["em_casa"]]),
            "tabela": tabela.get(hid),
            "tecnico": tecnicos.get(hid),
        },
        "visitante": {
            "ultimos_jogos": numeros_do_time(fora),
            "jogando_fora": numeros_do_time([j for j in fora if not j["em_casa"]]),
            "tabela": tabela.get(aid),
            "tecnico": tecnicos.get(aid),
        },
        "confronto_direto": h2h,
        "arbitro": {
            "nome": arb.get("nome"), "jogos": len(arb_jogos),
            "amarelos_media": _media([j["amarelos"] for j in arb_jogos]),
        } if arb_jogos else None,
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
SYSTEM = """Voce escreve o resumo de pre-jogo do Raio-X do PickIA, um site brasileiro de analise de apostas esportivas. Quem le esta no celular, decidindo se aposta, e quer saber em segundos o que os numeros do jogo apontam.

Regras:
- Use SOMENTE os numeros do JSON recebido. Nao invente lesao, escalacao, noticia, odd, motivacao ou historia que nao esteja nele. Se um dado nao veio, nao fale dele.
- Escreva em portugues do Brasil, direto, sem jargao tecnico de estatistica. Percentuais como "7 de 10 jogos" ou "70%".
- Nada de certeza nem promessa ("vai sair", "garantido", "aposta certa"). Fale em tendencia.
- O formato importa: em "liga", posicao na tabela e mando pesam; em mata-mata, o jogo e decidido no placar (e na ida e volta, a 2a partida depende da 1a), entao times costumam se fechar; em "grupos" e "copa", diga que a amostra mistura competicoes quando for o caso.
- Tecnico com poucos jogos seguidos (3 ou menos) e contexto: diga que a amostra do trabalho dele e curta.
- Mercados: aponte ate 4 linhas de over/under (gols, escanteios, cartoes, gol no 1o tempo, ambas marcam) em que mandante em casa e visitante fora concordam. Se os dois discordam, diga que a linha fica dividida em vez de escolher um lado.
- "alerta" e para o que deixa a leitura fraca (amostra curta, numeros que se contradizem, mata-mata). Vazio se nao houver.
- Curto: "resumo" com no maximo 3 frases; cada "leitura" com uma frase."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "resumo": {"type": "string"},
        "mercados": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "mercado": {"type": "string"},
                    "tendencia": {"type": "string", "enum": ["over", "under", "dividido"]},
                    "leitura": {"type": "string"},
                },
                "required": ["mercado", "tendencia", "leitura"],
                "additionalProperties": False,
            },
        },
        "contexto": {"type": "string"},
        "alerta": {"type": "string"},
    },
    "required": ["resumo", "mercados", "contexto", "alerta"],
    "additionalProperties": False,
}


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
        max_tokens=2000,
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
    conteudo["mercados"] = (conteudo.get("mercados") or [])[:4]
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
    if linha and not (linha["status"] == "falhou" and linha["velho"]):
        return _resposta(linha)
    if not ligado():
        return {"status": "desligado"}

    with _lock(fixture_id):
        linha = _guardado(cur, fixture_id, dia)
        if linha and not (linha["status"] == "falhou" and linha["velho"]):
            return _resposta(linha)

        cur.execute("SELECT league_id, season, round, status, home_team_id, away_team_id "
                    "FROM fixtures WHERE fixture_id = %s", (fixture_id,))
        fix = cur.fetchone()
        if not fix:
            return {"status": "inelegivel", "motivo": "jogo fora da agenda"}
        if fix["status"] in _ENCERRADO:
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
            cur.execute("SELECT name FROM leagues WHERE league_id = %s LIMIT 1",
                        (fix["league_id"],))
            liga = (cur.fetchone() or {}).get("name")
            fatos = montar_fatos(dados, liga, formato, tabela,
                                 tecnicos_dos_times(cur, [fix["home_team_id"], fix["away_team_id"]]),
                                 amostra)
            conteudo, t_in, t_out = chamar_modelo(fatos)
        except Exception as e:
            cur.connection.rollback()
            logger.warning("[RESUMO IA] jogo %s falhou: %s", fixture_id, e)
            _gravar(cur, fixture_id, dia, "falhou", motivo=str(e)[:300])
            return {"status": "falhou"}
        _gravar(cur, fixture_id, dia, "ok", conteudo=conteudo, tokens_in=t_in, tokens_out=t_out)
        logger.info("[RESUMO IA] jogo %s gerado (%s in / %s out)", fixture_id, t_in, t_out)
        return {"status": "ok", **conteudo}
