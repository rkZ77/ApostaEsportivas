"""A justificativa do Pick Boost, montada a partir dos numeros que decidiram.

REGRA: NENHUM NUMERO NOVO
-------------------------
Tudo aqui sai de `stats_model.analisar_confronto` e dos dois perfis. Se uma
frase precisar de um numero que nao esta' la', o lugar de calcula-lo e' o
stats_model -- senao a explicacao vira um segundo calculo, e dois calculos
sobre a mesma coisa acabam discordando. E' o defeito que ja' apareceu no
projeto entre o card de forma e o motor, em 08/08.

DOIS FORMATOS, MESMA FONTE
--------------------------
  · `resumo_estruturado` -- lista de indicadores rotulados, pra a tela montar
    ("Over 1.5: 9 de 10 jogos"). E' o que o admin ve em "Por que essa pick?";
  · `frase` -- o texto corrido que vai pra `reasoning` do pick.

A IA nao entra em nenhum dos dois. Ela pode explicar depois, por cima; o
numero e a conclusao sao do motor estatistico.
"""
from __future__ import annotations

from services.pick_engine_boost import config as cfg


def _pct(v) -> str:
    return "n/d" if v is None else f"{float(v) * 100:.0f}%"


def _n(v, casas=2) -> str:
    return "n/d" if v is None else f"{float(v):.{casas}f}".replace(".", ",")


def resumo_estruturado(confronto: dict, perfil_home: dict, perfil_away: dict,
                       fixture: dict) -> list:
    """Os indicadores que sustentaram a decisao, em ordem de importancia.

    Cada item e' {rotulo, valor, detalhe}. `detalhe` carrega a amostra quando
    ela existe -- "9 de 10" diz mais que "90%", e a diferenca entre 9/10 e
    90/100 e' justamente o que o Score pesa em consistencia.
    """
    home = fixture.get("home_team") or "Mandante"
    away = fixture.get("away_team") or "Visitante"
    ad = confronto.get("ataque_defesa") or {}
    tend = confronto.get("tendencia") or {}
    cons = confronto.get("consistencia") or {}

    itens = [
        {"rotulo": "Over 1.5 FT · frequência",
         "valor": _pct(confronto.get("freq_over15")),
         "detalhe": (f"{perfil_home.get('over15_acertos')} de {perfil_home.get('over15_total')} "
                     f"({home}) · {perfil_away.get('over15_acertos')} de "
                     f"{perfil_away.get('over15_total')} ({away})")},
        {"rotulo": "Under 2.5 HT · frequência",
         "valor": _pct(confronto.get("freq_under25_ht")),
         "detalhe": (f"{perfil_home.get('under25_ht_acertos')} de {perfil_home.get('under25_ht_total')} "
                     f"({home}) · {perfil_away.get('under25_ht_acertos')} de "
                     f"{perfil_away.get('under25_ht_total')} ({away})")},
        {"rotulo": "Média de gols no jogo",
         "valor": _n(confronto.get("lambda_ft")),
         "detalhe": (f"{_n(perfil_home.get('media_gols_total'))} ({home}) · "
                     f"{_n(perfil_away.get('media_gols_total'))} ({away})")},
        {"rotulo": "Média de gols no 1º tempo",
         "valor": _n(confronto.get("lambda_ht")),
         "detalhe": (f"{_n(perfil_home.get('media_gols_ht'))} ({home}) · "
                     f"{_n(perfil_away.get('media_gols_ht'))} ({away})")},
        {"rotulo": f"{home} em casa · Over 1.5",
         "valor": _pct(perfil_home.get("freq_over15_mando")),
         "detalhe": f"{perfil_home.get('jogos_no_mando')} jogos como mandante"},
        {"rotulo": f"{away} fora · Over 1.5",
         "valor": _pct(perfil_away.get("freq_over15_mando")),
         "detalhe": f"{perfil_away.get('jogos_no_mando')} jogos como visitante"},
        {"rotulo": "Ataque do mandante x defesa do visitante",
         "valor": f"{_n(ad.get('mandante_ataca'))} x {_n(ad.get('visitante_defende'))}",
         "detalhe": "gols marcados em casa contra gols sofridos fora"},
        {"rotulo": "Ataque do visitante x defesa do mandante",
         "valor": f"{_n(ad.get('visitante_ataca'))} x {_n(ad.get('mandante_defende'))}",
         "detalhe": "gols marcados fora contra gols sofridos em casa"},
        {"rotulo": "Tendência (últimos 5 x últimos 10)",
         "valor": _delta_texto(tend.get("over15"), tend.get("under25_ht")),
         "detalhe": "variação das duas frequências na janela curta"},
        {"rotulo": "Consistência",
         "valor": (f"amostra {cons.get('min_amostra_ft')}/{cons.get('min_amostra_ht')} "
                   f"(FT/HT)"),
         "detalhe": f"desvio de gols {_n(cons.get('desvio_medio_gols'))}"},
        {"rotulo": "Probabilidade Over 1.5 FT",
         "valor": _pct(confronto.get("prob_over15_ft")),
         "detalhe": f"modelo {_pct(confronto.get('prob_modelo_ft'))} + histórico "
                    f"{_pct(confronto.get('freq_over15'))}"},
        {"rotulo": "Probabilidade Under 2.5 HT",
         "valor": _pct(confronto.get("prob_under25_ht")),
         "detalhe": f"modelo {_pct(confronto.get('prob_modelo_ht'))} + histórico "
                    f"{_pct(confronto.get('freq_under25_ht'))}"},
    ]
    return itens


def _delta_texto(over, under) -> str:
    partes = []
    for rotulo, valor in (("Over 1.5", over), ("Under 2.5 HT", under)):
        if valor is None:
            continue
        sinal = "+" if float(valor) >= 0 else ""
        partes.append(f"{rotulo} {sinal}{float(valor) * 100:.0f} p.p.")
    return " · ".join(partes) if partes else "n/d"


def conclusao(score: float, confronto: dict) -> str:
    """A frase de fecho -- a mesma que o usuario pediu como exemplo.

    Muda de texto conforme o que sustentou o Score, e nao um template fixo:
    um jogo aprovado por consistencia e um aprovado por tendencia forte nao
    foram aprovados pela mesma coisa, e dizer a mesma frase nos dois casos
    torna a conclusao decorativa.
    """
    freq_ft = confronto.get("freq_over15")
    freq_ht = confronto.get("freq_under25_ht")
    if freq_ft is not None and freq_ht is not None and freq_ft >= 0.85 and freq_ht >= 0.85:
        return ("Selecionada devido à forte consistência estatística para "
                "Over 1.5 FT e Under 2.5 HT.")
    if freq_ft is not None and freq_ft >= 0.85:
        return ("Selecionada pelo histórico de Over 1.5 no jogo inteiro, com "
                "primeiros tempos dentro da linha.")
    if freq_ht is not None and freq_ht >= 0.85:
        return ("Selecionada pelos primeiros tempos fechados dos dois times, com "
                "volume de gols suficiente no jogo completo.")
    return (f"Selecionada por Score Estatístico {score:.0f}, sustentado pela "
            f"combinação dos indicadores acima.")


def frase(score: float, confronto: dict, perfil_home: dict, perfil_away: dict,
          fixture: dict) -> str:
    """Texto corrido pro campo `reasoning` do pick."""
    home = fixture.get("home_team") or "Mandante"
    away = fixture.get("away_team") or "Visitante"
    partes = [
        f"Score Estatístico {score:.0f}/100 para a combinação Over "
        f"{cfg.LINHA_OVER_FT} FT + Under {cfg.LINHA_UNDER_HT} HT.",
        f"Over 1.5 saiu em {perfil_home.get('over15_acertos')} dos "
        f"{perfil_home.get('over15_total')} últimos jogos do {home} e em "
        f"{perfil_away.get('over15_acertos')} dos {perfil_away.get('over15_total')} do {away}.",
        f"Under 2.5 no primeiro tempo saiu em {perfil_home.get('under25_ht_acertos')} de "
        f"{perfil_home.get('under25_ht_total')} ({home}) e "
        f"{perfil_away.get('under25_ht_acertos')} de "
        f"{perfil_away.get('under25_ht_total')} ({away}), com média de "
        f"{_n(confronto.get('lambda_ht'))} gol no intervalo.",
        f"Gols esperados no jogo: {_n(confronto.get('lambda_ft'))}.",
        conclusao(score, confronto),
    ]
    return " ".join(partes)
