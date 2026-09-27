"""Leitura de um RED: o que aconteceu no jogo que derrubou o pick (2026-09-27).

A aba de REDs respondia "o que o motor escolheu e o que ele deixou de lado".
Faltava a outra metade, a do CAMPO: o pick perdeu por um escanteio ou por
seis? A linha de Under ja' tinha estourado no intervalo? Houve expulsao? O
time entrou poupado? Sao perguntas diferentes e pedem correcoes diferentes:

  evento_atipico   expulsao mudou o jogo; nao e' erro de leitura
  estourou_cedo    Under que ja' tinha passado da linha no 1o tempo: o jogo
                   foi outro desde o comeco
  time_poupado     rodizio de 5 ou mais titulares contra o jogo anterior
  por_pouco        perdeu por 1 ou menos: variancia normal da linha
  leitura_errada   perdeu longe da linha, sem nenhum dos sinais acima: e' o
                   RED que deve pesar contra o motor

Puro: recebe a folha (linha de match_statistics) e a funcao que le o contador
do mercado (routers/live.py::_stat_for_market), a mesma regra da liquidacao.
Nao afirma o que nao mediu: sem folha, sem fato.
"""
from __future__ import annotations

import market_form
from settlement_bridge import settlement

ROTULOS = {
    "evento_atipico": "Expulsão mudou o jogo",
    "estourou_cedo": "Estourou já no 1º tempo",
    "time_poupado": "Time poupado",
    "por_pouco": "Perdeu por pouco",
    "leitura_errada": "Leitura errada do jogo",
    "sem_folha": "Sem estatística do jogo",
}

#: Titulares trocados em relacao ao jogo anterior pra contar como time poupado.
TROCAS_POUPADO = 5


def _valor(stat, market, line, market_type, ms, primeiro_tempo):
    escopo = market_form.escopo_do_mercado(market)
    casa, fora, gc, gf, _ = market_form.perspectiva_do_time(ms, None, escopo, primeiro_tempo)
    valor, _rotulo, _dir = stat(market, line, casa, fora, gc, gf, market_type)
    return valor


def _num(v) -> str:
    """Numero no formato de tela: virgula decimal, sem ",0"."""
    f = float(v)
    return str(int(f)) if f.is_integer() else f"{round(f, 2)}".replace(".", ",")


def ler(market: str, line: str, market_type: str | None, ms: dict | None,
        stat_para_mercado, trocas: dict | None = None) -> dict:
    """{categoria, rotulo, fatos}. `trocas`: {nome do time: titulares trocados}."""
    if not ms:
        return {"categoria": "sem_folha", "rotulo": ROTULOS["sem_folha"], "fatos": []}

    parsed = settlement.parse_line(line)
    op, linha = parsed["op"], parsed["value"]
    linha = float(linha) if linha is not None else None
    primeiro_tempo = market_form.e_mercado_de_primeiro_tempo(market, market_type)
    fatos: list = []
    categoria = None

    vermelhos = sum(v for v in (ms.get("home_red_cards"), ms.get("away_red_cards")) if v)
    if vermelhos:
        fatos.append(f"{vermelhos} expulsão(ões) na partida.")
        categoria = "evento_atipico"

    valor = _valor(stat_para_mercado, market, line, market_type, ms, primeiro_tempo)
    margem = None
    if valor is not None and linha is not None and op in ("over", "under"):
        margem = abs(float(valor) - linha)
        fatos.append(f"Terminou em {_num(valor)} contra a linha {_num(linha)}, "
                     f"diferença de {_num(margem)}.")

    if op == "under" and not primeiro_tempo and linha is not None:
        no_intervalo = _valor(stat_para_mercado, market, line, market_type, ms, True)
        if no_intervalo is not None and float(no_intervalo) > linha:
            fatos.append(f"No intervalo já estava em {_num(no_intervalo)}, acima da linha.")
            categoria = categoria or "estourou_cedo"

    for time, n in (trocas or {}).items():
        if n is not None and n >= TROCAS_POUPADO:
            fatos.append(f"{time} trocou {n} titulares em relação ao jogo anterior.")
            categoria = categoria or "time_poupado"

    if categoria is None:
        categoria = "por_pouco" if (margem is not None and margem <= 1) else "leitura_errada"
    return {"categoria": categoria, "rotulo": ROTULOS[categoria], "fatos": fatos}
