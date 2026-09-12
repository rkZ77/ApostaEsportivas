"""DATA_QUALITY_SCORE e CONVERGENCIA -- o que o motor sabe, e quantos sabem.

O DEFEITO QUE ISTO FECHA
------------------------
A V1 tratava ausencia de dado de duas formas, e nenhuma delas custava nada:

  · piso de amostra: 4 jogos passa, 3 reprova. Entre 4 e 14 nao havia
    diferenca nenhuma na decisao -- so' na parcela de consistencia do Score,
    que vale 10 pontos e nao reprova ninguem sozinha;

  · cobertura de HT: bastava ter 4 jogos com intervalo. Um time com 14 jogos
    lidos e 4 com HT publicado tinha a MESMA leitura de primeiro tempo que um
    com 14 e 14 -- e a primeira e' uma amostra de 29% do periodo, escolhida
    pelo provedor, nao pelo motor.

Aqui esses dois viram preco: a cobertura entra no score, o score desconta a
confianca e, abaixo do minimo, recusa a pick.

CONVERGENCIA: QUANTAS FONTES INDEPENDENTES CONCORDAM
----------------------------------------------------
Oito sinais, quatro de cada perna. Nao e' media ponderada nem soma de pontos:
e' CONTAGEM. Um jogo aprovado por oito sinais e um aprovado por quatro podem
ter o mesmo Score -- o segundo esta' apoiado em menos pernas, e e' isso que a
contagem mostra e o somatorio esconde.
"""
from __future__ import annotations

from datetime import date, datetime

from services.pick_engine_boost import config as cfg


def _faixa(valor, piso: float, teto: float) -> float:
    if valor is None or teto == piso:
        return 0.0
    return max(0.0, min(1.0, (float(valor) - piso) / (teto - piso)))


def _faixa_invertida(valor, bom: float, ruim: float) -> float:
    if valor is None or ruim == bom:
        return 0.0
    return max(0.0, min(1.0, (ruim - float(valor)) / (ruim - bom)))


def classificar(score: float) -> str:
    if score >= 90:
        return "EXCELENTE"
    if score >= 80:
        return "BOA"
    if score >= 70:
        return "LIMITADA"
    return "INSUFICIENTE"


def _dias_desde(jogos: list) -> int | None:
    """Idade do jogo mais recente lido. O historico vem do mais novo pro mais
    antigo, entao e' o primeiro da lista."""
    for j in jogos or []:
        d = j.get("match_date")
        if d is None:
            continue
        if isinstance(d, datetime):
            d = d.date()
        if isinstance(d, date):
            return (date.today() - d).days
    return None


def data_quality(perfil_home: dict, perfil_away: dict,
                 hist_home: list, hist_away: list) -> dict:
    """0-100 sobre o ELO MAIS FRACO dos dois times.

    Media dos dois seria a conta errada pelo mesmo motivo que ja' vale em
    `stats_model.consistencia`: o pick depende dos dois, e um time cego nao
    fica enxergando porque o outro enxerga bem.
    """
    def pior(chave):
        valores = [p.get(chave) for p in (perfil_home, perfil_away)]
        valores = [v for v in valores if v is not None]
        return min(valores) if valores else None

    jogos = pior("jogos")
    jogos_ht = pior("jogos_com_ht")
    jogos_mando = pior("jogos_no_mando")

    cobertura = []
    for p in (perfil_home, perfil_away):
        if p.get("jogos"):
            cobertura.append((p.get("jogos_com_ht") or 0) / p["jogos"])
    cobertura_ht = min(cobertura) if cobertura else None

    idades = [d for d in (_dias_desde(hist_home), _dias_desde(hist_away)) if d is not None]
    dias = max(idades) if idades else None

    # Completude: quantos dos indicadores que a decisao usa nasceram com
    # numero. Nenhum deles e' opcional -- se um esta' None, alguma parcela do
    # Score entrou valendo zero sem que isso fosse uma medicao.
    criticos = ("media_gols_total", "media_gols_ht", "freq_over15",
                "freq_under25_ht", "freq_over15_mando", "desvio_gols_ht")
    preenchidos = sum(1 for p in (perfil_home, perfil_away) for c in criticos
                      if p.get(c) is not None)
    completude = preenchidos / (2 * len(criticos))

    partes = {
        "amostra_ft": _faixa(jogos, cfg.MIN_JOGOS_FT, cfg.JANELA_LONGA),
        "amostra_ht": _faixa(jogos_ht, cfg.MIN_JOGOS_HT, cfg.JANELA_LONGA),
        "cobertura_ht": _faixa(cobertura_ht, 0.40, 0.90),
        "amostra_mando": _faixa(jogos_mando, 2, 5),
        "recencia": _faixa_invertida(dias, *cfg.FAIXA_RECENCIA_DIAS),
        "completude": completude,
    }
    score = round(sum(partes[k] * peso for k, peso in cfg.PESOS_QUALIDADE.items()) * 100, 1)
    return {
        "score": score,
        "classe": classificar(score),
        "partes": {k: round(v, 3) for k, v in partes.items()},
        "jogos_ft": jogos, "jogos_ht": jogos_ht, "jogos_no_mando": jogos_mando,
        "cobertura_ht": round(cobertura_ht, 3) if cobertura_ht is not None else None,
        "dias_desde_o_ultimo_jogo": dias,
        "suficiente": score >= cfg.DATA_QUALITY_MINIMO,
    }


#: Os oito sinais e o que cada um exige pra "concordar". Declarados aqui, em
#: uma lista, pra a contagem ser lida de cima -- e pra acrescentar um sinal
#: novo nao exigir mexer na conta.
SINAIS = (
    ("historico_over15", "freq_over15", 0.70),
    ("mando_over15", "freq_over15_mando", 0.68),
    ("modelo_over15", "prob_modelo_ft", 0.72),
    ("projecao_ft", "margem_ft", cfg.MARGEM_MIN_FT),
    ("historico_under25_ht", "freq_under25_ht", 0.80),
    ("modelo_under25_ht", "prob_modelo_ht", 0.80),
    ("projecao_ht", "margem_ht", 1.20),
    ("tendencia", "tendencia_media", 0.0),
)


def convergencia(valores: dict) -> dict:
    """Quantos dos oito sinais sustentam a pick.

    Sinal sem numero NAO conta como concordancia nem como discordancia: ele
    sai da conta e o denominador encolhe, e o denominador vai gravado. Contar
    ausencia como discordancia faria a cobertura ruim do provedor virar
    argumento contra o jogo.
    """
    a_favor, disponiveis, detalhe = 0, 0, {}
    for nome, chave, minimo in SINAIS:
        v = valores.get(chave)
        if v is None:
            detalhe[nome] = None
            continue
        disponiveis += 1
        ok = float(v) >= minimo
        detalhe[nome] = ok
        a_favor += 1 if ok else 0
    fracao = round(a_favor / disponiveis, 3) if disponiveis else None
    return {
        "fracao": fracao,
        "a_favor": a_favor,
        "disponiveis": disponiveis,
        "sinais": detalhe,
        "suficiente": fracao is not None and fracao >= cfg.CONVERGENCIA_MINIMA,
    }
