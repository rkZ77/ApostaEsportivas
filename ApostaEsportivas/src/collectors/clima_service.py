"""Clima e altitude de cada partida (2026-09-27).

POR QUE EXISTE
--------------
Pedido do usuario: o motor tem que enxergar o que o mercado padrao nao olha.
Chuva forte e vento mudam o jogo (bola parada, chute de longe, passe longo);
altitude muda o ritmo (La Paz a 3.600 m, Quito a 2.800 m, Bogota a 2.600 m,
todos em competicao que as ligas acompanhadas disputam). Nada disso estava no
banco.

FONTE
-----
Open-Meteo, gratis e sem chave. Tres servicos:
  geocoding  cidade -> latitude, longitude e ALTITUDE (cacheado por cidade)
  archive    clima de hora em hora do passado (reanalise; ~5 dias de atraso)
  forecast   previsao pros jogos de hoje e dos proximos dias

Nao gasta cota da API-Football. A cidade vem de `calendario_jogos.venue_city`
(a resposta de /fixtures traz o estadio), e o pais da liga desambigua nome
repetido ("Santos", "Victoria").

O que se grava e' o clima NA HORA DO APITO (a hora mais proxima do inicio).

APROXIMACAO CONHECIDA: a cidade vem escrita pela API-Football, com erro as
vezes ("Monterey" pra Monterrey, medido em 27/09: o geocoding achou outra
cidade, a 8 m em vez de ~540 m). Cidade que nao se acha fica sem clima; cidade
achada errada fica com o clima de outro lugar. Por isso o dado e' contexto e
medicao, nao termo de probabilidade, ate' ser medido.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import requests

from utils.db_utils import get_connection

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = 20

#: Pais da liga (como a API-Football escreve) -> codigo ISO do Open-Meteo.
PAIS_ISO = {
    "Brazil": "BR", "Argentina": "AR", "England": "GB", "Spain": "ES", "Italy": "IT",
    "Germany": "DE", "France": "FR", "Portugal": "PT", "Netherlands": "NL", "Colombia": "CO",
    "Chile": "CL", "Uruguay": "UY", "Paraguay": "PY", "Ecuador": "EC", "Peru": "PE",
    "Bolivia": "BO", "Venezuela": "VE", "Mexico": "MX", "USA": "US", "Belgium": "BE",
    "Turkey": "TR", "Scotland": "GB", "Saudi-Arabia": "SA",
}

DDL = (
    """CREATE TABLE IF NOT EXISTS geocode_cidades (
        chave        TEXT PRIMARY KEY,
        latitude     DOUBLE PRECISION,
        longitude    DOUBLE PRECISION,
        altitude_m   DOUBLE PRECISION,
        encontrada   BOOLEAN NOT NULL DEFAULT TRUE,
        atualizado_em TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS clima_partida (
        fixture_id      INTEGER PRIMARY KEY,
        venue_city      TEXT,
        altitude_m      DOUBLE PRECISION,
        temperatura_c   DOUBLE PRECISION,
        chuva_mm        DOUBLE PRECISION,
        vento_kmh       DOUBLE PRECISION,
        fonte           TEXT,
        coletado_em     TIMESTAMP DEFAULT NOW()
    )""",
)


def _chave(cidade: str, iso: str | None) -> str:
    return f"{(cidade or '').strip().lower()}|{iso or ''}"


def geocodificar(cur, cidade: str, iso: str | None) -> tuple | None:
    """(lat, lon, altitude) da cidade, com cache. Nome com parenteses ou
    virgula ("Rio de Janeiro, RJ") usa so' a primeira parte."""
    if not cidade:
        return None
    chave = _chave(cidade, iso)
    cur.execute("SELECT latitude, longitude, altitude_m, encontrada FROM geocode_cidades WHERE chave = %s",
                (chave,))
    linha = cur.fetchone()
    if linha:
        return tuple(linha[:3]) if linha[3] else None
    nome = cidade.split(",")[0].split("(")[0].strip()
    params = {"name": nome, "count": 5, "language": "pt"}
    if iso:
        params["country_code"] = iso
    try:
        r = requests.get(GEOCODE, params=params, timeout=_TIMEOUT).json()
    except Exception as e:
        print(f"[CLIMA] geocoding {cidade}: {e}")
        return None
    resultados = r.get("results") or []
    # Entre homonimos, a cidade mais populosa e' a que tem estadio.
    melhor = max(resultados, key=lambda x: x.get("population") or 0) if resultados else None
    if melhor:
        valores = (melhor["latitude"], melhor["longitude"], melhor.get("elevation"))
        cur.execute("""INSERT INTO geocode_cidades (chave, latitude, longitude, altitude_m)
                       VALUES (%s,%s,%s,%s) ON CONFLICT (chave) DO NOTHING""", (chave, *valores))
        return valores
    cur.execute("INSERT INTO geocode_cidades (chave, encontrada) VALUES (%s, FALSE) "
                "ON CONFLICT (chave) DO NOTHING", (chave,))
    return None


def _clima_na_hora(lat, lon, quando: datetime) -> tuple | None:
    """(temperatura, chuva, vento, fonte) na hora mais proxima do apito."""
    dia = quando.date()
    arquivo = dia <= date.today() - timedelta(days=5)
    url = ARCHIVE if arquivo else FORECAST
    params = {"latitude": lat, "longitude": lon,
              "hourly": "temperature_2m,precipitation,wind_speed_10m",
              "timezone": "America/Sao_Paulo",
              "start_date": dia.isoformat(), "end_date": dia.isoformat()}
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT).json()
    except Exception as e:
        print(f"[CLIMA] {url}: {e}")
        return None
    h = r.get("hourly") or {}
    horas = h.get("time") or []
    if not horas:
        return None
    alvo = quando.replace(minute=0, second=0, microsecond=0).isoformat(timespec="minutes")
    i = horas.index(alvo) if alvo in horas else min(
        range(len(horas)), key=lambda k: abs(datetime.fromisoformat(horas[k]) - quando))
    return (h["temperature_2m"][i], h["precipitation"][i], h["wind_speed_10m"][i],
            "archive" if arquivo else "forecast")


def coletar(teto: int = 500, dias_a_frente: int = 3) -> dict:
    """Clima das partidas do calendario sem clima: as que ja' aconteceram
    (arquivo) e as dos proximos `dias_a_frente` dias (previsao). Previsao e'
    regravada a cada passada, porque melhora perto do jogo."""
    conn = get_connection()
    cur = conn.cursor()
    feitas = sem = 0
    try:
        for sql in DDL:
            cur.execute(sql)
        conn.commit()
        cur.execute("""
            SELECT c.fixture_id, c.venue_city, c.match_datetime, c.pais
              FROM calendario_jogos c
              LEFT JOIN clima_partida cp ON cp.fixture_id = c.fixture_id
             WHERE c.venue_city IS NOT NULL AND c.match_datetime IS NOT NULL
               AND c.match_datetime <= NOW() + (%s * INTERVAL '1 day')
               AND (cp.fixture_id IS NULL OR cp.fonte = 'forecast')
             ORDER BY c.match_datetime DESC
             LIMIT %s
        """, (dias_a_frente, teto))
        for fixture_id, cidade, quando, pais in cur.fetchall():
            geo = geocodificar(cur, cidade, PAIS_ISO.get(pais or ""))
            if not geo:
                sem += 1
                continue
            lat, lon, alt = geo
            clima = _clima_na_hora(lat, lon, quando)
            if not clima:
                sem += 1
                continue
            cur.execute("""
                INSERT INTO clima_partida (fixture_id, venue_city, altitude_m, temperatura_c,
                                           chuva_mm, vento_kmh, fonte)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (fixture_id) DO UPDATE SET
                    temperatura_c = EXCLUDED.temperatura_c, chuva_mm = EXCLUDED.chuva_mm,
                    vento_kmh = EXCLUDED.vento_kmh, fonte = EXCLUDED.fonte, coletado_em = NOW()
            """, (fixture_id, cidade, alt, *clima))
            conn.commit()
            feitas += 1
    finally:
        cur.close()
        conn.close()
    print(f"[CLIMA] {feitas} partida(s) com clima, {sem} sem cidade ou sem dado")
    return {"com_clima": feitas, "sem": sem}
