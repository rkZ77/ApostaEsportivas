"""Leitura de IA da liga, na aba Ligas de /jogos (15/10/2026, pedido do usuario).

A aba mostra os numeros da liga; a leitura diz em poucas linhas o que eles
apontam: que tipo de liga e' (muitos gols, poucos, muito cartao), quais
linhas a liga inteira sustenta e quais times puxam os jogos pra cima ou pra
baixo.

CUSTO, MESMA REGRA DA LEITURA DO RAIO-X (resumo_ia.py):
  - UMA vez por liga por dia (escolha do usuario), gerada na primeira abertura
    e guardada em `liga_resumo_ia`. Quem abre depois le' o banco. ~20 ligas =
    no maximo ~20 chamadas por dia.
  - Mesmo modelo barato (Haiku), esforco baixo, saida em JSON.
  - So' dados do banco · nenhuma chamada a API-Football.
  - So' liga com amostra (MIN_JOGOS na temporada).
  - Teto por dia (LIGA_IA_MAX_DIA) e o mesmo desligamento (RESUMO_IA=off).

Os numeros que aparecem na tela saem da conta daqui, nunca do texto do modelo.

UMA GERACAO SO' PRO SITE E PRO MOTOR (15/10/2026, pedido do usuario: "fazer 1
coisa so' pra nao ficar duas e gastar errado"). O motor tinha o proprio perfil
de liga (ApostaEsportivas/src/atualizar_ligas.py: Sonnet, com TODOS os jogos da
temporada no prompt) que o gate de IA le' em `league_analysis`. Agora quem
escreve `league_analysis` e' esta leitura (_gravar_perfil_do_motor), com o
texto da liga sem citar time · o script do motor nao chama mais a IA.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import defaultdict

import resumo_ia
from resumo_ia import _media, _pct, _sem_vazios

logger = logging.getLogger(__name__)

#: Jogos encerrados minimos da liga na temporada pra valer uma leitura.
MIN_JOGOS = 20
#: Jogos minimos de um time pra ele entrar na lista que vai pro modelo.
MIN_JOGOS_TIME = 4
#: 2 (19/10/2026): todos os mercados do Raio-X na leitura.
VERSAO = 2

_locks: dict[int, threading.Lock] = {}
_locks_guarda = threading.Lock()


def max_por_dia() -> int:
    try:
        return int(os.getenv("LIGA_IA_MAX_DIA", "60"))
    except ValueError:
        return 60


def _lock(league_id: int) -> threading.Lock:
    with _locks_guarda:
        return _locks.setdefault(league_id, threading.Lock())


DDL = """
    CREATE TABLE IF NOT EXISTS liga_resumo_ia (
        league_id   INTEGER NOT NULL,
        dia         DATE NOT NULL,
        status      VARCHAR(12) NOT NULL,
        conteudo    JSONB,
        motivo      TEXT,
        modelo      VARCHAR(40),
        tokens_in   INTEGER,
        tokens_out  INTEGER,
        criado_em   TIMESTAMP NOT NULL DEFAULT NOW(),
        PRIMARY KEY (league_id, dia)
    )
"""


# ─────────────────────────────────────────────────────────────────────────────
# Fatos
# ─────────────────────────────────────────────────────────────────────────────
def _total(j: dict, a: str, b: str):
    if j.get(a) is None or j.get(b) is None:
        return None
    return j[a] + j[b]


def _acima(a: str, b: str, linha: float):
    return lambda j: None if _total(j, a, b) is None else _total(j, a, b) > linha


def numeros_da_liga(jogos: list[dict]) -> dict | None:
    """Medias e taxas por linha sobre os jogos da temporada.

    `pct_` e' percentual de JOGOS em que a linha bateu, como no Raio-X.
    """
    if not jogos:
        return None
    hg, ag = "home_goals", "away_goals"
    hc, ac = "home_corners", "away_corners"
    hy, ay = "home_yellow_cards", "away_yellow_cards"
    com_placar = [j for j in jogos if j.get(hg) is not None and j.get(ag) is not None]
    gols = [j[hg] + j[ag] for j in com_placar]
    media = sum(gols) / len(gols) if gols else None
    return {
        "jogos": len(jogos),
        "gols_media": _media([_total(j, hg, ag) for j in jogos]),
        # Volatilidade (pedida no perfil antigo do motor): o quanto o total de
        # gols foge da media. Liga de 2,6 com desvio 1,9 e' "ou 0x0 ou 4x2".
        "gols_desvio_padrao": (round((sum((g - media) ** 2 for g in gols) / len(gols)) ** 0.5, 2)
                               if gols else None),
        "pct_0x0": _pct(com_placar, lambda j: j[hg] + j[ag] == 0),
        "gols_mandante_media": _media([j.get(hg) for j in jogos]),
        "gols_visitante_media": _media([j.get(ag) for j in jogos]),
        "pct_over_1_5_gols": _pct(jogos, _acima(hg, ag, 1.5)),
        "pct_over_2_5_gols": _pct(jogos, _acima(hg, ag, 2.5)),
        "pct_over_3_5_gols": _pct(jogos, _acima(hg, ag, 3.5)),
        "pct_ambas_marcam": _pct(jogos, lambda j: None if j.get(hg) is None or j.get(ag) is None
                                 else j[hg] > 0 and j[ag] > 0),
        "pct_gol_no_1t": _pct(jogos, _acima("home_goals_ht", "away_goals_ht", 0.5)),
        "pct_vitoria_mandante": _pct(com_placar, lambda j: j[hg] > j[ag]),
        "pct_empate": _pct(com_placar, lambda j: j[hg] == j[ag]),
        "pct_vitoria_visitante": _pct(com_placar, lambda j: j[hg] < j[ag]),
        "escanteios_media": _media([_total(j, hc, ac) for j in jogos]),
        "pct_over_8_5_escanteios": _pct(jogos, _acima(hc, ac, 8.5)),
        "pct_over_9_5_escanteios": _pct(jogos, _acima(hc, ac, 9.5)),
        "pct_over_10_5_escanteios": _pct(jogos, _acima(hc, ac, 10.5)),
        "amarelos_media": _media([_total(j, hy, ay) for j in jogos]),
        "pct_over_3_5_amarelos": _pct(jogos, _acima(hy, ay, 3.5)),
        "pct_over_4_5_amarelos": _pct(jogos, _acima(hy, ay, 4.5)),
        "vermelhos_media": _media([_total(j, "home_red_cards", "away_red_cards") for j in jogos]),
        # TODOS OS MERCADOS DO RAIO-X (19/10/2026, pedido do usuario): faltas,
        # chutes, chutes no alvo, impedimentos, defesas, 1o e 2o tempo. Mesma
        # conta da leitura do jogo (resumo_ia._MERCADOS_DO_JOGO). Com ~20
        # ligas por dia o custo e' pequeno, entao vai a linha inteira (o corte
        # de 40/60 e' do SYSTEM, nao o de 35/65 do jogo).
        "mercados": {nome: resumo_ia._mercado([_pelo_mandante(j) for j in jogos], c, q, linhas, p,
                                              corte=None)
                     for nome, c, q, p, linhas in resumo_ia._MERCADOS_DO_JOGO},
    }


_pelo_mandante = resumo_ia.pelo_mandante


#: Tamanho do recorte recente: ~3 rodadas de uma liga de 20 times.
RECENTES = 30


def numeros_por_time(jogos: list[dict]) -> list[dict]:
    """Cada time pelos jogos DELE (casa e fora juntos): as linhas do jogo e o
    que o time faz. E' daqui que o modelo tira quem puxa a liga pra cima."""
    por_time: dict = defaultdict(list)
    nomes: dict = {}
    for j in jogos:
        for lado, outro in (("home", "away"), ("away", "home")):
            tid = j.get(f"{lado}_team_id")
            if tid is None:
                continue
            nomes[tid] = j.get(f"{lado}_team") or nomes.get(tid)
            por_time[tid].append({
                "gp": j.get(f"{lado}_goals"), "gc": j.get(f"{outro}_goals"),
                "ep": j.get(f"{lado}_corners"), "ec": j.get(f"{outro}_corners"),
                "ap": j.get(f"{lado}_yellow_cards"), "ac": j.get(f"{outro}_yellow_cards"),
                "fp": j.get(f"{lado}_fouls"), "fc": j.get(f"{outro}_fouls"),
                "sp": j.get(f"{lado}_shots_on"), "sc": j.get(f"{outro}_shots_on"),
            })
    saida = []
    for tid, js in por_time.items():
        if len(js) < MIN_JOGOS_TIME:
            continue
        saida.append({
            "team_id": tid, "nome": nomes.get(tid), "jogos": len(js),
            "gols_pro_media": _media([x["gp"] for x in js]),
            "gols_contra_media": _media([x["gc"] for x in js]),
            "pct_over_2_5_gols": _pct(js, _acima("gp", "gc", 2.5)),
            "pct_ambas_marcam": _pct(js, lambda x: None if x["gp"] is None or x["gc"] is None
                                     else x["gp"] > 0 and x["gc"] > 0),
            "escanteios_jogo_media": _media([_total(x, "ep", "ec") for x in js]),
            "amarelos_jogo_media": _media([_total(x, "ap", "ac") for x in js]),
            "faltas_jogo_media": _media([_total(x, "fp", "fc") for x in js]),
            "chutes_no_alvo_jogo_media": _media([_total(x, "sp", "sc") for x in js]),
        })
    saida.sort(key=lambda t: t["nome"] or "")
    return saida


def montar_fatos(liga: str | None, season, jogos: list[dict], tabela: list[dict],
                 media_do_site: dict | None) -> dict:
    """Tudo que o modelo pode usar, ja' contado · ele interpreta, nao calcula.

    `jogos` vem do mais recente pro mais antigo (jogos_da_temporada). O recorte
    recente so' entra quando a temporada tem o dobro dele: com menos, ele e'
    quase a temporada inteira e nao diz nada de novo.
    """
    recentes = jogos[:RECENTES] if len(jogos) >= 2 * RECENTES else None
    return _sem_vazios({
        "liga": {"nome": liga, "temporada": season},
        "numeros_da_liga_na_temporada": numeros_da_liga(jogos),
        f"numeros_dos_ultimos_{RECENTES}_jogos": numeros_da_liga(recentes) if recentes else None,
        "media_das_ligas_do_site": media_do_site,
        "times": numeros_por_time(jogos),
        "tabela_topo_e_fundo": tabela,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Leituras do banco
# ─────────────────────────────────────────────────────────────────────────────
def temporada_atual(cur, league_id: int):
    cur.execute("SELECT MAX(season) AS s FROM match_statistics WHERE league_id = %s",
                (league_id,))
    return (cur.fetchone() or {}).get("s")


def jogos_da_temporada(cur, league_id: int, season) -> list[dict]:
    # Nome por subconsulta, nunca por JOIN em `teams` (ver
    # routers/suggestions._nome_do_time): o JOIN repete a partida.
    cur.execute("""
        SELECT ms.home_team_id, ms.away_team_id,
               (SELECT t.name FROM teams t WHERE t.team_id = ms.home_team_id LIMIT 1) AS home_team,
               (SELECT t.name FROM teams t WHERE t.team_id = ms.away_team_id LIMIT 1) AS away_team,
               ms.home_goals, ms.away_goals, ms.home_goals_ht, ms.away_goals_ht,
               ms.home_corners, ms.away_corners,
               ms.home_yellow_cards, ms.away_yellow_cards,
               ms.home_red_cards, ms.away_red_cards,
               ms.home_fouls, ms.away_fouls, ms.home_shots_on, ms.away_shots_on,
               ms.home_total_shots, ms.away_total_shots, ms.home_offsides, ms.away_offsides,
               ms.home_goalkeeper_saves, ms.away_goalkeeper_saves,
               ms.home_corners_1h, ms.away_corners_1h,
               ms.home_yellow_cards_1h, ms.away_yellow_cards_1h,
               ms.home_shots_on_1h, ms.away_shots_on_1h
          FROM match_statistics ms
         WHERE ms.league_id = %s AND ms.season = %s
           AND ms.status IN ('FT','AET','PEN')
         ORDER BY ms.match_date DESC
    """, (league_id, season))
    return [dict(r) for r in cur.fetchall()]


def media_do_site(cur) -> dict | None:
    """Media por jogo de todas as ligas do site na temporada corrente de cada
    uma · e' a regua de "liga de muitos gols" que o modelo usa."""
    try:
        cur.execute("""
            SELECT ROUND(AVG(ms.home_goals + ms.away_goals)::numeric, 2) AS gols,
                   ROUND(AVG(ms.home_corners + ms.away_corners)::numeric, 2) AS escanteios,
                   ROUND(AVG(ms.home_yellow_cards + ms.away_yellow_cards)::numeric, 2) AS amarelos
              FROM match_statistics ms
              JOIN (SELECT league_id, MAX(season) AS season
                      FROM match_statistics GROUP BY league_id) u
                ON u.league_id = ms.league_id AND u.season = ms.season
             WHERE ms.status IN ('FT','AET','PEN')
        """)
        r = cur.fetchone() or {}
        return {"gols_media": _num(r.get("gols")), "escanteios_media": _num(r.get("escanteios")),
                "amarelos_media": _num(r.get("amarelos"))}
    except Exception:
        cur.connection.rollback()
        logger.warning("[LIGA IA] media do site indisponivel", exc_info=True)
        return None


def _num(v):
    return float(v) if v is not None else None


def tabela_resumida(cur, league_id: int) -> list[dict]:
    """Os 3 primeiros e os 3 ultimos de cada grupo · o bastante pra situar."""
    try:
        cur.execute("""
            SELECT group_name, rank, team_name, points, played,
                   COUNT(*) OVER (PARTITION BY group_name) AS n
              FROM league_standings
             WHERE league_id = %s
               AND season = (SELECT MAX(season) FROM league_standings WHERE league_id = %s)
             ORDER BY group_name NULLS FIRST, rank
        """, (league_id, league_id))
        return [{"grupo": r["group_name"], "posicao": r["rank"], "time": r["team_name"],
                 "pontos": r["points"], "jogos": r["played"]}
                for r in cur.fetchall() if r["rank"] <= 3 or r["rank"] > r["n"] - 3]
    except Exception:
        cur.connection.rollback()
        logger.warning("[LIGA IA] tabela indisponivel", exc_info=True)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# A chamada
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM = """Você escreve a leitura da LIGA na aba Ligas do PickIA, um site brasileiro de análise de apostas esportivas. Quem lê está no celular e quer saber em segundos que tipo de liga é esta para apostar: muitos ou poucos gols, escanteios, cartões, força do mando, e quais times puxam os jogos para cima ou para baixo.

Fonte:
- Use SOMENTE os números do JSON. Não invente lesão, notícia, odd, técnico ou história. Dado que não veio não existe.
- Todo campo "pct_" é PERCENTUAL DE JOGOS (em quantos jogos aconteceu). Ex.: pct_over_2_5_gols = 62 significa "6 de cada 10 jogos tiveram 3 gols ou mais".
- "media_das_ligas_do_site" é a régua: compare a liga com ela ("acima da média das ligas que acompanhamos").
- "mercados" traz TODOS os mercados do Raio-X (gols, escanteios, cartões, chutes no alvo, chutes, faltas, impedimentos, defesas dos goleiros, e 1º e 2º tempo com sufixo "_1t"/"_2t"): "media" por jogo e "pct_mais_de": {"9.5": 62} = passou de 9,5 em 62% dos jogos. Leia todos antes de escolher as tendências: a mais forte pode ser de faltas ou de 1º tempo, não só de gols.
- Em "times", os números são dos jogos de cada time (casa e fora juntos).
- "numeros_dos_ultimos_30_jogos", quando vier, é o momento atual. Se uma linha mudou 10 pontos ou mais em relação à temporada, diga (ex.: "nas últimas rodadas os gols caíram"). Se não mudou, não comente.
- "gols_desvio_padrao" é a volatilidade: acima de 1,7 a liga alterna jogos fechados e abertos, e a média engana; abaixo de 1,4 os placares são parecidos entre si.

Este texto também vai para o revisor de risco do motor de picks, que só veta palpite. Por isso:
- Seja específico sobre o que a liga NÃO sustenta (linhas com pct baixo, volatilidade alta, mudança recente contra a temporada).
- Não afirme nada que os números não mostrem.

O que escrever:
- "resumo": 2 frases, no máximo, sobre o perfil da liga com os números principais.
- "tendencias": até 4 linhas da LIGA com pct de 60 ou mais ("over") ou 40 ou menos ("under"). Ex.: "Mais de 1,5 gol", "Ambas marcam", "Mais de 9,5 escanteios", "Mais de 22,5 faltas", "Gol no 1º tempo". Um mercado por família, na linha mais forte. Para "under", "pct" é o percentual de jogos em que a linha NÃO bateu. Nada entre 41 e 59.
- "mando": 1 frase sobre a força de quem joga em casa, com os percentuais de vitória.
- "momento": 1 frase sobre o recorte recente contra a temporada, quando houver diferença de 10 pontos ou mais em alguma linha. Vazio se não houver recorte ou diferença.
- "times_over": até 3 times cujos jogos mais passam da média da liga (gols, escanteios ou cartões). "times_under": até 3 cujos jogos mais ficam abaixo. Em cada um, "time" é o nome EXATAMENTE como veio em "nome", e "leitura" é 1 frase curta com o número que justifica. Só times com 6 ou mais jogos.
- "alerta": o que deixa a leitura fraca (temporada no começo, poucos jogos). Vazio se não houver.

Estilo: português do Brasil com acentuação correta. Decimais com vírgula ("2,8 gols por jogo"). Direto, sem jargão estatístico, sem certeza nem promessa. Fale em tendência."""

_TIME = {
    "type": "object",
    "properties": {"time": {"type": "string"}, "leitura": {"type": "string"}},
    "required": ["time", "leitura"],
    "additionalProperties": False,
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "resumo": {"type": "string"},
        "tendencias": {"type": "array", "items": resumo_ia._MERCADO},
        "mando": {"type": "string"},
        "momento": {"type": "string"},
        "times_over": {"type": "array", "items": _TIME},
        "times_under": {"type": "array", "items": _TIME},
        "alerta": {"type": "string"},
    },
    "required": ["resumo", "tendencias", "mando", "momento", "times_over", "times_under", "alerta"],
    "additionalProperties": False,
}


def chamar_modelo(fatos: dict) -> tuple[dict, int, int]:
    """(conteudo, tokens de entrada, tokens de saida). Levanta em falha."""
    resposta = resumo_ia._get_client().messages.create(
        model=resumo_ia.MODELO,
        max_tokens=6000,
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
    conteudo["tendencias"] = (conteudo.get("tendencias") or [])[:4]
    conteudo["times_over"] = (conteudo.get("times_over") or [])[:3]
    conteudo["times_under"] = (conteudo.get("times_under") or [])[:3]
    u = resposta.usage
    return conteudo, int(u.input_tokens or 0), int(u.output_tokens or 0)


def _com_escudo(conteudo: dict, times: list[dict]) -> None:
    """O modelo devolve o nome; o escudo vem do id que a conta conhece. Nome
    que nao bate com nenhum time da liga sai da lista (o modelo inventou)."""
    por_nome = {(t.get("nome") or "").strip().lower(): t["team_id"] for t in times}
    for chave in ("times_over", "times_under"):
        lista = []
        for t in conteudo.get(chave) or []:
            tid = por_nome.get((t.get("time") or "").strip().lower())
            if tid is not None:
                lista.append({**t, "team_id": tid})
        conteudo[chave] = lista


def _br(v) -> str:
    return "-" if v is None else f"{v}".replace(".", ",")


def texto_pro_motor(liga, season, jogos: int, conteudo: dict, numeros: dict | None = None) -> str:
    """O perfil em prosa que o gate do motor le' (`league_profile`).

    Mesmo recorte do prompt antigo do motor: comportamento da LIGA, sem citar
    time (as listas de times ficam so' na tela). A 2a linha e' de NUMEROS
    calculados aqui, nao escritos pela IA: o gate decide veto com numero
    auditavel, e a prosa so' interpreta.
    """
    linhas = [f"{liga or 'Liga'} ({jogos} jogos) · Season {season}"]
    if numeros:
        n = numeros
        linhas.append(
            f"– Números: gols {_br(n.get('gols_media'))}/jogo (desvio {_br(n.get('gols_desvio_padrao'))}), "
            f"over 2,5 {_br(n.get('pct_over_2_5_gols'))}%, ambas marcam {_br(n.get('pct_ambas_marcam'))}%, "
            f"0x0 {_br(n.get('pct_0x0'))}%, escanteios {_br(n.get('escanteios_media'))}/jogo, "
            f"amarelos {_br(n.get('amarelos_media'))}/jogo, mandante vence {_br(n.get('pct_vitoria_mandante'))}%.")
    if conteudo.get("resumo"):
        linhas.append(f"– {conteudo['resumo']}")
    for t in conteudo.get("tendencias") or []:
        lado = "a favor" if t.get("tendencia") == "over" else "contra"
        linhas.append(f"– {t.get('mercado')}: {t.get('pct')}% {lado}. {t.get('leitura') or ''}".rstrip())
    if conteudo.get("mando"):
        linhas.append(f"– {conteudo['mando']}")
    if conteudo.get("momento"):
        linhas.append(f"– {conteudo['momento']}")
    if conteudo.get("alerta"):
        linhas.append(f"– Atenção: {conteudo['alerta']}")
    return "\n".join(linhas)


def _gravar_perfil_do_motor(cur, league_id, liga, season, texto: str) -> None:
    """Upsert em `league_analysis` · mesma tabela e mesma chave que o motor
    criou (services/league_analysis_service.criar_tabela). Falhar aqui nao
    derruba a leitura do site: o gate do motor falha aberto sem perfil."""
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS league_analysis (
                id            SERIAL PRIMARY KEY,
                league_id     INTEGER NOT NULL,
                league_name   TEXT,
                season        INTEGER NOT NULL,
                analysis_text TEXT,
                created_at    TIMESTAMP DEFAULT NOW(),
                updated_at    TIMESTAMP DEFAULT NOW(),
                UNIQUE (league_id, season)
            )
        """)
        cur.execute("""
            INSERT INTO league_analysis (league_id, league_name, season, analysis_text)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (league_id, season)
            DO UPDATE SET analysis_text = EXCLUDED.analysis_text,
                          league_name = EXCLUDED.league_name, updated_at = NOW()
        """, (league_id, liga, int(season), texto))
        cur.connection.commit()
    except Exception:
        cur.connection.rollback()
        logger.warning("[LIGA IA] perfil do motor nao gravado (liga %s)", league_id, exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Fluxo
# ─────────────────────────────────────────────────────────────────────────────
def _guardado(cur, league_id: int, dia) -> dict | None:
    cur.execute("""
        SELECT status, conteudo, motivo, criado_em,
               criado_em < NOW() - make_interval(mins => %s) AS velho
          FROM liga_resumo_ia WHERE league_id = %s AND dia = %s
    """, (resumo_ia._REPETIR_FALHA_MIN, league_id, dia))
    return cur.fetchone()


def _gravar(cur, league_id, dia, status, conteudo=None, motivo=None,
            tokens_in=None, tokens_out=None) -> None:
    cur.execute("""
        INSERT INTO liga_resumo_ia
            (league_id, dia, status, conteudo, motivo, modelo, tokens_in, tokens_out)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (league_id, dia) DO UPDATE SET
            status = EXCLUDED.status, conteudo = EXCLUDED.conteudo,
            motivo = EXCLUDED.motivo, modelo = EXCLUDED.modelo,
            tokens_in = EXCLUDED.tokens_in, tokens_out = EXCLUDED.tokens_out,
            criado_em = NOW()
    """, (league_id, dia, status,
          json.dumps(conteudo, ensure_ascii=False) if conteudo is not None else None,
          motivo, resumo_ia.MODELO if status == "ok" else None, tokens_in, tokens_out))
    cur.connection.commit()


def _vale(linha) -> bool:
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
        return (c or {}).get("versao", 0) >= VERSAO
    return True


def leitura_da_liga(cur, league_id: int) -> dict:
    """A leitura do dia: do banco, ou gerada agora se for a primeira abertura.
    Um lock por liga: dez pessoas abrindo a mesma liga viram UMA chamada."""
    dia = resumo_ia._hoje()
    linha = _guardado(cur, league_id, dia)
    if _vale(linha):
        return resumo_ia._resposta(linha)
    if not resumo_ia.ligado():
        return {"status": "desligado"}

    with _lock(league_id):
        linha = _guardado(cur, league_id, dia)
        if _vale(linha):
            return resumo_ia._resposta(linha)

        season = temporada_atual(cur, league_id)
        jogos = jogos_da_temporada(cur, league_id, season) if season else []
        if len(jogos) < MIN_JOGOS:
            motivo = f"temporada com {len(jogos)} jogo(s) encerrado(s); a leitura pede {MIN_JOGOS}"
            _gravar(cur, league_id, dia, "inelegivel", motivo=motivo)
            return {"status": "inelegivel", "motivo": motivo}

        cur.execute("SELECT COUNT(*) AS n FROM liga_resumo_ia WHERE dia = %s AND status = 'ok'",
                    (dia,))
        if (cur.fetchone() or {}).get("n", 0) >= max_por_dia():
            return {"status": "limite", "motivo": "limite de leituras do dia"}

        try:
            cur.execute("SELECT name FROM leagues WHERE league_id = %s LIMIT 1", (league_id,))
            liga = (cur.fetchone() or {}).get("name")
            fatos = montar_fatos(liga, season, jogos, tabela_resumida(cur, league_id),
                                 media_do_site(cur))
            conteudo, t_in, t_out = chamar_modelo(fatos)
        except Exception as e:
            cur.connection.rollback()
            logger.warning("[LIGA IA] liga %s falhou: %s", league_id, e)
            _gravar(cur, league_id, dia, "falhou", motivo=str(e)[:300])
            return {"status": "falhou"}
        _com_escudo(conteudo, fatos.get("times") or [])
        conteudo["temporada"] = season
        conteudo["jogos"] = len(jogos)
        conteudo["versao"] = VERSAO
        _gravar(cur, league_id, dia, "ok", conteudo=conteudo, tokens_in=t_in, tokens_out=t_out)
        _gravar_perfil_do_motor(cur, league_id, liga, season, texto_pro_motor(
            liga, season, len(jogos), conteudo, fatos.get("numeros_da_liga_na_temporada")))
        logger.info("[LIGA IA] liga %s gerada (%s in / %s out)", league_id, t_in, t_out)
        return {"status": "ok", **conteudo}
