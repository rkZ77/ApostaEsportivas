"""Necessidade competitiva numa competicao de pontos corridos.

O QUE ISTO RESPONDE, E O QUE `context_model.table_pressure` NAO RESPONDIA
------------------------------------------------------------------------
A aproximacao anterior olhava rank e saldo de gols e devolvia um rotulo
("briga_topo", "pressao_alta"), que virava +0.03 chapado no context_score.
Ela nao distinguia o caso que o usuario levantou em 2026-08-14, e que e' o
caso inteiro:

    10o colocado na RODADA 5   -> a tabela ainda nao significa nada
    10o colocado na RODADA 35  -> pode estar a 2 pontos do rebaixamento

Mesma posicao, mesmo saldo, mesmo rotulo antigo. Partidas completamente
diferentes. O que separa as duas nao e' a posicao: e' quantos pontos ainda
existem pra disputar e a que distancia esta' a fronteira que importa.

A CONTA, EM UMA FRASE
---------------------
Necessidade = quao perto o time esta' de uma fronteira que muda a temporada
dele, medida em pontos, DIVIDIDA pelo que ainda da' pra conquistar.

Faltando 3 pontos pra sair do rebaixamento com 30 em disputa (rodada 20), a
distancia e' 10% do disponivel -- da' pra resolver com calma. Os mesmos 3
pontos com 6 em disputa (rodada 36) sao 50% -- e' agora ou nunca. A mesma
formula produz os dois, sem tabela de casos e sem "pressao = +20%".

DE ONDE VEM CADA NUMERO (nenhum coletor novo)
---------------------------------------------
    zonas e fronteiras  `league_standings.description`, a marcacao da propria
                        API por faixa ("Relegation", "Promotion - Copa
                        Libertadores (Group Stage)"). Cada liga desenha o
                        proprio mapa e e' ela quem diz onde as linhas passam --
                        chutar "4 ultimos caem" erraria em metade das ligas
                        cobertas (Portugal rebaixa 2 e tem playoff).
    rodadas restantes   numero de times na tabela -> pontos corridos em turno
                        e returno da 2*(n-1) rodadas; menos `played` do time.
                        Usa o `played` do TIME, nao a rodada do fixture, porque
                        jogo atrasado e' comum e a rodada mente nesse caso.
    sequencia recente   `league_standings.form` ("DWLWW"), ja' coletado e ate'
                        hoje nunca lido por ninguem.

O QUE ESTE MODULO NAO FAZ
-------------------------
Nao aprova pick e nao da' bonus de probabilidade a ninguem. A saida daqui
alimenta (a) o context_score, no mesmo lugar onde a aproximacao antiga
entrava, e (b) o context_gate, como mais uma parcela de pressao CONTRARIA a
Unders. As duas direcoes so' conseguem reduzir ou barrar -- nunca inflar o
volume de picks, que era a condicao explicita do pedido.
"""
from __future__ import annotations

import re

from services.pick_engine.competition_profile import get_profile

TITULO = "TITULO"
CONTINENTAL = "CONTINENTAL"
PROMOCAO = "PROMOCAO"
NEUTRA = "NEUTRA"
REBAIXAMENTO = "REBAIXAMENTO"

#: `description` -> tipo de zona. Testado em ordem: "relegation playoffs" tem
#: que cair em REBAIXAMENTO antes de qualquer coisa, e "promotion play-offs"
#: (acesso) nao pode ser confundido com ele.
_ZONAS = (
    (re.compile(r"relegation|rebaixamento|descenso", re.I), REBAIXAMENTO),
    (re.compile(r"promotion\s*play|play-?offs?\s*de\s*acesso", re.I), PROMOCAO),
    (re.compile(r"champions|libertadores", re.I), CONTINENTAL),
    (re.compile(r"europa|sudamericana|sul-?americana|conference|ecl", re.I), CONTINENTAL),
    (re.compile(r"promotion|acesso", re.I), PROMOCAO),
)

#: Quanto cada fronteira vale pra o clube, 0-1. Nao e' probabilidade: e' o
#: tamanho da consequencia. Cair de divisao reorganiza o clube inteiro; perder
#: a vaga na Conference custa bem menos. Numeros declarados, pra calibrar
#: contra resultado depois -- nao medidos ainda.
_PESO_DA_FRONTEIRA = {
    REBAIXAMENTO: 1.00,
    TITULO: 0.85,
    PROMOCAO: 0.85,
    CONTINENTAL: 0.60,
    NEUTRA: 0.0,
}

#: Abaixo desta fracao da temporada jogada, a tabela ainda nao informa nada --
#: o 10o da rodada 3 nao esta' "perto do rebaixamento", esta' perto de tudo.
#: 0.30 e' onde a classificacao para de oscilar de forma violenta a cada
#: rodada; antes disso a camada devolve necessidade zero de proposito.
FRACAO_MINIMA_DA_TEMPORADA = 0.30

#: A partir daqui a temporada esta' madura o bastante pra que a tabela valha
#: por inteiro. Entre FRACAO_MINIMA e este ponto a necessidade cresce de forma
#: continua -- e' o que separa o 10o da rodada 5 do 10o da rodada 35, que era
#: exatamente o caso que o usuario levantou.
FRACAO_DE_MATURIDADE_TOTAL = 0.90

#: Pontos por vitoria -- explicito porque a conta de "pontos ainda em disputa"
#: depende dele e a constante solta no meio da formula esconde a premissa.
PONTOS_POR_VITORIA = 3


def classificar_zona(description: str | None) -> str:
    """Tipo de zona a partir da marcacao da API. Sem marcacao e' NEUTRA --
    meio de tabela nao tem descricao em liga nenhuma."""
    if not description:
        return NEUTRA
    for padrao, tipo in _ZONAS:
        if padrao.search(description):
            return tipo
    return NEUTRA


def mapear_zonas(tabela: list) -> list:
    """Faixas contiguas da tabela, cada uma com seu tipo.

    AGRUPA POR `description`, NAO POR TIPO -- e a diferenca importa. No
    Brasileirao a API marca 1o-4o como "Libertadores (Group Stage)", 5o como
    "Libertadores (Qualification)" e 6o-11o como "Sudamericana (Group Stage)".
    As tres viram CONTINENTAL, e a primeira versao deste modulo (2026-08-14)
    fundia as tres numa faixa unica de 1o a 11o -- apagando exatamente a
    fronteira do G4, que e' a linha pela qual meio campeonato joga. Validado
    contra a tabela real: o 2o colocado aparecia como se sua unica ameaca
    fosse cair pra 12o, a 16 pontos de distancia.

    A primeira posicao vira TITULO mesmo quando a API marca a faixa inteira
    como CONTINENTAL: ser campeao e' um objetivo separado de se classificar.
    """
    faixas: list = []
    for linha in tabela:
        tipo = classificar_zona(linha.get("description"))
        descricao = linha.get("description")
        if linha.get("rank") == 1 and tipo in (CONTINENTAL, NEUTRA):
            tipo = TITULO
        mesma_faixa = (
            faixas
            and faixas[-1]["tipo"] == tipo
            and faixas[-1]["description"] == descricao
            and faixas[-1]["rank_ate"] == (linha.get("rank") or 0) - 1
        )
        if mesma_faixa:
            faixas[-1]["rank_ate"] = linha["rank"]
            continue
        faixas.append({"tipo": tipo, "rank_de": linha.get("rank"),
                       "rank_ate": linha.get("rank"),
                       "description": descricao})
    return faixas


def rodadas_totais(tabela: list) -> int | None:
    """Turno e returno entre n times da 2*(n-1) rodadas. None com tabela
    pequena demais pra afirmar qualquer coisa.

    SO' VALE EM PONTOS CORRIDOS, e por isso `situacao` recusa competicao que
    nao seja LEAGUE antes de chegar aqui. A Sudamericana tem 32 times numa
    tabela unica de fase de grupos, onde cada um joga 6 partidas -- a formula
    devolveria 62 rodadas e um time com 6 jogos apareceria com 5% da temporada
    cumprida pra sempre. Hoje isso resulta em necessidade zero, que e' o
    numero certo; mas por acidente aritmetico, nao por decisao, e acidente que
    da o resultado certo e' o tipo de coisa que quebra na primeira mudanca.
    """
    n = len(tabela)
    if n < 4:
        return None
    return 2 * (n - 1)


def pontos_da_forma(form: str | None) -> dict | None:
    """Le "DWLWW" (mais recente a DIREITA, formato da API-Football).

    Devolve os pontos dos ultimos jogos e a comparacao com o ritmo da
    temporada -- um time em queda perto da fronteira esta' sob mais pressao
    que um time no mesmo ponto vindo de tres vitorias.
    """
    if not form:
        return None
    letras = [c for c in form.upper() if c in ("W", "D", "L")]
    if not letras:
        return None
    pontos = sum({"W": 3, "D": 1, "L": 0}[c] for c in letras)
    return {
        "jogos": len(letras),
        "pontos": pontos,
        "por_jogo": round(pontos / len(letras), 3),
        "sequencia": "".join(letras),
    }


def _fronteira_mais_proxima(tabela: list, zonas: list, linha: dict, para_cima: bool) -> dict | None:
    """A fronteira de zona mais proxima, e quantos pontos separam dela.

    Pra cima: o time olha a primeira posicao de uma zona MELHOR e mede quanto
    falta pra alcancar quem a ocupa por ultimo. Pra baixo: olha a primeira
    posicao de uma zona PIOR e mede a folga ate quem a ocupa primeiro.

    Devolve None quando nao ha zona diferente naquele sentido -- lider nao tem
    o que perseguir, lanterna nao tem pra onde cair.
    """
    rank = linha.get("rank")
    pontos = linha.get("points")
    if rank is None or pontos is None:
        return None

    minha = next((z for z in zonas if z["rank_de"] <= rank <= z["rank_ate"]), None)
    if minha is None:
        return None

    if para_cima:
        candidatas = [z for z in zonas if z["rank_ate"] < rank]
        alvo = candidatas[-1] if candidatas else None   # a imediatamente acima
    else:
        candidatas = [z for z in zonas if z["rank_de"] > rank]
        alvo = candidatas[0] if candidatas else None    # a imediatamente abaixo
    if alvo is None:
        return None

    # Quem ocupa a posicao de fronteira: o ultimo da zona de cima (pra
    # alcancar) ou o primeiro da zona de baixo (pra nao ser alcancado).
    alvo_rank = alvo["rank_ate"] if para_cima else alvo["rank_de"]
    ocupante = next((l for l in tabela if l.get("rank") == alvo_rank), None)
    if ocupante is None or ocupante.get("points") is None:
        return None

    distancia = (ocupante["points"] - pontos) if para_cima else (pontos - ocupante["points"])
    # O PESO DA FRONTEIRA E' O DO LADO MAIS PESADO, nao o do destino.
    #
    # Pesar so' o destino invertia o campeonato inteiro (validado contra a
    # tabela real do Brasileirao em 2026-08-14): quem esta' DENTRO do Z4 tem
    # como alvo a zona NEUTRA, que pesa 0 -- entao o lanterna aparecia com
    # menos necessidade que o 12o colocado, que enxergava o Z4 como risco
    # abaixo e pesava 1.0. Atravessar a linha do rebaixamento e' grave nos
    # DOIS sentidos, e o mesmo vale pra sair ou cair da zona de acesso.
    tipo_da_fronteira = max(
        (alvo["tipo"], minha["tipo"]),
        key=lambda t: _PESO_DA_FRONTEIRA.get(t, 0.0),
    )
    peso = _PESO_DA_FRONTEIRA.get(tipo_da_fronteira, 0.0)
    if peso <= 0:
        return None
    return {
        "tipo": alvo["tipo"],
        "tipo_de_origem": minha["tipo"],
        # A IDENTIDADE da fronteira, que nao e' a do destino. O 16o (fora do
        # Z4) e o 17o (dentro) disputam a MESMA linha -- um pra nao entrar,
        # outro pra sair -- mas o destino de um e' "rebaixamento" e o do outro
        # e' "neutra". Comparar por destino dizia que os dois brigavam por
        # coisas diferentes, quando brigam exatamente pela mesma.
        "tipo_da_fronteira": tipo_da_fronteira,
        "description": alvo["description"],
        "rank_da_fronteira": alvo_rank,
        "pontos_de_distancia": distancia,
        "peso": peso,
    }


def maturidade(fracao_jogada: float) -> float:
    """0-1: quanto a tabela ja' significa alguma coisa nesta altura do ano.

    Rampa continua entre FRACAO_MINIMA_DA_TEMPORADA e FRACAO_DE_MATURIDADE_
    TOTAL. Era um corte binario na primeira versao, e o corte binario nao
    resolvia o problema: passada a rodada 12, a rodada 13 e a rodada 37 valiam
    igual.
    """
    if fracao_jogada <= FRACAO_MINIMA_DA_TEMPORADA:
        return 0.0
    span = FRACAO_DE_MATURIDADE_TOTAL - FRACAO_MINIMA_DA_TEMPORADA
    return round(min(1.0, (fracao_jogada - FRACAO_MINIMA_DA_TEMPORADA) / span), 4)


def _urgencia(fronteira: dict | None, pontos_em_disputa: int, madura: float) -> float:
    """0-1: quanto aquela fronteira pesa AGORA.

    TRES COISAS, E A PRIMEIRA VERSAO CONFUNDIA DUAS DELAS
    ----------------------------------------------------
      APERTO      quao pequena e' a diferenca, em pontos. E' absoluto, nao
                  relativo: 2 pontos e' pouco em qualquer rodada.
      ALCANCE     a diferenca ainda cabe no que resta? 14 pontos com 4 rodadas
                  nao e' uma disputa, e' aritmetica encerrada.
      MATURIDADE  quanto do campeonato ja' passou.

    A primeira versao (2026-08-14) usava so' `distancia / pontos_em_disputa` e
    chamava isso de proximidade -- mas essa razao mede se a diferenca e'
    RECUPERAVEL, nao se ela e' urgente. O efeito, medido contra a tabela real
    da Serie B: no meio da temporada, com 51 pontos ainda em disputa, dez times
    de meio de tabela apareciam entre 0.74 e 0.92 de necessidade, porque
    qualquer diferenca de 1 a 8 pontos era "pequena" perto de 51. Recuperavel
    eles eram; urgentes, nao.
    """
    if not fronteira or pontos_em_disputa <= 0 or madura <= 0:
        return 0.0
    peso = fronteira["peso"]
    if peso <= 0:
        return 0.0

    distancia = max(0, fronteira["pontos_de_distancia"])
    if distancia > pontos_em_disputa:
        return 0.0                      # fora de alcance: nao e' mais disputa

    # 0 pontos -> 1.00 | 3 pontos (uma vitoria) -> 0.50 | 9 pontos -> 0.25
    aperto = 1.0 / (1.0 + distancia / PONTOS_POR_VITORIA)
    return round(aperto * peso * madura, 4)


def vale_para_a_competicao(league_id) -> bool:
    """Esta camada so' descreve PONTOS CORRIDOS.

    Copa de clube, torneio de selecao e eliminatoria tem tabela coletada, mas
    ela nao e' uma temporada: e' uma fase de grupos curta dentro de um
    mata-mata, onde "rodadas restantes" e "distancia ate o rebaixamento" nao
    querem dizer nada. Quem descreve essas partidas e' match_context_model,
    pelo agregado -- e' outro modulo porque e' outra pergunta.
    """
    return get_profile(league_id).type == "LEAGUE"


def situacao(tabela: list, team_id: int) -> dict:
    """Retrato competitivo de um time: onde esta', o que persegue, do que foge
    e quanto disso e' urgente.

    Sempre devolve os numeros brutos junto do score -- a explicacao do pick
    precisa poder dizer "a 2 pontos do Z4 com 4 rodadas restantes", nao apenas
    "pressao alta".
    """
    vazio = {"disponivel": False, "necessidade": 0.0, "motivo": None}
    if not tabela:
        return {**vazio, "motivo": "sem tabela da competicao"}

    linha = next((l for l in tabela if l.get("team_id") == team_id), None)
    if linha is None:
        return {**vazio, "motivo": "time fora da tabela desta competicao"}

    total_rodadas = rodadas_totais(tabela)
    jogadas = linha.get("played")
    if total_rodadas is None or jogadas is None:
        return {**vazio, "motivo": "sem rodadas jogadas/totais pra medir o que resta"}

    restantes = max(0, total_rodadas - jogadas)
    em_disputa = restantes * PONTOS_POR_VITORIA
    fracao_jogada = jogadas / total_rodadas if total_rodadas else 0.0

    zonas = mapear_zonas(tabela)
    alvo = _fronteira_mais_proxima(tabela, zonas, linha, para_cima=True)
    risco = _fronteira_mais_proxima(tabela, zonas, linha, para_cima=False)
    minha_zona = next((z for z in zonas if z["rank_de"] <= linha["rank"] <= z["rank_ate"]), None)

    base = {
        "disponivel": True,
        "team_id": team_id,
        "rank": linha.get("rank"),
        "points": linha.get("points"),
        "played": jogadas,
        "rodadas_totais": total_rodadas,
        "rodadas_restantes": restantes,
        "pontos_em_disputa": em_disputa,
        "fracao_da_temporada": round(fracao_jogada, 4),
        "zona_atual": (minha_zona or {}).get("tipo", NEUTRA),
        "alvo_acima": alvo,
        "risco_abaixo": risco,
        "forma": pontos_da_forma(linha.get("form")),
        "motivo": None,
    }

    madura = maturidade(fracao_jogada)
    base["maturidade"] = madura

    # Comeco de temporada: a tabela existe mas nao informa. Devolver os numeros
    # e' util pra explicacao; devolver necessidade > 0 seria inventar sinal.
    if madura <= 0:
        return {**base, "necessidade": 0.0,
                "motivo": f"temporada com {fracao_jogada:.0%} jogada, tabela ainda nao informa"}
    if restantes <= 0:
        return {**base, "necessidade": 0.0, "motivo": "competicao encerrada para este time"}

    urgencia_alvo = _urgencia(alvo, em_disputa, madura)
    urgencia_risco = _urgencia(risco, em_disputa, madura)

    # Fugir do rebaixamento aperta mais que perseguir uma vaga: por isso a
    # necessidade e' a MAIOR das duas, e nao a soma. Somar faria um time de
    # meio de tabela -- perto das duas fronteiras e longe de decidir qualquer
    # uma -- parecer mais pressionado que um lanterna.
    necessidade = max(urgencia_alvo, urgencia_risco)

    # Estar DENTRO da zona de rebaixamento e' a propria emergencia, mesmo
    # quando a fronteira de saida esta' longe. O piso acompanha a maturidade
    # pelo mesmo motivo que todo o resto: estar em ultimo na rodada 12 nao e'
    # a mesma coisa que estar em ultimo na rodada 36.
    if base["zona_atual"] == REBAIXAMENTO:
        necessidade = max(necessidade, 0.55 * madura)

    # Sequencia recente modula, nao decide. Um time em queda livre perto da
    # fronteira esta' sob mais pressao que o mesmo time vindo de vitorias --
    # e' o unico lugar em que `form` entra.
    forma = base["forma"]
    if forma and necessidade > 0:
        # 1.0 ponto por jogo e' o ritmo de quem se salva; 2.0 e' ritmo de G4.
        if forma["por_jogo"] <= 0.8:
            necessidade = min(1.0, necessidade * 1.15)
        elif forma["por_jogo"] >= 2.0:
            necessidade = necessidade * 0.90

    return {**base, "necessidade": round(min(necessidade, 1.0), 4),
            "urgencia_alvo": urgencia_alvo, "urgencia_risco": urgencia_risco}


def confronto_direto(situacao_home: dict, situacao_away: dict) -> dict:
    """Os dois times brigam pela MESMA coisa? Confronto direto vale seis
    pontos na pratica -- some da conta do adversario o que entra na sua.

    Exige as duas situacoes disponiveis e um alvo/risco do mesmo tipo. Sem
    isso devolve False; ausencia de dado nunca vira evidencia de nada.
    """
    if not (situacao_home.get("disponivel") and situacao_away.get("disponivel")):
        return {"direto": False, "motivo": "situacao indisponivel para um dos lados"}

    zh, za = situacao_home.get("zona_atual"), situacao_away.get("zona_atual")
    if zh == za and zh != NEUTRA:
        return {"direto": True, "tipo": zh,
                "detalhe": f"os dois disputam a mesma faixa ({zh.lower()})"}

    def _tipos(s):
        return {(s.get("alvo_acima") or {}).get("tipo_da_fronteira"),
                (s.get("risco_abaixo") or {}).get("tipo_da_fronteira")} - {None}

    comuns = _tipos(situacao_home) & _tipos(situacao_away)
    if comuns:
        tipo = sorted(comuns, key=lambda t: -_PESO_DA_FRONTEIRA.get(t, 0))[0]
        return {"direto": True, "tipo": tipo,
                "detalhe": f"os dois disputam a mesma fronteira ({tipo.lower()})"}
    return {"direto": False, "motivo": "objetivos diferentes na tabela"}


def pressao_da_partida(tabela: list, home_team_id: int, away_team_id: int,
                       league_id=None) -> dict:
    """A leitura da PARTIDA, que e' o que os modelos consomem.

    Tres numeros, e cada um descreve uma coisa diferente:

      intensidade  o quanto a partida importa pros dois somados. Um jogo entre
                   dois desesperados nao e' a media dos dois -- por isso e' a
                   maior necessidade com um acrescimo quando a outra tambem e'
                   alta, e nao a media simples.
      assimetria   um lado precisa e o outro nao. E' o cenario que ABRE o jogo
                   (quem precisa se lanca, quem nao precisa administra), e e'
                   diferente de dois times pressionados, que costuma travar.
      confronto_direto  os dois brigam pelo mesmo objetivo.
    """
    if league_id is not None and not vale_para_a_competicao(league_id):
        return {"disponivel": False, "intensidade": 0.0, "assimetria": 0.0,
                "home": None, "away": None,
                "motivo": "competicao nao e' de pontos corridos"}

    sh = situacao(tabela, home_team_id)
    sa = situacao(tabela, away_team_id)

    if not (sh.get("disponivel") and sa.get("disponivel")):
        return {"disponivel": False, "intensidade": 0.0, "assimetria": 0.0,
                "home": sh, "away": sa,
                "motivo": sh.get("motivo") or sa.get("motivo") or "sem classificacao"}

    nh, na = sh["necessidade"], sa["necessidade"]
    maior, menor = max(nh, na), min(nh, na)
    intensidade = round(min(1.0, maior + menor * 0.35), 4)
    assimetria = round(abs(nh - na), 4)
    direto = confronto_direto(sh, sa)
    if direto.get("direto"):
        # Seis pontos numa tabela so'. Acrescimo pequeno de proposito: o
        # confronto direto ja' esta' parcialmente refletido nas duas
        # necessidades, e contar duas vezes o mesmo sinal e' o erro que o
        # pre-jogo ja' pagou uma vez com K e M.
        intensidade = round(min(1.0, intensidade * 1.10), 4)

    return {
        "disponivel": True,
        "intensidade": intensidade,
        "assimetria": assimetria,
        "confronto_direto": direto,
        "home": sh,
        "away": sa,
        "motivo": None,
    }


def descrever(pressao: dict | None) -> list:
    """Frases derivadas dos numeros, pra explicacao de pick e de rejeicao.
    Campo ausente nao vira frase -- nunca se afirma o que nao foi medido."""
    if not pressao or not pressao.get("disponivel"):
        return []

    partes: list = []
    for lado, rotulo in (("home", "mandante"), ("away", "visitante")):
        s = pressao.get(lado) or {}
        if not s.get("disponivel") or s.get("necessidade", 0) < 0.25:
            continue
        risco = s.get("risco_abaixo") or {}
        alvo = s.get("alvo_acima") or {}
        restantes = s.get("rodadas_restantes")
        if s.get("zona_atual") == REBAIXAMENTO:
            partes.append(f"{rotulo} esta' na zona de rebaixamento com "
                          f"{restantes} rodadas restantes")
        elif risco.get("tipo") == REBAIXAMENTO and risco.get("pontos_de_distancia") is not None:
            partes.append(f"{rotulo} tem {risco['pontos_de_distancia']} ponto(s) de folga "
                          f"para o rebaixamento com {restantes} rodadas restantes")
        elif alvo.get("pontos_de_distancia") is not None:
            partes.append(f"{rotulo} esta' a {alvo['pontos_de_distancia']} ponto(s) da zona "
                          f"de {alvo['tipo'].lower()} com {restantes} rodadas restantes")

    direto = pressao.get("confronto_direto") or {}
    if direto.get("direto"):
        partes.append(direto["detalhe"])
    return partes
