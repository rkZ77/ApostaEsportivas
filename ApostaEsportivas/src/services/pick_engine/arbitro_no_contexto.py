"""O arbitro no contexto da partida, pra IA (18/10/2026).

PEDIDO DO USUARIO
-----------------
"O arbitro interfere no contexto da partida: vai que e' classico e o arbitro
e' rigoroso, o motor precisa saber disso, e o Raio-X na leitura de IA."

O QUE JA' EXISTIA E O QUE FALTAVA
---------------------------------
O motor ja' usa o arbitro em tres contas: a terceira estimativa de cartao
(referee_model.cards_probability), o score de intensidade (game_intensity) e o
modelo de faltas (40% de peso). A rivalidade e' medida nos confrontos diretos
(rivalry_model). O que faltava era a IA ver as duas coisas JUNTAS, com a
referencia da liga: "6,8 pontos de cartao por jogo" nao diz nada sem saber que
a liga da' 4,9.

NUMERO, NAO CONTA
-----------------
Isto vai pro dossie (o que a IA le' antes do veto) e nao entra em
probabilidade nenhuma -- regra do usuario: sinal novo entra no dossie e na
medicao primeiro (scripts/medir_arbitro_e_classico.py), e so' entra na conta
depois de medido. Campo sem dado fica de fora, nunca vira zero.
"""
from __future__ import annotations

#: Pontos de cartao (amarelo + 2x vermelho) acima/abaixo da media da liga a
#: partir dos quais o arbitro e' "rigoroso"/"leniente". 0,8 ponto e' quase um
#: amarelo por jogo: aparece numa linha de 4,5, nao e' ruido de arredondamento.
#: Escolhido, nao medido -- a medicao diz se o corte separa resultado.
DIFERENCA_RELEVANTE = 0.8
#: Abaixo disto o perfil sai "amostra curta": media de 3 jogos e' ruido.
MIN_JOGOS_PERFIL = 5


def _pontos(stats: dict | None) -> float | None:
    if not stats or stats.get("avg_yellow") is None:
        return None
    return float(stats["avg_yellow"]) + 2 * float(stats.get("avg_red") or 0)


def perfil_do_arbitro(jogos: int | None, pontos: float | None, pontos_liga: float | None) -> str | None:
    if pontos is None or pontos_liga is None:
        return None
    if (jogos or 0) < MIN_JOGOS_PERFIL:
        return "amostra_curta"
    diff = pontos - pontos_liga
    if diff >= DIFERENCA_RELEVANTE:
        return "rigoroso"
    if diff <= -DIFERENCA_RELEVANTE:
        return "leniente"
    return "na_media_da_liga"


def temperatura(perfil: str | None, rivalidade: str | None) -> str | None:
    """Juntando quem apita com o historico do confronto."""
    quente_arb, frio_arb = perfil == "rigoroso", perfil == "leniente"
    quente_jogo = rivalidade == "rivalidade_alta"
    frio_jogo = rivalidade == "confronto_frio"
    if perfil in (None, "amostra_curta") and rivalidade in (None, "desconhecido"):
        return None
    if quente_arb and quente_jogo:
        return "confronto_quente_com_arbitro_rigoroso"
    if quente_jogo and frio_arb:
        return "confronto_quente_com_arbitro_leniente"
    if quente_arb and frio_jogo:
        return "confronto_frio_com_arbitro_rigoroso"
    if frio_arb and frio_jogo:
        return "confronto_frio_com_arbitro_leniente"
    if quente_jogo:
        return "confronto_quente"
    if frio_jogo:
        return "confronto_frio"
    if quente_arb:
        return "arbitro_rigoroso"
    if frio_arb:
        return "arbitro_leniente"
    return "normal"


def leitura(nome: str | None, arbitro: dict | None, liga: dict | None, rivalidade: dict | None) -> dict | None:
    """O bloco `arbitro` do dossie. `arbitro` e' RefereeStatsService.get_stats
    (todas as grafias + outras ligas do pais), `liga` e' get_league_stats,
    `rivalidade` e' rivalry_model.rivalry_signal."""
    pontos, pontos_liga = _pontos(arbitro), _pontos(liga)
    jogos = (arbitro or {}).get("games")
    perfil = perfil_do_arbitro(jogos, pontos, pontos_liga)
    riv_label = (rivalidade or {}).get("label")
    saida = {
        "nome": (nome or "").split(",")[0].strip() or None,
        "jogos_na_temporada_com_folha": jogos,
        "pontos_de_cartao_por_jogo": round(pontos, 2) if pontos is not None else None,
        "pontos_de_cartao_da_liga": round(pontos_liga, 2) if pontos_liga is not None else None,
        "amarelos_por_jogo": float(arbitro["avg_yellow"]) if (arbitro or {}).get("avg_yellow") is not None else None,
        "faltas_por_jogo": float(arbitro["avg_fouls"]) if (arbitro or {}).get("avg_fouls") is not None else None,
        "perfil": perfil,
        "confronto_direto_cartoes": ({
            "confrontos": rivalidade.get("confrontos"),
            "pontos_por_confronto": rivalidade.get("media_h2h"),
            "esperado_pelos_times": rivalidade.get("baseline"),
            "excesso": rivalidade.get("excesso"),
            "leitura": riv_label,
        } if rivalidade and rivalidade.get("confiavel") else None),
        "temperatura": temperatura(perfil, riv_label),
    }
    saida = {k: v for k, v in saida.items() if v is not None}
    return saida if len(saida) > 1 else None
