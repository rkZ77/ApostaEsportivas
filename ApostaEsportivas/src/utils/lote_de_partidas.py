"""Vinte partidas por requisicao (18/10/2026).

`/fixtures?ids=a-b-c` devolve, pra cada partida (ate' 20), o jogo com os
blocos `events`, `lineups`, `statistics` e `players` -- o mesmo conteudo de
`/fixtures/events`, `/fixtures/lineups`, etc., que custam uma requisicao POR
partida. Os coletores de historico (eventos, escalacao, jogador) pediam um por
um; com o lote o mesmo gasto de cota cobre 20 vezes mais partidas.

So' entra no resultado a partida que trouxe o bloco pedido como LISTA. A que
nao trouxe (formato inesperado, partida ausente da resposta) fica de fora e o
coletor cai no caminho antigo, uma por uma -- o lote nunca perde partida.
"""
from __future__ import annotations

from utils.api_client import buscar

IDS_POR_REQUISICAO = 20


def em_lotes(ids: list, tamanho: int = IDS_POR_REQUISICAO):
    for i in range(0, len(ids), tamanho):
        yield ids[i:i + tamanho]


def buscar_bloco(fixture_ids: list, bloco: str, origem: str) -> dict:
    """{fixture_id: lista do `bloco`} de ate' 20 partidas, numa requisicao.

    Erro de API sobe (inclusive `ApiQuotaEsgotada`): quem chama decide se
    encerra a rodada ou segue uma por uma."""
    if not fixture_ids:
        return {}
    resposta = buscar("fixtures", {"ids": "-".join(map(str, fixture_ids))}, origem=origem)
    saida = {}
    for item in resposta or []:
        fid = ((item or {}).get("fixture") or {}).get("id")
        if fid is not None and isinstance(item.get(bloco), list):
            saida[fid] = item[bloco]
    return saida


def percorrer(fixture_ids: list, bloco: str, avulsa, teto_requisicoes: int, origem: str):
    """Gera (fixture_id, lista do bloco) pra fila inteira, em lotes de 20.

    `avulsa(fixture_id)` e' o caminho antigo (uma requisicao), usado so' pra
    partida que o lote nao trouxe. Para no `teto_requisicoes` contando as duas.
    Cota esgotada encerra; outra falha de lote cai pra uma por uma; falha
    avulsa pula a partida sem marcar (ela volta na proxima rodada)."""
    from utils.api_client import ApiQuotaEsgotada
    gastas = 0
    for ids in em_lotes(list(fixture_ids)):
        if gastas >= teto_requisicoes:
            return
        gastas += 1
        try:
            lote = buscar_bloco(ids, bloco, origem)
        except ApiQuotaEsgotada as e:
            print(f"[LOTE {origem}] cota esgotada: {e}")
            return
        except Exception as e:
            print(f"[LOTE {origem}] lote a partir de {ids[0]} falhou ({e}) · uma por uma")
            lote = {}
        for fid in ids:
            if fid in lote:
                yield fid, lote[fid]
                continue
            if gastas >= teto_requisicoes:
                return
            gastas += 1
            try:
                resposta = avulsa(fid)
            except ApiQuotaEsgotada as e:
                print(f"[LOTE {origem}] cota esgotada: {e}")
                return
            except Exception as e:
                print(f"[LOTE {origem}] fixture_id={fid}: {e}")
                continue
            yield fid, resposta
