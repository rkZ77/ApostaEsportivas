"""A linha ainda existe, e ainda vale, no momento de publicar? (2026-10-08)

POR QUE EXISTE
--------------
O motor decide sobre as odds que estavam no banco quando a rodada comecou.
Entre a coleta e o INSERT do pick passam minutos (rodada com muitos jogos e
revisao de IA) ou horas (rodada disparada a mao). Nesse intervalo a casa pode
mexer no preco ou tirar a linha do ar -- e a coleta faz upsert, entao a linha
retirada continua no banco com o carimbo antigo. Ate' aqui o pick saia mesmo
assim: anunciado a uma odd que nao existia mais.

O QUE FAZ
---------
1. Atualiza as odds DAQUELA partida na API (OddsCollectorService.
   process_fixture_odds, o mesmo caminho da coleta; grava tambem o retrato
   em odds_snapshots). Uma vez por partida por rodada (memo de 10 min).
2. Rele so' as cotacoes atualizadas nessa passada (`max_idade_seg`). Linha que
   nenhuma casa cotou agora nao aparece -- e' "fora do ar".
3. Confere: a linha existe, tem casas suficientes, a odd de avaliacao esta' na
   faixa do pipeline e o EV, RECALCULADO com a odd de agora e a probabilidade
   que o motor publicaria, continua positivo. Edge contra o no-vig de agora.
4. Atualiza odd/EV/edge/casa do pick pros numeros de agora.

FALHA DA API
------------
Sem resposta da API (rede, cota) a conferencia cai pro banco, com a idade
maxima de `config.max_idade_odd_publicacao_seg`. Linha mais velha que isso nao
publica. E' o lado seguro: pick sem linha confirmada nao sai.

`MOTOR_REVALIDAR_ODD`: api (padrao) | banco (nao chama a API) | off.
"""
from __future__ import annotations

import os
import time

from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG

_ATUALIZADAS: dict = {}       # fixture_id -> (time.time() do inicio, duracao)
_MEMO_SEG = 600


def modo() -> str:
    m = os.getenv("MOTOR_REVALIDAR_ODD", "api").strip().lower()
    return m if m in ("api", "banco", "off") else "api"


def _atualizar_na_api(fixture_id: int, coletor=None) -> tuple:
    """(janela em segundos que cobre a passada, falha ou None)."""
    agora = time.time()
    feito = _ATUALIZADAS.get(fixture_id)
    if feito and agora - feito[0] < _MEMO_SEG:
        return int(agora - feito[0]) + 5, None
    try:
        if coletor is None:
            from collectors.odds_collector_service import OddsCollectorService
            from services import api_quota
            coletor = OddsCollectorService()
            # Uma requisicao por casa ativa. Sem folga de cota, confere no
            # banco (com a idade maxima) em vez de raspar o que a liquidacao
            # do dia precisa.
            if not api_quota.pode_gastar(len(coletor.casas)):
                return None, "cota do dia sem folga"
        coletor.process_fixture_odds(fixture_id)
    except Exception as e:
        return None, str(e)[:200]
    _ATUALIZADAS[fixture_id] = (agora, time.time() - agora)
    # +5s de folga entre o relogio deste processo e o NOW() do banco.
    return int(time.time() - agora) + 5, None


def _mesma_linha(entry: dict, pick: dict) -> bool:
    rot = (pick.get("value_label") or "").strip().lower()
    return (entry.get("market_id") == pick.get("market_id")
            and (entry.get("value_label") or "").strip().lower() == rot)


def revalidar(pick: dict, fixture_id: int, config: PickEngineConfig = DEFAULT_CONFIG,
              odds_service=None, coletor=None) -> dict:
    """{"ok", "motivo", "fonte", "odd_antes", "odd_agora", "ev_agora", ...}.

    Nunca levanta: erro inesperado vira ok=False com o motivo.
    """
    m = modo()
    if m == "off":
        return {"ok": True, "fonte": "off"}
    from services.pick_engine import market_model, ranking
    from services.pick_engine.orchestrator import _find_sibling

    saida = {"odd_antes": pick.get("odd"), "fonte": "banco"}
    janela, falha = (None, None)
    if m == "api":
        janela, falha = _atualizar_na_api(fixture_id, coletor)
        if janela is not None:
            saida["fonte"] = "api"
        else:
            saida["falha_api"] = falha
    if janela is None:
        janela = config.max_idade_odd_publicacao_seg
    try:
        if odds_service is None:
            from services.odds_service import OddsService
            odds_service = OddsService()
        linhas = odds_service.load_odds_structured(fixture_id, max_idade_seg=janela)
    except Exception as e:
        return {**saida, "ok": False, "motivo": f"nao consegui reler as odds: {str(e)[:160]}"}

    entry = next((e for e in linhas or [] if _mesma_linha(e, pick)), None)
    if entry is None:
        return {**saida, "ok": False,
                "motivo": (f"linha {pick.get('value_label')} nao esta' mais cotada "
                           f"({'na API agora' if saida['fonte'] == 'api' else f'nas ultimas {janela // 3600}h'})")}
    if entry.get("bookmakers_count", 1) < config.min_bookmakers_count:
        return {**saida, "ok": False,
                "motivo": f"so' {entry.get('bookmakers_count')} casa(s) cotam a linha agora"}
    odd = market_model.evaluation_odd(entry, config)
    fora = ranking.motivo_de_odd_fora(odd, config)
    if fora:
        return {**saida, "ok": False, "odd_agora": odd, "motivo": f"odd de agora {fora}"}
    sibling = _find_sibling(entry, linhas)
    baseline = market_model.resolve_prob_baseline(entry, sibling, config)["prob"]
    p = pick.get("taxa_real")
    if p is None:
        return {**saida, "ok": False, "motivo": "pick sem probabilidade"}
    # A aprovacao olha a probabilidade MAIS CONSERVADORA do pick (a regra de
    # ranking._valores_de_aprovacao): o preco novo nao pode aprovar pelo
    # numero que o contexto nao deixou decidir.
    p_aprov, _ = ranking._valores_de_aprovacao({**pick, "ev": p * odd - 1})
    ev_aprov = round(p_aprov * odd - 1, 4)
    if ev_aprov <= config.min_ev:
        return {**saida, "ok": False, "odd_agora": odd,
                "motivo": f"EV deixou de ser positivo com a odd de agora ({ev_aprov:+.1%})"}
    return {**saida, "ok": True, "odd_agora": odd,
            "melhor_odd_agora": entry.get("best_odd"),
            "casa_agora": entry.get("best_bookmaker"),
            "casas_agora": entry.get("bookmakers_count"),
            "ev_agora": round(p * odd - 1, 4), "edge_agora": round(p - baseline, 4),
            "prob_mercado_agora": baseline,
            "bookmaker_odds": entry.get("bookmaker_odds") or []}


def pernas_ok(pernas: list, config: PickEngineConfig = DEFAULT_CONFIG,
              rotulo: str = "MOTOR", **kw) -> list | None:
    """Bilhete: TODA perna precisa continuar cotada e com EV positivo na odd
    de agora; uma que falhe derruba o bilhete. Os numeros do bilhete (odd
    total, casa unica, probabilidade conjunta) NAO sao recompostos aqui --
    isso e' a montagem inteira de novo; o que se garante e' que nenhuma perna
    publicada esteja fora do ar ou sem valor. Devolve as pernas anotadas com
    `revalidacao`, ou None."""
    anotadas = []
    for p in pernas or []:
        fid = p.get("fixture_id") or (p.get("_fixture") or {}).get("fixture_id")
        if not fid:
            anotadas.append(p)
            continue
        r = revalidar(p, fid, config, **kw)
        if not r.get("ok"):
            print(f"[{rotulo}] Bilhete descartado na revalidacao: fixture {fid} "
                  f"{p.get('market_name')} {p.get('value_label')} -- {r.get('motivo')}")
            return None
        anotadas.append({**p, "revalidacao": r})
    return anotadas


def aplicar(pick: dict, fixture_id: int, config: PickEngineConfig = DEFAULT_CONFIG,
            rotulo: str = "MOTOR", **kw) -> dict | None:
    """O pick com os numeros de agora, ou None quando nao pode sair."""
    r = revalidar(pick, fixture_id, config, **kw)
    if not r.get("ok"):
        print(f"[{rotulo}] Fixture {fixture_id}: pick NAO publicado na revalidacao "
              f"-- {r.get('motivo')}")
        return None
    if r.get("fonte") == "off":
        return {**pick, "revalidacao": r}
    novo = {**pick, "revalidacao": r, "odd": r["odd_agora"], "ev": r["ev_agora"],
            "edge": r["edge_agora"]}
    if r.get("casa_agora"):
        novo["best_bookmaker"] = r["casa_agora"]
        novo["melhor_odd"] = r.get("melhor_odd_agora")
        novo["bookmaker_odds"] = r.get("bookmaker_odds") or pick.get("bookmaker_odds")
    if r["odd_agora"] != r.get("odd_antes"):
        print(f"[{rotulo}] Fixture {fixture_id}: odd revalidada {r.get('odd_antes')} -> "
              f"{r['odd_agora']} (EV {r['ev_agora']:+.1%}, fonte {r['fonte']})")
    return novo
