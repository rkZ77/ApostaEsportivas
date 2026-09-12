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
from services.pick_engine_boost import joint, shrinkage


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
    #
    # Lido sobre a LISTA INTEIRA e nao sobre os dez primeiros (V2, 11/09): um
    # time joga ~metade dos jogos em cada mando, entao cortar os dez e depois
    # separar por mando deixava 4 ou 5 jogos onde ha' 7. O leitor ja' traz 14
    # por time exatamente pra isso (goals_history.LIMITE_JOGOS), e a V1 jogava
    # essa folga fora no proprio recorte que mais precisava dela.
    no_mando = [j for j in jogos
                if _e_mandante(j, team_id) == (mando_hoje == "home")][:cfg.JANELA_LONGA]
    marcados_mando = [_gols_do_time(j, team_id)[0] for j in no_mando]
    sofridos_mando = [_gols_do_time(j, team_id)[1] for j in no_mando]
    totais_mando = [t for t in (_total_ft(j) for j in no_mando) if t is not None]
    over15_mando = [t for t in totais_mando if t >= 2]
    # Under 2.5 HT no mando de hoje -- a perna do intervalo tambem tem vies de
    # mando, e a V1 so' olhava o total do jogo pra ela.
    ht_mando = [t for t in (_total_ht(j) for j in no_mando) if t is not None]
    under25_ht_mando = [t for t in ht_mando if t <= 2]
    # Os cinco mais recentes NO MANDO -- o "ultimos 5 em casa / fora" pedido.
    totais_mando_curta = [t for t in (_total_ft(j) for j in no_mando[:cfg.JANELA_CURTA])
                          if t is not None]
    over15_mando_curta = [t for t in totais_mando_curta if t >= 2]

    # Janela curta -- so' o que a tendencia usa.
    totais_curta = [t for t in (_total_ft(j) for j in curta) if t is not None]
    over15_curta = [t for t in totais_curta if t >= 2]
    par_acertos, par_total = joint.frequencia_do_par(com_ht)
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
        "over15_mando_acertos": len(over15_mando),
        "over15_mando_total": len(totais_mando),
        "freq_over15_mando_curta": _freq(len(over15_mando_curta), len(totais_mando_curta)),
        "freq_under25_ht_mando": _freq(len(under25_ht_mando), len(ht_mando)),
        "media_gols_ht_mando": _media(ht_mando),

        # -- distribuicao do primeiro tempo (V2) --
        # E' o formato, nao o nivel: quantos jogos encostaram na linha, quantos
        # passaram dela e qual foi o pior. Ver ht_risk.py.
        "ht_2mais": sum(1 for t in totais_ht if t >= 2),
        "ht_3mais": sum(1 for t in totais_ht if t >= 3),
        "ht_exatos_2": sum(1 for t in totais_ht if t == 2),
        "ht_max": max(totais_ht) if totais_ht else None,

        # -- o PAR, contado direto (V2) --
        # Over 1.5 FT e Under 2.5 HT no MESMO jogo. Nao e' reconstruido de duas
        # frequencias: cada jogo do historico ou teve as duas coisas ou nao.
        "par_acertos": par_acertos,
        "par_total": par_total,

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


def distribuicao_ht(perfil_home: dict, perfil_away: dict) -> dict:
    """A distribuicao de gols no intervalo, somando os dois times.

    Somada e nao ponderada de proposito: sao jogos, e cada jogo conta um. Um
    time com 12 jogos de HT e outro com 5 nao devem valer metade e metade --
    a pergunta e' "nesses 17 primeiros tempos, quantos passaram de 1 gol?".
    """
    def soma(chave):
        return sum(int(p.get(chave) or 0) for p in (perfil_home, perfil_away))

    total = soma("under25_ht_total")
    maximos = [p.get("ht_max") for p in (perfil_home, perfil_away)]
    maximos = [int(m) for m in maximos if m is not None]
    desvios = [p.get("desvio_gols_ht") for p in (perfil_home, perfil_away)]
    desvios = [float(d) for d in desvios if d is not None]

    # DISPERSAO RELATIVA (variancia / media), nao o desvio cru.
    #
    # O desvio cru nao e' comparavel entre jogos: um primeiro tempo que
    # produz 1,0 gol em media tem desvio ~1,0 SO' POR SER Poisson, e cobrar
    # risco dele seria cobrar risco do normal. O que interessa e' o EXCESSO
    # sobre o esperado, que e' a mesma grandeza (phi) que o projeto ja' usa
    # pra escolher entre Poisson e Binomial Negativa nas outras familias.
    #
    # E' isto que separa os dois casos que a media nao separa: dez primeiros
    # tempos de 1 gol (phi 0) e oito de 0 com dois de 2 gols (phi 1,6) tem
    # frequencia igual de Under 2.5 HT, e so' o segundo tem cauda.
    phis, pesos = [], 0
    for p in (perfil_home, perfil_away):
        media, desvio = p.get("media_gols_ht"), p.get("desvio_gols_ht")
        n = int(p.get("under25_ht_total") or 0)
        if not media or desvio is None or n <= 1:
            continue
        phis.append((float(desvio) ** 2 / float(media)) * n)
        pesos += n
    dispersao_relativa = round(sum(phis) / pesos, 3) if pesos else None

    return {
        "jogos": total,
        "acertos_under25": soma("under25_ht_acertos"),
        "jogos_2mais": soma("ht_2mais"),
        "jogos_3mais": soma("ht_3mais"),
        "jogos_exatos_2": soma("ht_exatos_2"),
        "freq_2mais": _freq(soma("ht_2mais"), total),
        "freq_3mais": _freq(soma("ht_3mais"), total),
        "freq_exatos_2": _freq(soma("ht_exatos_2"), total),
        "max_ht": max(maximos) if maximos else None,
        "desvio": round(sum(desvios) / len(desvios), 3) if desvios else None,
        "dispersao_relativa": dispersao_relativa,
    }


def analisar_confronto(perfil_home: dict, perfil_away: dict,
                       base: dict | None = None) -> dict:
    """Os indicadores do JOGO, a partir dos dois perfis.

    Devolve tudo que o Score le e tudo que a justificativa exibe -- nao ha um
    segundo calculo em lugar nenhum.

    `base` e' o baseline da liga (baseline.da_liga). Ele e' opcional pra esta
    funcao continuar chamavel sem banco -- em teste, por exemplo -- e o
    fallback e' o global declarado, nunca "sem encolhimento": frequencia crua
    e' justamente o defeito que a V2 veio fechar, e deixar ela como caminho de
    ausencia seria reabrir a porta pelo lado de dentro.
    """
    base = base or {
        "over15_ft": cfg.BASELINE_OVER15_FT, "under25_ht": cfg.BASELINE_UNDER25_HT,
        "par": cfg.BASELINE_PAR, "gols_ht": cfg.BASELINE_GOLS_HT, "fonte": "global",
    }
    lam_ft = _lambda_ft(perfil_home, perfil_away)
    # lambda_ht ENCOLHIDO (V2): a media de gols do intervalo de um time com 4
    # jogos com HT publicado nao e' um numero sobre o time, e' um numero sobre
    # quatro jogos. Aqui os dois times entram com o peso da amostra de cada um
    # e o baseline da liga entra com o peso de PSEUDO_JOGOS_HT jogos.
    lam_ht_cru = _lambda_ht(perfil_home, perfil_away)
    lam_ht = shrinkage.encolher_media(
        [(p.get("media_gols_ht"), p.get("under25_ht_total")) for p in (perfil_home, perfil_away)],
        base.get("gols_ht"), cfg.PSEUDO_JOGOS_HT)
    if lam_ht is None:
        lam_ht = lam_ht_cru

    # Poisson, e nao Binomial Negativa: gol e' a unica familia do projeto em
    # que a variancia bate com a media (phi 1.07). Ver config.PHI_GOLS_TOTAL.
    prob_modelo_ft = (pm.prob_over(cfg.LINHA_OVER_FT, lam_ft, cfg.PHI_GOLS_TOTAL)
                      if lam_ft else None)
    prob_modelo_ht = (pm.prob_under(cfg.LINHA_UNDER_HT, lam_ht, cfg.PHI_GOLS_HT)
                      if lam_ht is not None else None)

    # Frequencia historica ENCOLHIDA (V2), uma por time e depois a media. Nao
    # e' a frequencia do confronto (que teria 2 ou 3 jogos de amostra).
    #
    # Encolher ANTES de tirar a media, e nao depois, importa: um time com 4/4 e
    # outro com 6/10 tem amostras diferentes, e a media das duas frequencias
    # cruas trataria as duas afirmacoes como igualmente firmes. Encolhido
    # primeiro, cada um chega na media ja' pesado pela propria amostra.
    freq_ft_cru = _media([perfil_home.get("freq_over15"), perfil_away.get("freq_over15")])
    freq_ht_cru = _media([perfil_home.get("freq_under25_ht"), perfil_away.get("freq_under25_ht")])
    freq_ft = _media([
        shrinkage.encolher(p.get("over15_acertos"), p.get("over15_total"),
                           base.get("over15_ft"), cfg.PSEUDO_JOGOS_FT)
        for p in (perfil_home, perfil_away)])
    freq_ht = _media([
        shrinkage.encolher(p.get("under25_ht_acertos"), p.get("under25_ht_total"),
                           base.get("under25_ht"), cfg.PSEUDO_JOGOS_HT)
        for p in (perfil_home, perfil_away)])
    freq_par = _media([
        shrinkage.encolher(p.get("par_acertos"), p.get("par_total"),
                           base.get("par"), cfg.PSEUDO_JOGOS_HT)
        for p in (perfil_home, perfil_away)])

    prob_ft = _combinar(prob_modelo_ft, freq_ft)
    prob_ht = _combinar(prob_modelo_ht, freq_ht)

    # -- o PAR (V2) ----------------------------------------------------------
    # Modelo: decomposicao em duas metades independentes (joint.py), nao o
    # produto das duas pernas. Historico: a contagem direta do par.
    modelo_par = joint.probabilidade_do_par(lam_ft, lam_ht)
    prob_par = _combinar(modelo_par, freq_par)
    divergencia = (round(float(modelo_par) - float(freq_par), 4)
                   if modelo_par is not None and freq_par is not None else None)
    produto_v1 = (round(prob_ft * prob_ht, 4)
                  if prob_ft is not None and prob_ht is not None else None)

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
        "freq_over15_cru": freq_ft_cru,
        "freq_under25_ht_cru": freq_ht_cru,
        "deslocamento_freq_ft": shrinkage.deslocamento(freq_ft_cru, freq_ft),
        "deslocamento_freq_ht": shrinkage.deslocamento(freq_ht_cru, freq_ht),
        "baseline": base,
        "prob_over15_ft": prob_ft,
        "prob_under25_ht": prob_ht,

        # -- o PAR (V2) ------------------------------------------------------
        # `prob_combinada` deixou de ser prob_ft x prob_ht. O produto tratava
        # os dois eventos como independentes, e eles dividem os gols do
        # primeiro tempo com sinal trocado -- ele SUPERESTIMA. Fica gravado em
        # `prob_combinada_produto_v1` pra a diferenca ser auditavel jogo a
        # jogo, e nao so' argumentada. Ver joint.py.
        "prob_modelo_par": modelo_par,
        "freq_par": freq_par,
        "prob_combinada": prob_par,
        "prob_combinada_produto_v1": produto_v1,
        "divergencia_modelo_historico": divergencia,

        # -- projecao contra a linha (V2) ------------------------------------
        "margem_ft": round(float(lam_ft) - cfg.LINHA_OVER_FT, 3) if lam_ft is not None else None,
        "margem_ht": round(cfg.LINHA_UNDER_HT - float(lam_ht), 3) if lam_ht is not None else None,
        "lambda_ht_cru": lam_ht_cru,
        "lambda_2t": joint.lambda_segundo_tempo(lam_ft, lam_ht),

        "distribuicao_ht": distribuicao_ht(perfil_home, perfil_away),
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
