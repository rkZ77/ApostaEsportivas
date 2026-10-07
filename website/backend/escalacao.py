"""Escalação e desfalques de um jogo, pro campinho do Raio-X (2026-10-07).

PEDIDO DO USUÁRIO: a formação desenhada no campo, com os prováveis titulares,
virando "confirmada" (verde) quando a escalação oficial sai, e os desfalques
(lesionado, suspenso, dúvida) do jogo.

DE ONDE VEM CADA COISA
----------------------
  · OFICIAL   /fixtures/lineups da API-Football. Sai de 20 a 40 minutos antes
              do apito, com formação e a posição de cada jogador no campo
              (`grid` "linha:coluna"). Depois de publicada não muda: fica em
              memória e não é pedida de novo.
  · PROVÁVEL  enquanto a oficial não sai: a última escalação que cada time
              usou (`team_lineups`, coletada no histórico), com nome e posição
              da ficha do jogador (`player_match_stats`). Zero API.
  · DESFALQUES /injuries?fixture= da API-Football. Muda até a véspera, então
              tem cache curto (ver TTL_DESFALQUES).

Tudo aqui que é regra (ler a resposta, traduzir motivo, montar a provável) é
função pura e tem teste; as chamadas de rede ficam isoladas em `_api`.
"""
from __future__ import annotations

import logging
import os
import threading
import time

import requests

import api_quota

logger = logging.getLogger(__name__)

API_BASE = "https://v3.football.api-sports.io"

#: Desfalque muda até a véspera (o clube atualiza o boletim médico); escalação
#: não oficial não é pedida à API (vem do banco). 30 min segura o custo sem
#: deixar a lista velha.
TTL_DESFALQUES = 30 * 60
#: Escalação ainda não publicada: perguntar de novo a cada 10 minutos.
TTL_SEM_OFICIAL = 10 * 60

_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


def _do_cache(chave: str, ttl: float | None):
    with _lock:
        item = _cache.get(chave)
    if item and (ttl is None or time.time() - item[0] < ttl):
        return item[1], True
    return None, False


def _guardar(chave: str, valor) -> None:
    with _lock:
        if len(_cache) > 400:   # teto: cada jogo aberto ocupa duas entradas
            for k in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
                _cache.pop(k, None)
        _cache[chave] = (time.time(), valor)


def _api(caminho: str, params: dict) -> list | None:
    """GET na API-Football. None quando falhou (rede, chave, limite)."""
    chave = os.getenv("API_FOOTBALL_KEY", "")
    if not chave:
        return None
    try:
        r = requests.get(f"{API_BASE}/{caminho}", headers={"x-apisports-key": chave},
                         params=params, timeout=12)
        api_quota.registrar(r.headers, origem=f"raio-x {caminho}")
        if r.status_code != 200:
            return None
        return (r.json() or {}).get("response") or []
    except Exception as e:
        logger.warning("[ESCALACAO] %s %s: %s", caminho, params, e)
        return None


# ── leitura da resposta da API (puro) ───────────────────────────────────────

#: Posição curta do provedor -> a letra que o site usa.
_POS = {"G": "G", "D": "D", "M": "M", "F": "A"}


def ler_escalacao_oficial(resposta: list) -> dict:
    """/fixtures/lineups -> {team_id: time}. Time sem titular não conta (o
    provedor devolve o bloco vazio enquanto o clube não confirma)."""
    times = {}
    for item in resposta or []:
        team_id = (item.get("team") or {}).get("id")
        if not team_id:
            continue

        def jogadores(lista):
            saida = []
            for x in lista or []:
                p = (x or {}).get("player") or {}
                if not p.get("id"):
                    continue
                saida.append({
                    "player_id": p["id"], "nome": p.get("name") or "",
                    "numero": p.get("number"), "posicao": _POS.get(p.get("pos") or "", None),
                    "grid": p.get("grid"),
                })
            return saida

        titulares = jogadores(item.get("startXI"))
        if not titulares:
            continue
        times[team_id] = {
            "formacao": item.get("formation"),
            "tecnico": (item.get("coach") or {}).get("name"),
            "titulares": titulares,
            "reservas": jogadores(item.get("substitutes")),
        }
    return times


def motivo_em_portugues(tipo: str | None, motivo: str | None) -> tuple[str, str]:
    """(categoria, texto). Categoria decide o ícone: lesao, suspenso, duvida, outro."""
    t = (tipo or "").lower()
    m = (motivo or "").strip()
    ml = m.lower()
    if "suspend" in ml or "card" in ml:
        texto = "Suspenso" if "red" not in ml else "Suspenso (vermelho)"
        if "yellow" in ml:
            texto = "Suspenso (amarelos)"
        return "suspenso", texto
    if t == "questionable" or "doubt" in ml:
        return "duvida", "Dúvida" + (f" · {_traduz_lesao(ml)}" if "injur" in ml else "")
    if "injur" in ml or "knock" in ml or "surgery" in ml:
        return "lesao", _traduz_lesao(ml)
    if "illness" in ml or "virus" in ml:
        return "outro", "Doença"
    if "international" in ml:
        return "outro", "Seleção"
    if "personal" in ml or "family" in ml:
        return "outro", "Motivo pessoal"
    return "outro", m or "Fora do jogo"


_PARTES = [("knee", "joelho"), ("ankle", "tornozelo"), ("hamstring", "coxa"),
           ("thigh", "coxa"), ("muscle", "muscular"), ("groin", "virilha"),
           ("calf", "panturrilha"), ("foot", "pé"), ("back", "costas"),
           ("shoulder", "ombro"), ("head", "cabeça"), ("hip", "quadril"),
           ("achilles", "tendão de aquiles"), ("ligament", "ligamento")]


def _traduz_lesao(ml: str) -> str:
    for en, pt in _PARTES:
        if en in ml:
            return f"Lesão ({pt})" if pt != "muscular" else "Lesão muscular"
    return "Lesionado"


def ler_desfalques(resposta: list) -> dict:
    """/injuries -> {team_id: [desfalque]}, sem repetir jogador."""
    times: dict[int, list] = {}
    vistos = set()
    for item in resposta or []:
        p = item.get("player") or {}
        team_id = (item.get("team") or {}).get("id")
        if not p.get("id") or not team_id or (team_id, p["id"]) in vistos:
            continue
        vistos.add((team_id, p["id"]))
        categoria, texto = motivo_em_portugues(p.get("type"), p.get("reason"))
        times.setdefault(team_id, []).append({
            "player_id": p["id"], "nome": p.get("name") or "",
            "categoria": categoria, "motivo": texto,
        })
    return times


def montar_provavel(titulares_ids: list, formacao: str | None, fichas: dict) -> dict:
    """A provável a partir da última escalação: nome e posição pela ficha.

    `fichas`: {player_id: {"nome", "posicao", "numero"?}}. Sem `grid` (o banco
    não guarda a posição no campo); quem desenha distribui pelas linhas da
    formação, por posição.
    """
    titulares = []
    for pid in titulares_ids or []:
        f = fichas.get(pid) or {}
        pos = (f.get("posicao") or "")[:1].upper() or None
        titulares.append({"player_id": pid, "nome": f.get("nome") or "",
                          "numero": f.get("numero"), "posicao": _POS.get(pos, pos),
                          "grid": None})
    return {"formacao": formacao, "tecnico": None, "titulares": titulares, "reservas": []}


# ── montagem com banco e API ───────────────────────────────────────────────


def _provavel_do_banco(cur, team_id: int, fixture_id: int) -> dict | None:
    cur.execute("""
        SELECT titulares, formation FROM team_lineups
         WHERE team_id = %s AND fixture_id <> %s AND cardinality(titulares) > 0
         ORDER BY match_date DESC LIMIT 1
    """, (team_id, fixture_id))
    linha = cur.fetchone()
    if not linha:
        return None
    ids = list(linha["titulares"])
    cur.execute("""
        SELECT DISTINCT ON (player_id) player_id, player_name, position
          FROM player_match_stats
         WHERE player_id = ANY(%s)
         ORDER BY player_id, match_date DESC
    """, (ids,))
    fichas = {r["player_id"]: {"nome": r["player_name"], "posicao": r["position"]}
              for r in cur.fetchall()}
    return montar_provavel(ids, linha["formation"], fichas)


def escalacao_do_jogo(cur, fixture_id: int, home_id: int, away_id: int) -> dict:
    """O que o campinho mostra. Nunca levanta: sem dado, devolve o vazio."""
    # Oficial: uma vez publicada, fica pra sempre (ttl None).
    oficial, achou = _do_cache(f"oficial:{fixture_id}", None)
    if not achou:
        oficial, achou = _do_cache(f"sem_oficial:{fixture_id}", TTL_SEM_OFICIAL)
        if not achou:
            resposta = _api("fixtures/lineups", {"fixture": fixture_id})
            oficial = ler_escalacao_oficial(resposta) if resposta is not None else {}
            completa = home_id in oficial and away_id in oficial
            _guardar(f"{'oficial' if completa else 'sem_oficial'}:{fixture_id}", oficial)

    desfalques, achou = _do_cache(f"desfalques:{fixture_id}", TTL_DESFALQUES)
    if not achou:
        resposta = _api("injuries", {"fixture": fixture_id})
        desfalques = ler_desfalques(resposta) if resposta is not None else {}
        if resposta is not None:
            _guardar(f"desfalques:{fixture_id}", desfalques)

    times = {}
    for lado, tid in (("home", home_id), ("away", away_id)):
        if tid in (oficial or {}):
            times[lado] = {**oficial[tid], "status": "oficial"}
            continue
        try:
            prov = _provavel_do_banco(cur, tid, fixture_id)
        except Exception:
            logger.warning("[ESCALACAO] provavel do time %s falhou", tid, exc_info=True)
            try:
                cur.connection.rollback()
            except Exception:
                pass
            prov = None
        times[lado] = {**prov, "status": "provavel"} if prov else {"status": "indisponivel"}

        # Titular provável que está no boletim médico: a tela marca.
        fora = {d["player_id"] for d in (desfalques or {}).get(tid, [])}
        for j in times[lado].get("titulares", []):
            j["desfalque"] = j["player_id"] in fora

    return {
        "times": times,
        "desfalques": {"home": (desfalques or {}).get(home_id, []),
                       "away": (desfalques or {}).get(away_id, [])},
    }
