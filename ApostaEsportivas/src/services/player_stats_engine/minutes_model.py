"""Minutos esperados, titularidade e risco de funcao -- o lado do JOGADOR.

POR QUE ISTO EXISTE (V2, 2026-09-11)
------------------------------------
Ate' aqui o motor resolvia minutos com UM filtro: `player_history.MIN_MINUTOS`
descarta atuacao abaixo de 60 e a media sai so' de jogo de titular efetivo. Isso
conserta o HISTORICO e nao diz nada sobre HOJE.

O buraco que sobrava:

  · um jogador que sempre joga 90 e um que sai sempre aos 62 entram na mesma
    media (as duas atuacoes passam no filtro) e saem com a mesma projecao;
  · um jogador em rodizio -- 90, 90, 25, 90, 18 -- tem media de titular alta e
    chance real de comecar no banco hoje. O corte de titularidade
    (MIN_TAXA_TITULARIDADE) pega o caso extremo; o rodizio de meio de tabela
    passa;
  · quem volta de lesao tem a media do jogador inteiro e 55 minutos de teto.

O motor NAO passa a normalizar o historico por minuto -- a decisao de
`player_history` continua valendo, e esta' escrita la': normalizar produz uma
media "por 90" que depois precisa ser desnormalizada por uma expectativa que
ninguem tem. O que muda e' que a expectativa PASSOU A EXISTIR, medida na
propria folha, e ela entra como um ajuste sobre a media de titular -- nao como
um regime novo de calculo.

O AJUSTE E' RELATIVO A' PROPRIA AMOSTRA
---------------------------------------
A media do historico ja' descreve um jogador que jogou, em media, `minutos
medios das atuacoes lidas`. Se a expectativa de hoje for a mesma, o fator e' 1.
O ajuste so' aparece quando hoje difere do regime que gerou a media -- que e'
exatamente o caso do jogador voltando de lesao. Comparar contra 90 fixo puniria
todo mundo que costuma sair aos 75.

CONTAGEM NAO E' PROPORCIONAL A MINUTO, E O FATOR SABE DISSO
-----------------------------------------------------------
Chute e falta nao se distribuem uniformemente no relogio, e um jogador que sai
aos 60 costuma ter jogado os 60 minutos mais intensos. Escalar linearmente
(70/90 = 0.78) exagera a queda. O expoente `ELASTICIDADE` amortece: 0.8 deixa
70 minutos valerem 0.82 da expectativa de 90, e nao 0.78.

Nao e' numero medido -- e' amortecimento declarado, com o valor neutro (1.0 =
linear) a uma constante de distancia. Quando houver medicao de contagem por
faixa de minuto ela entra aqui e em nenhum outro lugar.
"""
from __future__ import annotations

from utils.db_utils import linhas_dict

#: Janela de folhas lidas pro perfil de minutos. Mesma da titularidade em
#: `player_history` -- as duas respondem "como este jogador esta' sendo usado
#: AGORA", e responder com janelas diferentes produziria dois retratos do mesmo
#: jogador no mesmo pick.
JANELA_JOGOS = 10

#: Quanto a contagem acompanha o minuto. 1.0 e' proporcional puro; abaixo disso
#: a perda de minuto custa menos que o proporcional. Ver a docstring.
ELASTICIDADE = 0.8

#: Limites do fator. Nao ha' cenario em que minutos JUSTIFIQUEM inflar a
#: expectativa muito acima do regime que gerou a media (o teto e' 90 minutos e a
#: media ja' vem de titular), e um fator muito baixo esconderia, dentro de um
#: multiplicador, um caso que deveria ser NO_PICK -- e por isso ele tambem e'
#: contradicao em `contradiction.py`.
FATOR_MIN = 0.70
FATOR_MAX = 1.10

#: Abaixo disto o jogador nao tem regime de titular hoje, e prop de volume
#: deixa de fazer sentido. Mesma fronteira do historico (MIN_MINUTOS): se 59
#: minutos nao servem pra ENTRAR na media, nao servem pra sustentar o pick.
MINUTOS_MINIMOS = 60


def perfil(cur, player_id: int, *, league_id=None, season=None,
           janela: int = JANELA_JOGOS) -> dict:
    """Como o jogador vem sendo usado -- TODAS as folhas, inclusive as curtas.

    O filtro de 60 minutos do historico nao pode valer aqui: o que se quer medir
    e' justamente a frequencia das atuacoes curtas. Ler so' as longas devolveria
    "este jogador sempre joga 90" pra qualquer reserva que tenha entrado em
    quatro jogos inteiros no ano.
    """
    filtros, params = [], [player_id]
    if season is not None:
        filtros.append("AND season = %s")
        params.append(season)
    if league_id is not None:
        filtros.append("AND league_id = %s")
        params.append(league_id)

    cur.execute(f"""
        SELECT fixture_id, match_date, COALESCE(minutes, 0) AS minutes,
               is_substitute, position
          FROM player_match_stats
         WHERE player_id = %s
           {" ".join(filtros)}
      ORDER BY match_date DESC
         LIMIT %s
    """, tuple(params) + (janela,))
    folhas = linhas_dict(cur)
    if not folhas:
        return {"amostra": 0, "minutos_medios": None, "minutos_ultimo": None,
                "jogos_completos": 0, "titularidades": 0, "curtas": 0,
                "posicoes": [], "erro": None}

    minutos = [int(f.get("minutes") or 0) for f in folhas]
    titular = [f for f in folhas if f.get("is_substitute") is not True]
    posicoes = [f.get("position") for f in folhas if f.get("position")]
    return {
        "amostra": len(folhas),
        "minutos_medios": round(sum(minutos) / len(minutos), 1),
        "minutos_ultimo": minutos[0],
        "minutos_serie": minutos,
        # 85 e nao 90: substituicao aos 87 nao e' rodizio, e' o jogo acabando.
        "jogos_completos": sum(1 for m in minutos if m >= 85),
        "titularidades": len(titular),
        "minutos_como_titular": (
            round(sum(int(f.get("minutes") or 0) for f in titular) / len(titular), 1)
            if titular else None),
        #: Atuacao curta com o jogador em campo -- entrou no segundo tempo ou
        #: saiu cedo. Zero minuto e' AUSENCIA (suspenso, lesionado, banco sem
        #: entrar) e conta em outro lugar: misturar os dois faria "nao foi
        #: relacionado" parecer "foi substituido".
        "curtas": sum(1 for m in minutos if 0 < m < MINUTOS_MINIMOS),
        "ausencias": sum(1 for m in minutos if m == 0),
        "posicoes": sorted(set(posicoes)),
        "erro": None,
    }


def minutos_esperados(perfil_min: dict) -> float | None:
    """Quantos minutos o jogador deve jogar hoje, SE comecar.

    E' a media das atuacoes em que ele COMECOU, e nao a media geral: a geral
    mistura o regime que se quer prever (titular) com o que ja' foi descartado
    do historico (entrada no segundo tempo), e devolve um numero que nao
    descreve nenhum dos dois.

    `None` sem folha nenhuma -- ausencia de dado sai como ausencia, e quem
    decide o que fazer com ela e' o gate, nao esta funcao (§33).
    """
    if not perfil_min or not perfil_min.get("amostra"):
        return None
    como_titular = perfil_min.get("minutos_como_titular")
    if como_titular:
        return float(como_titular)
    return float(perfil_min.get("minutos_medios") or 0) or None


def fator_de_minutos(esperados: float | None, minutos_da_amostra: float | None) -> float:
    """Multiplicador da expectativa, pelo regime de minutos de hoje.

    1.0 quando hoje e' o mesmo regime que gerou a media -- que e' o caso comum,
    e por isso o motor nao fica mais conservador de graca com esta camada.
    """
    if not esperados or not minutos_da_amostra or minutos_da_amostra <= 0:
        return 1.0
    razao = float(esperados) / float(minutos_da_amostra)
    fator = razao ** ELASTICIDADE
    return round(min(max(fator, FATOR_MIN), FATOR_MAX), 4)


def risco_de_minutos(perfil_min: dict, jogador: dict) -> str:
    """LOW · MEDIUM · HIGH -- o quanto a expectativa de minutos pode falhar.

    Nao e' probabilidade, e' classe: entra no gate (HIGH reprova) e na
    explicacao. Um numero continuo aqui daria impressao de precisao que a folha
    de jogo nao sustenta.
    """
    if not perfil_min or not perfil_min.get("amostra"):
        return "HIGH"

    n = perfil_min["amostra"]
    curtas = perfil_min.get("curtas") or 0
    ausencias = perfil_min.get("ausencias") or 0
    completos = perfil_min.get("jogos_completos") or 0
    taxa_titular = jogador.get("taxa_titularidade")
    taxa_titular = float(taxa_titular) if taxa_titular is not None else None

    # Sinal duro primeiro: quem nao esteve disponivel em boa parte da janela
    # tem risco de minutos alto por motivo que a media nao mostra (lesao,
    # suspensao, fora do grupo).
    if ausencias >= max(3, n // 2):
        return "HIGH"
    if (curtas + ausencias) / n >= 0.4:
        return "HIGH"
    if taxa_titular is not None and taxa_titular < 0.60:
        return "HIGH" if taxa_titular < 0.50 else "MEDIUM"
    if completos / n >= 0.6 and (curtas + ausencias) <= 1:
        return "LOW"
    if (curtas + ausencias) / n <= 0.2:
        return "MEDIUM" if completos / n < 0.4 else "LOW"
    return "MEDIUM"


def risco_de_funcao(perfil_min: dict, atuacoes: list, metodo) -> tuple:
    """(role_risk, posicao) -- o cargo em que ele joga condiz com a prop?

    A folha traz `position` por partida, entao "mudou de funcao" e' medido e nao
    inferido do nome. Um volante escalado de zagueiro em tres dos ultimos dez
    jogos nao e' o mesmo jogador pra uma prop de desarme.
    """
    posicoes = [a.get("position") for a in (atuacoes or []) if a.get("position")]
    posicoes += [p for p in (perfil_min.get("posicoes") or [])]
    distintas = sorted(set(posicoes))
    principal = None
    if posicoes:
        principal = max(distintas, key=posicoes.count)

    if not distintas:
        return ("HIGH", None)
    # Posicao exigida pelo metodo (goleiro). Fora dela, a prop nao e' do mesmo
    # produto -- e o motor nao deveria nem ter chegado aqui.
    if metodo.posicoes and principal not in metodo.posicoes:
        return ("HIGH", principal)
    if len(distintas) >= 3:
        return ("HIGH", principal)
    if len(distintas) == 2:
        return ("MEDIUM", principal)
    return ("LOW", principal)


#: Como o motor le' a disponibilidade de hoje. A API-Football so' publica
#: escalacao OFICIAL (20 a 40 minutos antes do apito), e o motor roda muito
#: antes disso -- entao "CONFIRMADO TITULAR" nao e' um estado alcancavel aqui, e
#: fingir que e' seria inventar dado.
#:
#: A escada do §2 do V2 fica, com o topo que o dado permite:
#:
#:     PROVAVEL TITULAR   titularidade alta e minutos previsiveis
#:     ALTERNA            comeca as vezes -- prop de volume nao se sustenta
#:     RESERVA            comeca pouco
#:     DESCONHECIDO       sem folha suficiente pra dizer
#:
#: DESCONHECIDO NAO E' NEUTRO (§33). Ate' 10/09 o motor tratava ausencia de
#: titularidade como "segue o jogo" (`e_titular_provavel` devolvia True sem
#: `partidas_do_time`), com a justificativa de que ausencia de dado nao pode
#: virar veto. Pra prop que DEPENDE de o jogador comecar, essa justificativa se
#: inverte: o pick nasce afirmando titularidade, e se o motor nao sabe, quem
#: paga a conta e' o apostador. Vira NO_PICK no gate.
PROVAVEL = "PROVAVEL_TITULAR"
ALTERNA = "ALTERNA"
RESERVA = "RESERVA"
DESCONHECIDO = "DESCONHECIDO"


def status_de_titularidade(jogador: dict, perfil_min: dict) -> str:
    partidas = jogador.get("partidas_do_time") or 0
    taxa = jogador.get("taxa_titularidade")
    if partidas < 4 or taxa is None:
        return DESCONHECIDO
    taxa = float(taxa)
    if taxa >= 0.70:
        return PROVAVEL
    if taxa >= 0.40:
        # Comeca a maioria dos jogos recentes desempata pra cima: a taxa olha
        # 120 dias e o perfil olha 10 jogos, e quem acabou de virar titular
        # aparece primeiro no segundo.
        recentes = (perfil_min or {}).get("titularidades") or 0
        amostra = (perfil_min or {}).get("amostra") or 0
        if amostra >= 5 and recentes / amostra >= 0.8:
            return PROVAVEL
        return ALTERNA
    return RESERVA
