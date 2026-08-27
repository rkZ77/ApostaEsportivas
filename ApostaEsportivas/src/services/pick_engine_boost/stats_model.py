"""Os indicadores do Pick Boost, calculados sobre o historico ja' lido.

CADA NUMERO AQUI VAI PARAR NA TELA
----------------------------------
Este modulo nao produz um score sozinho -- produz o conjunto de indicadores
que o Score usa E que a justificativa exibe. As duas coisas leem o MESMO
dicionario, e e' isso que impede a explicacao de contar uma historia diferente
da decisao. Ja' aconteceu no projeto o contrario (card e motor discordando
sobre escanteios em 08/08), e o custo foi confianca.

DOIS RECORTES, PROPOSITALMENTE DIFERENTES
-----------------------------------------
  · TOTAL DO JOGO (media de gols, Over 1.5, Under 2.5 HT): le os jogos do time
    em QUALQUER mando. E' contador de PARTIDA, e o vies de mando num contador
    de partida e' pequeno -- cortar por mando aqui reduziria a amostra pela
    metade pra corrigir quase nada.

  · DESEMPENHO POR MANDO e ATAQUE x DEFESA: leem so' o mando que o time vai
    jogar hoje. Aqui o vies e' o efeito, nao ruido: mandante e visitante
    marcam e sofrem em taxas diferentes, e misturar produz um numero que nao
    descreve nem um caso nem o outro.

E' a mesma distincao que o resto do projeto ja' faz (ver a nota sobre mercado
de total em routers/suggestions.py::get_market_form).
"""
from __future__ import annotations

from statistics import pstdev

from services.pick_engine import probability_model as pm
from services.pick_engine_boost import config as cfg


def _gols_do_time(jogo: dict, team_id: int) -> tuple:
    """(marcados, sofridos) resolvidos por team_id, nunca pela coluna."""
    if jogo.get("home_team_id") == team_id:
        return jogo.get("home_goals"), jogo.get("away_goals")
    return jogo.get("away_goals"), jogo.get("home_goals")


def _e_mandante(jogo: dict, team_id: int) -> bool:
    return jogo.get("home_team_id") == team_id


def _media(valores: list) -> float | None:
    valores = [v for v in valores if v is not None]
    if not valores:
        return None
    return round(sum(float(v) for v in valores) / len(valores), 3)


def _freq(acertos: int, total: int) -> float | None:
    return round(acertos / total, 4) if total else None


def _total_ht(jogo: dict) -> int | None:
    casa, fora = jogo.get("home_goals_ht"), jogo.get("away_goals_ht")
    if casa is None or fora is None:
        return None
    return int(casa) + int(fora)


def _total_ft(jogo: dict) -> int | None:
    casa, fora = jogo.get("home_goals"), jogo.get("away_goals")
    if casa is None or fora is None:
        return None
    return int(casa) + int(fora)


# ---------------------------------------------------------------------------
# Perfil de um time
# ---------------------------------------------------------------------------
def perfil_do_time(jogos: list, team_id: int, mando_hoje: str) -> dict:
    """Todos os indicadores de UM time, nas duas janelas.

    `mando_hoje` e' 'home' ou 'away' -- define qual recorte de mando alimenta
    os indicadores de desempenho e de ataque/defesa.
    """
    longa = jogos[:cfg.JANELA_LONGA]
    curta = jogos[:cfg.JANELA_CURTA]

    marcados = [_gols_do_time(j, team_id)[0] for j in longa]
    sofridos = [_gols_do_time(j, team_id)[1] for j in longa]
    totais = [_total_ft(j) for j in longa]
    totais = [t for t in totais if t is not None]

    over15 = [t for t in totais if t >= 2]

    com_ht = [j for j in longa if _total_ht(j) is not None]
    totais_ht = [_total_ht(j) for j in com_ht]
    under25_ht = [t for t in totais_ht if t <= 2]

    # Recorte de mando: so' os jogos no mando que o time vai jogar HOJE.
    no_mando = [j for j in longa
                if _e_mandante(j, team_id) == (mando_hoje == "home")]
    marcados_mando = [_gols_do_time(j, team_id)[0] for j in no_mando]
    sofridos_mando = [_gols_do_time(j, team_id)[1] for j in no_mando]
    totais_mando = [t for t in (_total_ft(j) for j in no_mando) if t is not None]
    over15_mando = [t for t in totais_mando if t >= 2]

    # Janela curta -- so' o que a tendencia usa.
    totais_curta = [t for t in (_total_ft(j) for j in curta) if t is not None]
    over15_curta = [t for t in totais_curta if t >= 2]
    totais_ht_curta = [t for t in (_total_ht(j) for j in curta) if t is not None]
    under25_ht_curta = [t for t in totais_ht_curta if t <= 2]

    return {
        "team_id": team_id,
        "mando_hoje": mando_hoje,
        "jogos": len(longa),
        "jogos_com_ht": len(com_ht),
        "jogos_no_mando": len(no_mando),

        # -- gols, janela longa --
        "media_gols_marcados": _media(marcados),
        "media_gols_sofridos": _media(sofridos),
        "media_gols_total": _media(totais),
        "over15_acertos": len(over15),
        "over15_total": len(totais),
        "freq_over15": _freq(len(over15), len(totais)),

        # -- primeiro tempo --
        "media_gols_ht": _media(totais_ht),
        "under25_ht_acertos": len(under25_ht),
        "under25_ht_total": len(totais_ht),
        "freq_under25_ht": _freq(len(under25_ht), len(totais_ht)),

        # -- desempenho no mando de hoje --
        "media_marcados_mando": _media(marcados_mando),
        "media_sofridos_mando": _media(sofridos_mando),
        "media_total_mando": _media(totais_mando),
        "freq_over15_mando": _freq(len(over15_mando), len(totais_mando)),

        # -- janela curta (tendencia) --
        "jogos_curta": len(totais_curta),
        "media_gols_total_curta": _media(totais_curta),
        "freq_over15_curta": _freq(len(over15_curta), len(totais_curta)),
        "media_gols_ht_curta": _media(totais_ht_curta),
        "freq_under25_ht_curta": _freq(len(under25_ht_curta), len(totais_ht_curta)),

        # -- dispersao: o quanto o time varia jogo a jogo --
        # Desvio populacional (nao amostral) de proposito: sao TODOS os jogos
        # que o motor leu, nao uma amostra deles.
        "desvio_gols_total": round(pstdev([float(t) for t in totais]), 3) if len(totais) > 1 else None,
        "desvio_gols_ht": round(pstdev([float(t) for t in totais_ht]), 3) if len(totais_ht) > 1 else None,
    }


# ---------------------------------------------------------------------------
# Confronto
# ---------------------------------------------------------------------------
def _lambda_ft(perfil_home: dict, perfil_away: dict) -> float | None:
    """Gols esperados no jogo -- ataque de cada lado contra a defesa do outro.

    Media de duas leituras que costumam discordar: (o que o mandante marca em
    casa + o que o visitante sofre fora) e o espelho disso. Discordancia entre
    as duas e' informacao, e ela sai em `ataque_defesa` pra tela; aqui elas
    entram somadas porque o mercado e' o TOTAL do jogo.
    """
    casa_marca = perfil_home.get("media_marcados_mando") or perfil_home.get("media_gols_marcados")
    casa_sofre = perfil_home.get("media_sofridos_mando") or perfil_home.get("media_gols_sofridos")
    fora_marca = perfil_away.get("media_marcados_mando") or perfil_away.get("media_gols_marcados")
    fora_sofre = perfil_away.get("media_sofridos_mando") or perfil_away.get("media_gols_sofridos")
    if None in (casa_marca, casa_sofre, fora_marca, fora_sofre):
        return None
    # Ataque de um com defesa do outro, media simples. Sem fator de liga: o
    # baseline entra pelo proprio historico dos dois times, que ja' e' da liga
    # deles.
    esperado_home = (float(casa_marca) + float(fora_sofre)) / 2
    esperado_away = (float(fora_marca) + float(casa_sofre)) / 2
    return round(esperado_home + esperado_away, 3)


def _lambda_ht(perfil_home: dict, perfil_away: dict) -> float | None:
    """Gols esperados no PRIMEIRO TEMPO -- media das duas medias de HT.

    Nao e' uma fracao do lambda de FT. A proporcao gol-no-primeiro-tempo varia
    por time e por liga, e derivar do total apagaria exatamente o sinal que
    este metodo procura: times que jogam morno e resolvem no segundo tempo.
    """
    a, b = perfil_home.get("media_gols_ht"), perfil_away.get("media_gols_ht")
    if a is None and b is None:
        return None
    valores = [float(v) for v in (a, b) if v is not None]
    return round(sum(valores) / len(valores), 3)


def _combinar(modelo: float | None, historico: float | None,
              peso_modelo: float = 0.55) -> float | None:
    """Probabilidade final de uma perna: modelo e frequencia historica.

    Nenhuma das duas sozinha serve. So' o modelo joga fora que o jogo em
    questao ja' aconteceu dez vezes; so' a frequencia trata 8/10 e 80/100 como
    a mesma afirmacao. A media ponderada e' a versao honesta de "os dois
    concordam" -- e quando eles discordam muito, `consistencia` derruba o
    Score, que e' onde a discordancia tem que doer.
    """
    valores = [(modelo, peso_modelo), (historico, 1 - peso_modelo)]
    validos = [(v, p) for v, p in valores if v is not None]
    if not validos:
        return None
    soma_peso = sum(p for _, p in validos)
    return round(sum(float(v) * p for v, p in validos) / soma_peso, 4)


def analisar_confronto(perfil_home: dict, perfil_away: dict) -> dict:
    """Os indicadores do JOGO, a partir dos dois perfis.

    Devolve tudo que o Score le e tudo que a justificativa exibe -- nao ha um
    segundo calculo em lugar nenhum.
    """
    lam_ft = _lambda_ft(perfil_home, perfil_away)
    lam_ht = _lambda_ht(perfil_home, perfil_away)

    # Poisson, e nao Binomial Negativa: gol e' a unica familia do projeto em
    # que a variancia bate com a media (phi 1.07). Ver config.PHI_GOLS_TOTAL.
    prob_modelo_ft = (pm.prob_over(cfg.LINHA_OVER_FT, lam_ft, cfg.PHI_GOLS_TOTAL)
                      if lam_ft else None)
    prob_modelo_ht = (pm.prob_under(cfg.LINHA_UNDER_HT, lam_ht, cfg.PHI_GOLS_HT)
                      if lam_ht is not None else None)

    # Frequencia historica: a media das duas frequencias, uma por time. Nao e'
    # a frequencia do confronto (que teria 2 ou 3 jogos de amostra).
    freq_ft = _media([perfil_home.get("freq_over15"), perfil_away.get("freq_over15")])
    freq_ht = _media([perfil_home.get("freq_under25_ht"), perfil_away.get("freq_under25_ht")])

    prob_ft = _combinar(prob_modelo_ft, freq_ft)
    prob_ht = _combinar(prob_modelo_ht, freq_ht)

    ataque_defesa = {
        # Nomeado pelo que ele mede, nao pelo lado: "ataque do mandante contra
        # a defesa do visitante" e' uma frase que sobrevive a leitura rapida.
        "mandante_ataca": perfil_home.get("media_marcados_mando"),
        "visitante_defende": perfil_away.get("media_sofridos_mando"),
        "visitante_ataca": perfil_away.get("media_marcados_mando"),
        "mandante_defende": perfil_home.get("media_sofridos_mando"),
    }

    return {
        "lambda_ft": lam_ft,
        "lambda_ht": lam_ht,
        "prob_modelo_ft": round(prob_modelo_ft, 4) if prob_modelo_ft is not None else None,
        "prob_modelo_ht": round(prob_modelo_ht, 4) if prob_modelo_ht is not None else None,
        "freq_over15": freq_ft,
        "freq_under25_ht": freq_ht,
        "prob_over15_ft": prob_ft,
        "prob_under25_ht": prob_ht,
        # A probabilidade do PAR. Independencia e' aproximacao, e ela e'
        # CONSERVADORA aqui: Under no primeiro tempo e Over no jogo inteiro
        # sao levemente concordantes (jogo que nao abre cedo tende a abrir
        # depois), entao o produto subestima em vez de superestimar. Um erro
        # que empurra pra baixo e' o erro aceitavel num criterio de selecao.
        "prob_combinada": (round(prob_ft * prob_ht, 4)
                           if prob_ft is not None and prob_ht is not None else None),
        "ataque_defesa": ataque_defesa,
        "tendencia": tendencia(perfil_home, perfil_away),
        "consistencia": consistencia(perfil_home, perfil_away),
    }


def tendencia(perfil_home: dict, perfil_away: dict) -> dict:
    """Os ultimos 5 confirmam os ultimos 10, ou contradizem?

    Devolve o DELTA, com sinal, nas duas frequencias. Positivo em `over15`
    quer dizer que o time vem marcando mais que a base; positivo em
    `under25_ht` quer dizer que os primeiros tempos vem mais fechados. Nos dois
    casos, positivo favorece o metodo.
    """
    def delta(chave_curta, chave_longa):
        valores = []
        for p in (perfil_home, perfil_away):
            curta, longa = p.get(chave_curta), p.get(chave_longa)
            if curta is not None and longa is not None:
                valores.append(float(curta) - float(longa))
        return round(sum(valores) / len(valores), 4) if valores else None

    return {
        "over15": delta("freq_over15_curta", "freq_over15"),
        "under25_ht": delta("freq_under25_ht_curta", "freq_under25_ht"),
        "gols_total": delta("media_gols_total_curta", "media_gols_total"),
    }


def consistencia(perfil_home: dict, perfil_away: dict) -> dict:
    """Quanto o dado se sustenta: amostra e dispersao.

    Nao mede se o jogo e' bom -- mede se da' pra AFIRMAR que e'. Um time com
    8/10 de Over 1.5 e desvio 2.4 de gols esta' dizendo outra coisa que um com
    8/10 e desvio 0.9, e o Score precisa poder separar os dois.
    """
    amostras_ft = [p.get("over15_total") or 0 for p in (perfil_home, perfil_away)]
    amostras_ht = [p.get("under25_ht_total") or 0 for p in (perfil_home, perfil_away)]
    desvios = [p.get("desvio_gols_total") for p in (perfil_home, perfil_away)]
    desvios = [float(d) for d in desvios if d is not None]

    return {
        # O ELO MAIS FRACO, nao a media: o metodo depende dos dois times, e um
        # time com 3 jogos nao vira aceitavel porque o outro tem 14.
        "min_amostra_ft": min(amostras_ft) if amostras_ft else 0,
        "min_amostra_ht": min(amostras_ht) if amostras_ht else 0,
        "desvio_medio_gols": round(sum(desvios) / len(desvios), 3) if desvios else None,
    }
