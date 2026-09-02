"""
Explorador de ligas e temporadas · lê a API-Football, não o banco.

POR QUE existe uma segunda fonte de estatística no site:

A aba Estatísticas responde bem "como está a liga que a IA cobre", porque lê
`match_statistics`, que é exatamente o que o motor usa pra decidir. O que ela
não responde é "e a Serie A de 2019?" ou "e a liga da Turquia, que ninguém
coletou?". Esses números nunca entraram no banco e não vão entrar: coletar uma
temporada inteira custa uma requisição POR JOGO (380 numa liga de pontos
corridos) e ocupa espaço pra alimentar uma tela de consulta, não o motor.

Então aqui a leitura é ao vivo e descartável. Nada deste módulo escreve no
banco. O cache é de memória e morre junto com o processo.

O QUE DÁ E O QUE NÃO DÁ, medido na API em 2026-08-21:

  `/fixtures?league&season`  devolve os 380 jogos da temporada inteira em UMA
  requisição, sem paginação, com placar final e do intervalo. É daqui que sai
  tudo que esta tela mostra por time e por recorte (todos/casa/fora): gols,
  aproveitamento, clean sheet, BTTS, over, forma.

  `/teams/statistics`        1 requisição por time. Acrescenta cartão por faixa
  de minuto, que o endpoint de fixtures não traz.

  Escanteio, falta, finalização e posse NÃO existem em nenhum dos dois. Só em
  `/fixtures/statistics`, que é 1 requisição por jogo. Por isso esta tela não
  promete esses mercados: melhor não ter a coluna do que ter a coluna vazia.
"""

import logging
import os
import time
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query

from auth_utils import require_vip
from database import get_connection
import api_quota

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/explorer", tags=["explorer"])

BASE_URL = "https://v3.football.api-sports.io"
FINALIZADOS = {"FT", "AET", "PEN"}

# TTL por tipo de dado, e não um número só.
#
# Catálogo de liga e lista de temporada mudam uma vez por ano; o placar de uma
# temporada em andamento muda toda rodada. Um TTL único ou desperdiçaria cota
# relendo o catálogo, ou mostraria a rodada de ontem por um dia inteiro.
TTL_CATALOGO  = 24 * 3600
TTL_TEMPORADA = 3600
TTL_TIME      = 6 * 3600

_cache: dict[str, tuple[float, object]] = {}

# País em português, com o nome original como reserva.
#
# A API responde em inglês e o site é todo em português. Traduzir no servidor
# em vez de na tela porque o nome aparece em três lugares (busca, cabeçalho da
# liga e detalhe) e três cópias da mesma tabela divergem na primeira correção.
# A lista cobre o que a busca alcança na prática; o que faltar aparece em
# inglês, que é melhor que aparecer vazio.
_PAISES = {
    "Argentina": "Argentina", "Australia": "Austrália", "Austria": "Áustria",
    "Belgium": "Bélgica", "Bolivia": "Bolívia", "Brazil": "Brasil",
    "Canada": "Canadá", "Chile": "Chile", "China": "China", "Colombia": "Colômbia",
    "Costa-Rica": "Costa Rica", "Croatia": "Croácia", "Czech-Republic": "Tchéquia",
    "Denmark": "Dinamarca", "Ecuador": "Equador", "Egypt": "Egito",
    "England": "Inglaterra", "France": "França", "Germany": "Alemanha",
    "Greece": "Grécia", "Italy": "Itália", "Japan": "Japão", "Mexico": "México",
    "Morocco": "Marrocos", "Netherlands": "Holanda", "Northern-Ireland": "Irlanda do Norte",
    "Norway": "Noruega", "Paraguay": "Paraguai", "Peru": "Peru", "Poland": "Polônia",
    "Portugal": "Portugal", "Romania": "Romênia", "Russia": "Rússia",
    "Saudi-Arabia": "Arábia Saudita", "Scotland": "Escócia", "Serbia": "Sérvia",
    "South-Africa": "África do Sul", "South-Korea": "Coreia do Sul",
    "Spain": "Espanha", "Sweden": "Suécia", "Switzerland": "Suíça",
    "Turkey": "Turquia", "Ukraine": "Ucrânia", "Uruguay": "Uruguai",
    "USA": "Estados Unidos", "Venezuela": "Venezuela", "Wales": "País de Gales",
    "World": "Internacional",
}


def _pais_pt(nome: Optional[str]) -> Optional[str]:
    if not nome:
        return None
    return _PAISES.get(nome, nome)


def _headers() -> dict:
    return {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}


def _get_cache(chave: str, ttl: int):
    item = _cache.get(chave)
    if item and time.time() - item[0] < ttl:
        return item[1]
    return None


def _set_cache(chave: str, valor):
    # Teto pra memória não crescer sem limite: cada temporada guardada é uma
    # lista de 380 jogos, e um usuário curioso abre dezenas delas numa sessão.
    # Ao estourar, joga fora a metade mais velha em vez de limpar tudo · limpar
    # tudo faria a próxima visita pagar cota de novo em TODAS as telas.
    # `>=` e não `>`: a poda tem que acontecer ANTES da inserção, senão o teto
    # de 200 é conferido com 200 itens dentro e o dicionário fecha com 201.
    if len(_cache) >= 200:
        for chave_velha in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
            _cache.pop(chave_velha, None)
    _cache[chave] = (time.time(), valor)
    return valor


def _api(caminho: str, params: dict) -> list:
    """Uma chamada à API-Football. Erro vira 502 com motivo, nunca lista vazia.

    Lista vazia e falha de rede são coisas diferentes e a tela precisa separar
    as duas: "esta temporada não tem jogo" pede um texto, "a API não respondeu"
    pede um botão de tentar de novo.
    """
    chave = os.getenv("API_FOOTBALL_KEY", "")
    if not chave:
        raise HTTPException(503, "Integração com a API de futebol não está configurada.")
    try:
        resp = requests.get(f"{BASE_URL}{caminho}", headers=_headers(), params=params, timeout=20)
        api_quota.registrar(getattr(resp, "headers", None), "explorar")
        resp.raise_for_status()
        corpo = resp.json()
    except Exception as e:
        logger.error("[EXPLORER] %s %s falhou: %s", caminho, params, e)
        raise HTTPException(502, "A fonte de dados não respondeu. Tente de novo em instantes.")

    erros = corpo.get("errors")
    # A API devolve 200 com `errors` preenchido quando a cota acaba ou o
    # parâmetro é inválido. Sem esta checagem isso chegaria na tela como
    # "nenhum resultado", que é a mentira mais cara possível aqui.
    if erros and (isinstance(erros, dict) and erros or isinstance(erros, list) and erros):
        detalhe = erros if isinstance(erros, list) else list(erros.values())
        logger.warning("[EXPLORER] %s devolveu erros: %s", caminho, detalhe)
        texto = str(detalhe[0]) if detalhe else "erro desconhecido"
        if "limit" in texto.lower() or "quota" in texto.lower():
            raise HTTPException(429, "A cota diária da fonte de dados acabou. Tente amanhã.")
        raise HTTPException(502, f"A fonte de dados recusou a consulta: {texto}")

    return corpo.get("response") or []


# ══════════════════════════════════════════════════════════════════════════
# CATÁLOGO DE LIGAS
# ══════════════════════════════════════════════════════════════════════════

@router.get("/ligas")
def listar_ligas(
    busca: Optional[str] = Query(None, min_length=0, max_length=60),
    current_user: dict = Depends(require_vip),
):
    """Ligas disponíveis pra explorar.

    Sem busca, devolve as ligas cadastradas no banco e NÃO gasta requisição:
    são as que a pessoa já conhece do resto do site, e servem de ponto de
    partida. A partir de 3 letras, pergunta o catálogo inteiro pra API.

    `no_banco` acompanha cada item porque a diferença importa pra quem lê: liga
    do banco tem histórico coletado e picks da IA, liga de fora tem só o que
    esta tela calcula na hora.
    """
    termo = (busca or "").strip()

    if len(termo) < 3:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT league_id, name, season, COALESCE(ativa, TRUE) AS ativa "
                "FROM leagues ORDER BY ativa DESC, name"
            )
            return [{
                "league_id":       r["league_id"],
                "nome":            r["name"],
                "pais":            None,
                "tipo":            None,
                "temporada_atual": r["season"],
                "no_banco":        True,
                "ativa":           r["ativa"],
            } for r in cur.fetchall()]
        finally:
            cur.close(); conn.close()

    chave = f"busca:{termo.lower()}"
    cacheado = _get_cache(chave, TTL_CATALOGO)
    if cacheado is not None:
        return cacheado

    itens = _api("/leagues", {"search": termo})

    ids_no_banco: set[int] = set()
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT league_id FROM leagues")
        ids_no_banco = {r["league_id"] for r in cur.fetchall()}
    finally:
        cur.close(); conn.close()

    ligas = []
    for item in itens:
        liga = item.get("league") or {}
        pais = item.get("country") or {}
        temporadas = item.get("seasons") or []
        atual = next((s.get("year") for s in temporadas if s.get("current")), None)
        if atual is None and temporadas:
            atual = temporadas[-1].get("year")
        ligas.append({
            "league_id":       liga.get("id"),
            "nome":            liga.get("name"),
            "pais":            _pais_pt(pais.get("name")),
            "tipo":            liga.get("type"),
            "temporada_atual": atual,
            "no_banco":        liga.get("id") in ids_no_banco,
            "ativa":           None,
        })

    # Quem está no banco primeiro: é o que a pessoa provavelmente procurava.
    ligas.sort(key=lambda l: (not l["no_banco"], l["nome"] or ""))
    return _set_cache(chave, ligas)


@router.get("/ligas/{league_id}/temporadas")
def listar_temporadas(league_id: int, current_user: dict = Depends(require_vip)):
    """Temporadas que a API tem dessa liga, da mais recente pra mais antiga.

    `tem_estatistica_por_jogo` vem do `coverage` da própria API e não é
    decoração: temporada antiga costuma ter só placar, e é ela que explica por
    que um ano devolve tabela cheia e o anterior devolve quase nada.
    """
    chave = f"temporadas:{league_id}"
    cacheado = _get_cache(chave, TTL_CATALOGO)
    if cacheado is not None:
        return cacheado

    itens = _api("/leagues", {"id": league_id})
    if not itens:
        raise HTTPException(404, f"Liga {league_id} não existe na fonte de dados.")

    item = itens[0]
    liga = item.get("league") or {}
    pais = item.get("country") or {}

    temporadas = []
    for s in item.get("seasons") or []:
        cobertura = s.get("coverage") or {}
        jogos = cobertura.get("fixtures") or {}
        temporadas.append({
            "ano":                      s.get("year"),
            "inicio":                   s.get("start"),
            "fim":                      s.get("end"),
            "atual":                    bool(s.get("current")),
            "tem_estatistica_por_jogo": bool(jogos.get("statistics_fixtures")),
        })
    temporadas.sort(key=lambda t: t["ano"] or 0, reverse=True)

    return _set_cache(chave, {
        "league_id":  liga.get("id"),
        "nome":       liga.get("name"),
        "pais":       _pais_pt(pais.get("name")),
        "tipo":       liga.get("type"),
        "logo":       liga.get("logo"),
        "temporadas": temporadas,
    })


# ══════════════════════════════════════════════════════════════════════════
# TEMPORADA: RESUMO E TABELA POR TIME
# ══════════════════════════════════════════════════════════════════════════

def _recorte_vazio() -> dict:
    return {
        "jogos": 0, "v": 0, "e": 0, "d": 0,
        "gols_pro": 0, "gols_contra": 0,
        "clean_sheet": 0, "sem_marcar": 0,
        "btts": 0, "over15": 0, "over25": 0, "over35": 0,
        "sem_gols": 0,
        # Primeiro tempo vem do `score.halftime`, que a mesma resposta ja'
        # traz. `jogos_ht` e' contado separado porque o intervalo vem nulo em
        # jogo antigo: dividir os gols de 1T pelo total de jogos faria a media
        # despencar em temporada mal coberta, sem sintoma nenhum.
        "jogos_ht": 0, "gols_1t": 0, "gols_2t": 0, "gol_no_1t": 0,
        "_resultados": [],
    }


def _fechar_recorte(r: dict) -> dict:
    """Transforma os contadores em médias e percentuais.

    Divisão sempre por `jogos`, e time sem jogo devolve zeros em vez de sumir
    da tabela: um time que ainda não jogou fora de casa é informação, e some
    justamente no recorte em que a pessoa foi olhar.
    """
    n = r["jogos"]
    nht = r["jogos_ht"]
    pct = lambda v: round(v / n * 100, 1) if n else 0.0
    media = lambda v: round(v / n, 2) if n else 0.0
    media_ht = lambda v: round(v / nht, 2) if nht else 0.0
    # Forma na ordem em que os jogos aconteceram, últimos cinco.
    forma = "".join(r["_resultados"][-5:])
    return {
        "jogos":              n,
        "v": r["v"], "e": r["e"], "d": r["d"],
        "gols_pro":           r["gols_pro"],
        "gols_contra":        r["gols_contra"],
        "media_gols_pro":     media(r["gols_pro"]),
        "media_gols_contra":  media(r["gols_contra"]),
        "media_gols_total":   media(r["gols_pro"] + r["gols_contra"]),
        "saldo":              r["gols_pro"] - r["gols_contra"],
        # Aproveitamento no formato do futebol brasileiro: pontos ganhos sobre
        # pontos disputados, e não vitórias sobre jogos.
        "aproveitamento_pct": round((r["v"] * 3 + r["e"]) / (n * 3) * 100, 1) if n else 0.0,
        "clean_sheet_pct":    pct(r["clean_sheet"]),
        "sem_marcar_pct":     pct(r["sem_marcar"]),
        "btts_pct":           pct(r["btts"]),
        "over15_pct":         pct(r["over15"]),
        "over25_pct":         pct(r["over25"]),
        "over35_pct":         pct(r["over35"]),
        "sem_gols_pct":       pct(r["sem_gols"]),
        # 1T e 2T do jogo inteiro (os dois lados somados), que e' a leitura de
        # quem olha mercado de tempo. O 2T sai por subtracao: a fonte da' o
        # placar do intervalo e o final, nunca o segundo tempo isolado.
        "media_gols_1t":      media_ht(r["gols_1t"]),
        "media_gols_2t":      media_ht(r["gols_2t"]),
        "gol_no_1t_pct":      round(r["gol_no_1t"] / nht * 100, 1) if nht else 0.0,
        "jogos_com_1t":       nht,
        "forma":              forma,
    }


def _contar(r: dict, gols_pro: int, gols_contra: int,
            ht_pro: Optional[int] = None, ht_contra: Optional[int] = None) -> None:
    r["jogos"] += 1
    r["gols_pro"] += gols_pro
    r["gols_contra"] += gols_contra
    if gols_pro > gols_contra:
        r["v"] += 1; r["_resultados"].append("V")
    elif gols_pro == gols_contra:
        r["e"] += 1; r["_resultados"].append("E")
    else:
        r["d"] += 1; r["_resultados"].append("D")
    if gols_contra == 0:
        r["clean_sheet"] += 1
    if gols_pro == 0:
        r["sem_marcar"] += 1
    if gols_pro > 0 and gols_contra > 0:
        r["btts"] += 1
    total = gols_pro + gols_contra
    if total == 0:
        r["sem_gols"] += 1
    if total >= 2: r["over15"] += 1
    if total >= 3: r["over25"] += 1
    if total >= 4: r["over35"] += 1
    if ht_pro is not None and ht_contra is not None:
        no_1t = ht_pro + ht_contra
        r["jogos_ht"] += 1
        r["gols_1t"] += no_1t
        # Segundo tempo por subtracao: a fonte da' o placar do INTERVALO e o
        # FINAL, nunca o segundo tempo isolado.
        r["gols_2t"] += total - no_1t
        if no_1t > 0:
            r["gol_no_1t"] += 1


@router.get("/ligas/{league_id}/temporadas/{season}")
def detalhe_temporada(league_id: int, season: int, current_user: dict = Depends(require_vip)):
    """Resumo da temporada e tabela por time, nos três recortes.

    UMA requisição à API pra qualquer liga e qualquer ano. O trabalho todo é
    somar em Python os jogos finalizados; a API entrega a temporada inteira de
    uma vez e não há nada pra paginar.
    """
    if season < 2000 or season > 2100:
        raise HTTPException(400, "Temporada fora do intervalo aceito.")

    chave = f"temporada:{league_id}:{season}"
    cacheado = _get_cache(chave, TTL_TEMPORADA)
    if cacheado is not None:
        return cacheado

    jogos = _api("/fixtures", {"league": league_id, "season": season})

    liga_info: dict = {}
    times: dict[int, dict] = {}
    total_jogos = len(jogos)
    finalizados = 0
    gols_casa = gols_fora = 0
    btts = over15 = over25 = over35 = sem_gols = 0
    vit_casa = empates = vit_fora = 0
    jogos_ht = gols_1t = gols_2t = gol_no_1t = 0
    placares: dict[str, int] = {}

    # Ordem cronológica antes de somar: a "forma" é os últimos cinco jogos, e a
    # API não garante ordem nenhuma na resposta.
    jogos = sorted(jogos, key=lambda j: (j.get("fixture") or {}).get("date") or "")

    for j in jogos:
        fixture = j.get("fixture") or {}
        if not liga_info:
            liga_info = j.get("league") or {}
        if (fixture.get("status") or {}).get("short") not in FINALIZADOS:
            continue

        equipes = j.get("teams") or {}
        casa = equipes.get("home") or {}
        fora = equipes.get("away") or {}
        placar = j.get("goals") or {}
        gc, gf = placar.get("home"), placar.get("away")
        if gc is None or gf is None or casa.get("id") is None or fora.get("id") is None:
            continue

        intervalo = (j.get("score") or {}).get("halftime") or {}
        hc, hf = intervalo.get("home"), intervalo.get("away")
        tem_ht = hc is not None and hf is not None

        finalizados += 1
        gols_casa += gc
        gols_fora += gf
        total_do_jogo = gc + gf
        if gc > 0 and gf > 0: btts += 1
        if total_do_jogo == 0: sem_gols += 1
        if total_do_jogo >= 2: over15 += 1
        if total_do_jogo >= 3: over25 += 1
        if total_do_jogo >= 4: over35 += 1
        if gc > gf: vit_casa += 1
        elif gc == gf: empates += 1
        else: vit_fora += 1
        if tem_ht:
            jogos_ht += 1
            gols_1t += hc + hf
            gols_2t += total_do_jogo - (hc + hf)
            if hc + hf > 0: gol_no_1t += 1
        # Placar visto do MANDANTE sempre ("2-1" e "1-2" sao coisas
        # diferentes), que e' como quem aposta le resultado exato.
        placares[f"{gc}-{gf}"] = placares.get(f"{gc}-{gf}", 0) + 1

        for time_info, recorte, pro, contra, ht_pro, ht_contra in (
            (casa, "casa", gc, gf, hc if tem_ht else None, hf if tem_ht else None),
            (fora, "fora", gf, gc, hf if tem_ht else None, hc if tem_ht else None),
        ):
            tid = time_info["id"]
            if tid not in times:
                times[tid] = {
                    "team_id": tid,
                    "nome":    time_info.get("name"),
                    "logo":    time_info.get("logo"),
                    "todos":   _recorte_vazio(),
                    "casa":    _recorte_vazio(),
                    "fora":    _recorte_vazio(),
                }
            _contar(times[tid][recorte], pro, contra, ht_pro, ht_contra)
            _contar(times[tid]["todos"], pro, contra, ht_pro, ht_contra)

    n = finalizados
    pct = lambda v: round(v / n * 100, 1) if n else 0.0
    resultado = {
        "liga": {
            "league_id": liga_info.get("id", league_id),
            "nome":      liga_info.get("name"),
            "pais":      _pais_pt(liga_info.get("country")),
            "logo":      liga_info.get("logo"),
        },
        "temporada": season,
        "resumo": {
            "jogos_total":        total_jogos,
            "jogos_finalizados":  n,
            "media_gols":         round((gols_casa + gols_fora) / n, 2) if n else 0.0,
            "media_gols_casa":    round(gols_casa / n, 2) if n else 0.0,
            "media_gols_fora":    round(gols_fora / n, 2) if n else 0.0,
            "btts_pct":           pct(btts),
            "over15_pct":         pct(over15),
            "over25_pct":         pct(over25),
            "over35_pct":         pct(over35),
            "sem_gols_pct":       pct(sem_gols),
            "vitoria_casa_pct":   pct(vit_casa),
            "empate_pct":         pct(empates),
            "vitoria_fora_pct":   pct(vit_fora),
            # Divididos por `jogos_ht`, nunca pelo total: temporada antiga vem
            # com o intervalo nulo em parte dos jogos, e dividir pelo total
            # afundaria a media sem ninguem perceber.
            "jogos_com_1t":       jogos_ht,
            "media_gols_1t":      round(gols_1t / jogos_ht, 2) if jogos_ht else 0.0,
            "media_gols_2t":      round(gols_2t / jogos_ht, 2) if jogos_ht else 0.0,
            "gol_no_1t_pct":      round(gol_no_1t / jogos_ht * 100, 1) if jogos_ht else 0.0,
            "placares_comuns":    [
                {"placar": p, "jogos": q, "pct": round(q / n * 100, 1)}
                for p, q in sorted(placares.items(), key=lambda kv: -kv[1])[:5]
            ] if n else [],
        },
        "times": sorted(
            [{
                "team_id": t["team_id"], "nome": t["nome"], "logo": t["logo"],
                "todos": _fechar_recorte(t["todos"]),
                "casa":  _fechar_recorte(t["casa"]),
                "fora":  _fechar_recorte(t["fora"]),
            } for t in times.values()],
            key=lambda t: t["nome"] or "",
        ),
    }
    return _set_cache(chave, resultado)


# ══════════════════════════════════════════════════════════════════════════
# TIME: CARTÕES E FORMA
# ══════════════════════════════════════════════════════════════════════════

@router.get("/times/{team_id}")
def detalhe_time(
    team_id: int,
    league_id: int = Query(..., ge=1),
    season: int = Query(..., ge=2000, le=2100),
    current_user: dict = Depends(require_vip),
):
    """Cartão por faixa de minuto e forma longa do time naquela liga/temporada.

    Uma requisição, e só quando alguém abre o time · é o único dado desta tela
    que escala com o número de cliques, então não vem junto com a tabela.
    """
    chave = f"time:{team_id}:{league_id}:{season}"
    cacheado = _get_cache(chave, TTL_TIME)
    if cacheado is not None:
        return cacheado

    resp = _api("/teams/statistics", {"team": team_id, "league": league_id, "season": season})
    # Este endpoint devolve objeto, não lista. `_api` normaliza pra lista vazia
    # quando não há resposta, então um dict vem direto.
    dados = resp if isinstance(resp, dict) else (resp[0] if resp else {})
    if not dados:
        raise HTTPException(404, "A fonte não tem estatística desse time nessa temporada.")

    time_info = dados.get("team") or {}
    jogados = ((dados.get("fixtures") or {}).get("played") or {})
    total_jogos = jogados.get("total") or 0

    # A API escreve a forma em inglês (WDL) e a tabela desta mesma tela escreve
    # em português (VED). Traduzir aqui, e não na tela, evita o pior caso: "D"
    # significa empate num alfabeto e derrota no outro, e a mesma letra com dois
    # sentidos na mesma página seria lida errado sem ninguém desconfiar.
    forma_pt = "".join({"W": "V", "D": "E", "L": "D"}.get(c, c)
                       for c in (dados.get("form") or ""))

    def faixas(cor: str) -> dict:
        bruto = (dados.get("cards") or {}).get(cor) or {}
        linhas, soma = [], 0
        for faixa, valores in bruto.items():
            # A API devolve uma chave de faixa vazia ("") junto das reais.
            if not faixa or not isinstance(valores, dict):
                continue
            qtd = valores.get("total") or 0
            soma += qtd
            linhas.append({"faixa": faixa, "total": qtd})
        return {
            "total":    soma,
            "por_jogo": round(soma / total_jogos, 2) if total_jogos else 0.0,
            "faixas":   linhas,
        }

    def gols_por_faixa(lado: str) -> list:
        """Em que altura do jogo o time marca (ou leva).

        Mesma resposta, campo diferente · nao custa requisicao nenhuma. Diz
        coisa que a media nao diz: dois times de 1.7 gol por jogo, um que
        resolve cedo e outro que decide no fim, sao apostas diferentes.
        """
        bruto = ((dados.get("goals") or {}).get(lado) or {}).get("minute") or {}
        linhas = []
        for faixa, valores in bruto.items():
            if not faixa or not isinstance(valores, dict):
                continue
            linhas.append({"faixa": faixa, "total": valores.get("total") or 0})
        return linhas

    maiores = dados.get("biggest") or {}
    sequencia = maiores.get("streak") or {}
    penaltis = dados.get("penalty") or {}

    resultado = {
        "team_id": time_info.get("id", team_id),
        "nome":    time_info.get("name"),
        "logo":    time_info.get("logo"),
        "forma":   forma_pt,
        "jogos":   {
            "todos": total_jogos,
            "casa":  jogados.get("home") or 0,
            "fora":  jogados.get("away") or 0,
        },
        "cartoes": {
            "amarelo":  faixas("yellow"),
            "vermelho": faixas("red"),
        },
        "gols_por_faixa": {
            "marcados": gols_por_faixa("for"),
            "sofridos": gols_por_faixa("against"),
        },
        "sequencias": {
            "vitorias": sequencia.get("wins") or 0,
            "empates":  sequencia.get("draws") or 0,
            "derrotas": sequencia.get("loses") or 0,
        },
        "maiores": {
            "vitoria_casa": (maiores.get("wins") or {}).get("home"),
            "vitoria_fora": (maiores.get("wins") or {}).get("away"),
            "derrota_casa": (maiores.get("loses") or {}).get("home"),
            "derrota_fora": (maiores.get("loses") or {}).get("away"),
        },
        "penaltis": {
            "cobrados":     penaltis.get("total") or 0,
            "convertidos":  ((penaltis.get("scored") or {}).get("total")) or 0,
            "perdidos":     ((penaltis.get("missed") or {}).get("total")) or 0,
        },
    }
    return _set_cache(chave, resultado)
