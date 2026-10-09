"""Dossie da partida: o que a IA le' antes de dar o parecer (2026-09-27).

POR QUE EXISTE
--------------
O gate de IA recebia so' o PICK -- probabilidade, odd, edge, uma amostra -- e
decidia sobre um jogo que nao via. Pedido do usuario: a IA tem papel central,
e pra decidir ela precisa do que um analista olharia antes de apostar:

  medias feitas e cedidas   por mando, em todas as familias, jogo inteiro e
                            1o tempo, com a dispersao (CV) de cada uma
  forma recente             ultimos 5 contra a temporada: o time esta' igual,
                            melhor ou pior do que a media diz?
  confronto direto          os ultimos encontros, com placar e contadores
  tabela                    posicao, pontos e a pressao de pontos corridos
                            (competitive_pressure: a que distancia da fronteira
                            que importa, com quantas rodadas restando)
  escalacao                 quanto o time mudou de titulares entre os ultimos
                            jogos (rodizio), de player_match_stats
  desfalques                lesionados e suspensos da partida (/injuries)

UM LUGAR SO', CHAMADO PELO GATE
-------------------------------
Nenhum pipeline monta isto. O gate (ai_review.review) pede o dossie pelo
fixture_id, e assim os nove motores recebem o mesmo material -- inclusive os
de bilhete (multipla, bingo, alavancagem), que chamam o gate sem fixture.

NUMERO, NAO OPINIAO
-------------------
Tudo aqui e' contagem do banco ou da API. Nada vira termo de probabilidade: o
dossie informa o veto, nao a conta. Campo que nao existe fica de fora, nunca
vira zero -- a mesma invariante do resto do motor.

CUSTO
-----
Memo por fixture dentro do processo: a multipla avalia centenas de bilhetes
por rodada com as mesmas partidas, e sem o memo cada um refaria as consultas
e a chamada de /injuries. Por partida: ~6 consultas e 1 requisicao da API.
`AI_DOSSIE=off` desliga tudo; `AI_DOSSIE_DESFALQUES=off` so' a requisicao.
"""
from __future__ import annotations

import os
import statistics

_MEMO: dict = {}
#: Sinal de desfalque/tecnico por fixture, no formato de news_model.injury_signal.
#: Sai do mesmo memo do dossie: nenhuma consulta nem requisicao a mais.
_SINAL: dict = {}
#: Contexto atual do motor por fixture (contexto_atual.coletar), mesmo memo.
_CONTEXTO: dict = {}

#: Titular recente = comecou jogando em pelo menos isto dos ultimos 5 jogos.
TITULAR_RECENTE = 2

#: (rotulo, coluna do mandante, coluna do visitante). Cartao e' tratado a parte
#: (amarelo + 2x vermelho, a convencao de liquidacao).
_METRICAS = (
    ("gols",            "home_goals",           "away_goals"),
    ("gols_1t",         "home_goals_ht",        "away_goals_ht"),
    ("escanteios",      "home_corners",         "away_corners"),
    ("escanteios_1t",   "home_corners_1h",      "away_corners_1h"),
    ("chutes",          "home_total_shots",     "away_total_shots"),
    ("chutes_no_alvo",  "home_shots_on",        "away_shots_on"),
    ("chutes_no_alvo_1t", "home_shots_on_1h",   "away_shots_on_1h"),
    # Chance criada: mais estavel que o gol, e o que a IA precisa pra
    # separar time que marca pouco de time que cria pouco.
    ("chutes_dentro_da_area", "home_shots_insidebox", "away_shots_insidebox"),
    ("xg",              "home_xg",              "away_xg"),
    ("faltas",          "home_fouls",           "away_fouls"),
    ("impedimentos",    "home_offsides",        "away_offsides"),
)


def habilitado() -> bool:
    return os.getenv("AI_DOSSIE", "on").strip().lower() != "off"


def _cartoes(m: dict, lado: str):
    amarelo, vermelho = m.get(f"{lado}_yellow_cards"), m.get(f"{lado}_red_cards")
    if amarelo is None or vermelho is None:
        return None
    return amarelo + 2 * vermelho


def _lados(m: dict, team_id: int):
    """('home','away') quando o time foi mandante NAQUELE jogo."""
    return ("home", "away") if m.get("home_team_id") == team_id else ("away", "home")


#: Abaixo disto a media nao entra: dois jogos nao descrevem time nenhum, e a
#: IA leria o numero com o mesmo peso dos outros.
_MIN_JOGOS = 3


def _resumo(valores: list) -> dict | None:
    """Media, n e coeficiente de variacao. None sem amostra minima."""
    vals = [float(v) for v in valores if v is not None]
    if len(vals) < _MIN_JOGOS:
        return None
    media = sum(vals) / len(vals)
    cv = (statistics.pstdev(vals) / media) if (len(vals) > 1 and media > 0) else None
    return {"media": round(media, 2), "n": len(vals),
            **({"cv": round(cv, 2)} if cv is not None else {})}


def medias_do_time(jogos: list, team_id: int, mando: str | None = None) -> dict:
    """Feitos e cedidos por metrica, no mando pedido (None = todos os jogos).

    Mando e' filtrado aqui porque o mercado e' sobre ESTE jogo: o mandante em
    casa, o visitante fora (mesma regra de stats_model.pool_and_field)."""
    if mando == "home":
        jogos = [m for m in jogos if m.get("home_team_id") == team_id]
    elif mando == "away":
        jogos = [m for m in jogos if m.get("away_team_id") == team_id]
    saida: dict = {}
    for rotulo, col_casa, col_fora in _METRICAS:
        feitos, cedidos = [], []
        for m in jogos:
            eu, ele = _lados(m, team_id)
            feitos.append(m.get(col_casa if eu == "home" else col_fora))
            cedidos.append(m.get(col_casa if ele == "home" else col_fora))
        f, c = _resumo(feitos), _resumo(cedidos)
        if f or c:
            saida[rotulo] = {"feitos": f, "cedidos": c}
    feitos = [_cartoes(m, _lados(m, team_id)[0]) for m in jogos]
    cedidos = [_cartoes(m, _lados(m, team_id)[1]) for m in jogos]
    f, c = _resumo(feitos), _resumo(cedidos)
    if f or c:
        saida["cartoes"] = {"feitos": f, "cedidos": c}
    return saida


def forma(jogos: list, team_id: int, ultimos: int = 5) -> dict | None:
    """Resultados dos ultimos jogos (V/E/D) e gols, contra a temporada."""
    recentes = jogos[:ultimos]
    if not recentes:
        return None
    letras, marcados, sofridos = [], [], []
    for m in recentes:
        eu, ele = _lados(m, team_id)
        gm, gs = m.get(f"{eu}_goals"), m.get(f"{ele}_goals")
        if gm is None or gs is None:
            continue
        letras.append("V" if gm > gs else "E" if gm == gs else "D")
        marcados.append(gm)
        sofridos.append(gs)
    if not letras:
        return None
    return {"sequencia": "".join(letras),
            "gols_marcados_media": round(sum(marcados) / len(marcados), 2),
            "gols_sofridos_media": round(sum(sofridos) / len(sofridos), 2),
            "medias_ultimos_5": medias_do_time(recentes, team_id)}


def confronto_direto(h2h: list, home_team_id: int) -> list:
    saida = []
    for m in h2h[:5]:
        casa_e_o_mandante_de_hoje = m.get("home_team_id") == home_team_id
        saida.append({
            "data": str(m.get("match_date") or "")[:10],
            "mandante_de_hoje_em_casa": casa_e_o_mandante_de_hoje,
            "placar": f"{m.get('home_goals')}x{m.get('away_goals')}",
            **({"escanteios": m["total_corners"]} if m.get("total_corners") is not None else {}),
            **({"cartoes_amarelos": m["total_yellow_cards"]}
               if m.get("total_yellow_cards") is not None else {}),
        })
    return saida


def rodizio(escalacoes: list, extras: list | None = None) -> dict | None:
    """Quanto o time trocou de titulares entre jogos consecutivos.

    `escalacoes`: [(data, [player_id, ...])] do mais recente pro mais antigo.
    `extras`: [(formacao, tecnico)] na mesma ordem, quando vieram de
    team_lineups -- dali sai a troca de tecnico e de esquema.
    Devolve as trocas jogo a jogo e o NUCLEO (quem foi titular em todos): um
    time que troca 6 titulares por rodada e' outro time a cada jogo, e a media
    da temporada descreve uma formacao que nao entra em campo."""
    validas = [(d, set(t)) for d, t in escalacoes if t and len(t) >= 9]
    if len(validas) < 2:
        return None
    trocas = [len(validas[i][1] - validas[i + 1][1]) for i in range(len(validas) - 1)]
    nucleo = set.intersection(*(t for _, t in validas))
    saida = {"jogos": len(validas), "trocas_por_jogo": trocas,
             "media_de_trocas": round(sum(trocas) / len(trocas), 1),
             "titulares_em_todos": len(nucleo)}
    if extras:
        formacoes = [f for f, _ in extras if f]
        tecnicos = [t for _, t in extras if t]
        if formacoes:
            saida["formacoes_recentes"] = formacoes
        if len(set(tecnicos)) > 1:
            # Tecnico novo e' o caso em que a media inteira descreve outro time
            # (ver teams.structural_change_date, que e' marcado a mao).
            saida["tecnico_mudou"] = {"atual": tecnicos[0], "anterior": tecnicos[-1]}
    return saida


def _escalacoes_recentes(cur, team_id: int, antes_de, limite: int = 5) -> tuple:
    """([(data, titulares)], [(formacao, tecnico)] ou None). team_lineups
    primeiro, que tem formacao e tecnico; player_match_stats quando a coleta
    de escalacao ainda nao chegou naquele time."""
    try:
        cur.execute("""
            SELECT match_date, titulares, formation, coach_name
              FROM team_lineups
             WHERE team_id = %s AND match_date < %s
             ORDER BY match_date DESC
             LIMIT %s
        """, (team_id, antes_de, limite))
        linhas = cur.fetchall()
    except Exception:
        cur.connection.rollback()
        linhas = []
    if len(linhas) >= 2:
        return ([(r[0], r[1] or []) for r in linhas], [(r[2], r[3]) for r in linhas])
    cur.execute("""
        SELECT fixture_id, MAX(match_date) AS dia,
               ARRAY_AGG(player_id) FILTER (
                   WHERE NOT COALESCE(is_substitute, FALSE) AND COALESCE(minutes, 0) > 0
               ) AS titulares
          FROM player_match_stats
         WHERE team_id = %s AND match_date < %s
         GROUP BY fixture_id
         ORDER BY dia DESC
         LIMIT %s
    """, (team_id, antes_de, limite))
    return ([(r[1], r[2] or []) for r in cur.fetchall()], None)


def _desfalques(team_id: int, fixture_id: int, escalacoes: list) -> list | None:
    """Desfalques da partida, cada um com quantas vezes COMECOU JOGANDO nos
    ultimos jogos (cruzado por id em team_lineups/player_match_stats).

    None = nao se sabe (desligado ou a API falhou); [] = a API respondeu e
    ninguem esta' fora. A diferenca importa desde 2026-10-08: o contexto atual
    registra a falha em vez de ler "sem desfalque"."""
    if os.getenv("AI_DOSSIE_DESFALQUES", "on").strip().lower() == "off":
        return None
    try:
        from services.pick_engine.news_model import fetch_injuries
        lista = fetch_injuries(team_id, fixture_id=fixture_id, levantar=True)
    except Exception:
        return None
    inicios: dict = {}
    for _data, titulares in escalacoes or []:
        for pid in titulares or []:
            inicios[pid] = inicios.get(pid, 0) + 1
    vistos, saida = set(), []
    for item in lista or []:
        nome = item.get("name")
        if not nome or nome in vistos:
            continue
        vistos.add(nome)
        saida.append({"jogador": nome, "tipo": item.get("type"), "motivo": item.get("reason"),
                      "titular_nos_ultimos_jogos": inicios.get(item.get("id"), 0),
                      "_id": item.get("id")})
    return saida


def _sinal_do_lado(desfalques, rod) -> dict:
    """Um lado do sinal que news_model.news_score le.

    Separa quem de fato faz falta: "Missing Fixture" de quem vinha comecando
    jogando. Emprestado, inativo e reserva que nunca joga tambem aparecem em
    /injuries (medido no Corinthians em 27/09: 10 nomes, varios com motivo
    "Loan agreement" ou "Inactive") -- contar todos igual penalizava o time por
    quem nem entraria em campo.
    """
    titulares, outros = [], []
    for d in desfalques or []:
        fora_do_jogo = (d.get("tipo") or "").lower() == "missing fixture"
        comeca = d.get("titular_nos_ultimos_jogos", 0) >= TITULAR_RECENTE
        if fora_do_jogo and comeca:
            titulares.append(d["jogador"])
        elif comeca:
            outros.append(d["jogador"])      # duvida de titular recente
    return {"titulares_desfalcados": titulares, "outros_desfalcados": outros,
            "tecnico_mudou": bool((rod or {}).get("tecnico_mudou"))}


def _contexto_extra(cur, fixture_id, casa, fora, quando) -> dict:
    """Calendario, gols por faixa de minuto e clima. Cada um e' opcional: tabela
    que ainda nao existe no ambiente (coleta nova) simplesmente nao entra."""
    saida: dict = {}
    for chave, funcao in (("calendario", _calendario), ("gols_por_faixa", _gols_por_faixa)):
        for team in (casa, fora):
            try:
                valor = funcao(cur, team, quando)
            except Exception:
                cur.connection.rollback()
                valor = None
            if valor:
                saida[(chave, team)] = valor
    try:
        cur.execute("""SELECT altitude_m, temperatura_c, chuva_mm, vento_kmh, fonte
                         FROM clima_partida WHERE fixture_id = %s""", (fixture_id,))
        linha = cur.fetchone()
        if linha:
            alt, temp, chuva, vento, fonte = linha
            saida["clima"] = {k: v for k, v in {
                "altitude_m": round(alt) if alt is not None else None,
                "temperatura_c": temp, "chuva_mm": chuva, "vento_kmh": vento,
                "fonte": "previsao" if fonte == "forecast" else "medido"}.items() if v is not None}
    except Exception:
        cur.connection.rollback()
    return saida


def _calendario(cur, team_id, quando):
    from collectors.calendario_service import carga_do_time
    return carga_do_time(cur, team_id, quando)


def _gols_por_faixa(cur, team_id, quando):
    from collectors.eventos_collector_service import gols_por_faixa
    return gols_por_faixa(cur, team_id, quando)


def _contexto_do_motor(cur, fixture_id, casa, fora, quando, desfalques, extras,
                       liga=None, temporada=None) -> dict | None:
    """contexto_atual.coletar com o que o dossie ja' tem em maos. So'
    "Missing Fixture" conta como fora; "Questionable" vira duvida (incerteza,
    nunca desconto -- ninguem sabe se joga)."""
    from services.pick_engine import contexto_atual
    if contexto_atual.modo() == "off":
        return None
    por_lado = {}
    for lado, team_id in (("home", casa), ("away", fora)):
        lista = desfalques.get(team_id)
        if lista is None:
            por_lado[lado] = {"falhou": os.getenv("AI_DOSSIE_DESFALQUES", "on")
                              .strip().lower() != "off"}
            continue
        por_lado[lado] = {
            "fora": {d["_id"] for d in lista
                     if d.get("_id") and (d.get("tipo") or "").lower() == "missing fixture"},
            "duvidas": [d["jogador"] for d in lista
                        if (d.get("tipo") or "").lower() == "questionable"],
        }
    calendario = {t: extras.get(("calendario", t)) for t in (casa, fora)
                  if extras.get(("calendario", t))}
    try:
        return contexto_atual.coletar(cur, fixture_id, casa, fora, quando, por_lado, calendario,
                                      league_id=liga, season=temporada)
    except Exception as e:
        cur.connection.rollback()
        print(f"[DOSSIE] contexto atual do fixture {fixture_id}: {e}")
        return None


def _leitura_tatica(ctx, hist_casa, hist_fora, casa, fora) -> dict | None:
    """O que a IA le' sobre como os times jogam, em tres blocos que nao se
    misturam: OBSERVADO (numeros da base, com n), MODELO (cenarios do
    intervalo e o efeito medido do confronto, com o veredito da validacao) e
    LIMITES (o que cada proxy aproxima e o que nao existe). Hipotese e' da IA,
    e ela tem que dizer que e' hipotese."""
    try:
        from services.pick_engine import team_profile_model as tpm, efeito_tatico
        ctx = ctx or {}
        ref = ctx.get("referencia_tatica")
        observado, perfis = {}, {}
        for nome, lado, tid, hist in (("mandante", "home", casa, hist_casa),
                                      ("visitante", "away", fora, hist_fora)):
            t = ctx.get(lado) or {}
            regime = t.get("regime") or {}
            perfis[lado] = tpm.perfil_tatico(hist, tid, ref)
            cmp = tpm.comparar_regimes(hist, tid, regime["inicio"]) if regime.get("inicio") else None
            r = tpm.resumo_tatico_para_ia(perfis[lado], cmp, t.get("carreira_tecnico"),
                                          t.get("formacoes"))
            if r:
                observado[nome] = r
        if not observado:
            return None
        modelo = {}
        cen = tpm.cenarios_do_intervalo(perfis["home"], perfis["away"])
        if cen:
            modelo["cenarios_do_intervalo"] = cen
        tat = efeito_tatico.preparar_partida(ctx, hist_casa, hist_fora, casa, fora)
        if tat:
            modelo["efeito_medido_do_confronto"] = {
                est: {"multiplicador_mandante": m["home"]["multiplicador"],
                      "multiplicador_visitante": m["away"]["multiplicador"],
                      "validado_fora_da_amostra": m.get("aprovado", False),
                      "principais_contribuicoes": m["home"]["contribuicoes"]}
                for est, m in tat["multiplicadores"].items()}
        return {"observado": observado, **({"modelo": modelo} if modelo else {}),
                "limites": list(tpm.LIMITES_DOS_PROXIES)}
    except Exception as e:
        print(f"[DOSSIE] leitura tatica: {e}")
        return None


def contexto_do_motor(fixture_id: int) -> dict | None:
    """Contexto atual da partida pro motor (contexto_partida de
    orchestrator.analyze_fixture_markets). Sai do mesmo memo do dossie."""
    if not fixture_id:
        return None
    _obter(fixture_id)
    return _CONTEXTO.get(fixture_id)


def sinal_de_desfalques(fixture_id: int) -> dict | None:
    """Sinal de desfalques e troca de tecnico pro Score Final do motor
    (news_data de orchestrator.analyze_fixture_markets). None sem dado.

    `MOTOR_DESFALQUES` (news_model.modo_desfalques), independente do dossie
    da IA: e' o motor lendo o mesmo dado, nao a IA. Em `shadow` (padrao) o
    sinal sai daqui e o orchestrator so' o registra."""
    from services.pick_engine.news_model import modo_desfalques
    if not fixture_id or modo_desfalques() == "off":
        return None
    _obter(fixture_id)
    return _SINAL.get(fixture_id)


def montar(fixture_id: int) -> dict | None:
    """Dossie de uma partida do dia, ou None quando nao da' pra montar."""
    if not fixture_id or not habilitado():
        return None
    return _obter(fixture_id)


def _obter(fixture_id: int) -> dict | None:
    if not fixture_id:
        return None
    if fixture_id in _MEMO:
        return _MEMO[fixture_id]
    dossie = None
    try:
        dossie = _montar(fixture_id)
    except Exception as e:
        print(f"[DOSSIE] fixture {fixture_id}: {e}")
        dossie = None
    _MEMO[fixture_id] = dossie
    return dossie


def _montar(fixture_id: int) -> dict | None:
    from utils.db_utils import get_connection
    from services.match_stats_service import MatchStatsService
    from services.standings_service import StandingsService
    from services.pick_engine import competitive_pressure

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT fixture_id, home_team_id, away_team_id, home_team, away_team,
                   league_id, season, match_datetime, round
              FROM fixtures WHERE fixture_id = %s
        """, (fixture_id,))
        linha = cur.fetchone()
        if not linha:
            return None
        (_, casa, fora, nome_casa, nome_fora, liga, temporada, quando, rodada) = linha

        stats = MatchStatsService()
        hist_casa = stats.get_all_matches_full(casa, temporada, liga, before_date=quando)
        hist_fora = stats.get_all_matches_full(fora, temporada, liga, before_date=quando)
        h2h = stats.get_h2h_matches(casa, fora, limit=5, before_date=quando)

        tabela = StandingsService().get_league_table(liga, temporada)
        pressao = competitive_pressure.pressao_da_partida(tabela, casa, fora, league_id=liga)

        def linha_da_tabela(team_id):
            t = next((l for l in (tabela or []) if l.get("team_id") == team_id), None)
            if not t:
                return None
            return {k: t.get(k) for k in ("rank", "points", "played", "goal_diff", "form", "description")
                    if t.get(k) is not None}

        escal_casa = _escalacoes_recentes(cur, casa, quando)
        escal_fora = _escalacoes_recentes(cur, fora, quando)
        extras = _contexto_extra(cur, fixture_id, casa, fora, quando)
        # Uma consulta de /injuries por time, usada por TRES leitores: o dossie
        # da IA, o news_score e o contexto atual do motor.
        desfalques = {casa: _desfalques(casa, fixture_id, escal_casa[0]),
                      fora: _desfalques(fora, fixture_id, escal_fora[0])}
        _CONTEXTO[fixture_id] = _contexto_do_motor(
            cur, fixture_id, casa, fora, quando, desfalques, extras, liga, temporada)
    finally:
        cur.close()
        conn.close()

    sinal: dict = {"is_approximation": False}

    def time(team_id, nome, hist, mando, escal):
        rod = rodizio(*escal)
        desf = desfalques.get(team_id)
        sinal[mando] = _sinal_do_lado(desf, rod)
        # Pra IA: titular recente primeiro, e sem o id interno.
        desf_ia = sorted(({k: v for k, v in d.items() if k != "_id"} for d in desf or []),
                         key=lambda d: -d["titular_nos_ultimos_jogos"])[:10]
        bloco = {
            "nome": nome,
            "medias_no_mando_deste_jogo": medias_do_time(hist, team_id, mando),
            "forma": forma(hist, team_id),
            "tabela": linha_da_tabela(team_id),
            "rodizio_de_titulares": rod,
            "desfalques": desf_ia,
            "calendario": extras.get(("calendario", team_id)),
            "gols_por_faixa_de_minuto": extras.get(("gols_por_faixa", team_id)),
        }
        return {k: v for k, v in bloco.items() if v not in (None, {}, [])}

    from services.pick_engine import contexto_atual
    dossie = {
        "rodada": rodada,
        "mandante": time(casa, nome_casa, hist_casa, "home", escal_casa),
        "visitante": time(fora, nome_fora, hist_fora, "away", escal_fora),
        "confronto_direto": confronto_direto(h2h, casa),
        "pressao_de_tabela": competitive_pressure.descrever(pressao) or None,
        "clima_e_altitude": extras.get("clima"),
        # Tecnico e desde quando, producao dos desfalcados, viagem, fontes que
        # falharam -- o que o motor usou (ou mediu, em sombra) na conta.
        "contexto_atual": contexto_atual.resumo_para_ia(_CONTEXTO.get(fixture_id)),
        "leitura_tatica": _leitura_tatica(_CONTEXTO.get(fixture_id), hist_casa, hist_fora,
                                          casa, fora),
    }
    _SINAL[fixture_id] = sinal
    return {k: v for k, v in dossie.items() if v not in (None, {}, [])}
