"""A chance de um pick de linha bater, refeita com o jogo rolando (09/10/2026).

PEDIDO DO USUARIO. A barra de probabilidade do card fica parada no numero de
antes do jogo. Com a bola rolando a pergunta muda ("escanteios +5.5, ja' tem 4
aos 60'"), e a barra tem que acompanhar. Acabou o jogo, ela volta ao numero de
antes, que e' o que o pick prometeu.

A CONTA, E POR QUE ELA E' ESSA. Nao ha' modelo ao vivo por pick (o motor ao
vivo e' outro produto e custa estatistica por jogo), e a decisao foi nao gastar
cota a mais. Entao a conta usa so' o que ja' esta' na mao:

  1. a probabilidade de antes do jogo, que o motor publicou;
  2. o contador de agora e o minuto, do cache que a varredura ja' mantem.

Do (1) sai a media que o pick supunha pro jogo inteiro: e' a lambda de uma
Poisson que da' exatamente aquela probabilidade naquela linha. O que falta
jogar recebe a fatia proporcional dessa media, e a chance e' a de o que falta
cobrir (ou nao estourar) a distancia ate' a linha.

E' uma ESTIMATIVA, e a tela diz isso. Ela nao sabe que o jogo esta' mais
movimentado que o esperado (usa o ritmo de antes do jogo, nao o de agora) e
trata contagem como Poisson. Para gols e escanteios isso e' razoavel; para o
resto e' aproximacao. O que ela acerta sempre e' o essencial: linha ja' batida
vale 100%, linha estourada vale 0%, e o resto anda conforme o relogio corre.
"""
from __future__ import annotations

import math

#: Status em que a bola esta' (ou ainda vai estar) rolando nos 90 minutos.
_PRIMEIRO_TEMPO = {"1H"}
_INTERVALO = {"HT"}
_SEGUNDO_TEMPO = {"2H"}
#: Depois dos 90: prorrogacao e penaltis nao contam pra casa.
_DEPOIS_DOS_90 = {"ET", "BT", "P", "AET", "PEN", "FT"}

#: Acrescimo: o relogio passa do 45/90 e ainda ha' jogo. Dois minutos e' o
#: minimo que se assume ate' o apito, pra a chance nao cravar 0/100 cedo demais.
_MINIMO_RESTANTE = 2.0


def _poisson_ate(k: int, lam: float) -> float:
    """P(X <= k) para X ~ Poisson(lam)."""
    if k < 0:
        return 0.0
    if lam <= 0:
        return 1.0
    termo = math.exp(-lam)
    soma = termo
    for i in range(1, k + 1):
        termo *= lam / i
        soma += termo
    return min(1.0, soma)


def _alvo(direcao: str, linha: float, atual: float = 0.0):
    """Quanto ainda precisa sair. over: precisa de >= k; under: pode sair <= k.

    Linha cheia (9.0) empata em 9: a casa devolve, e aqui o empate conta como
    nao-vitoria nos dois lados (a barra e' a chance de GANHAR)."""
    falta = linha - atual
    if direcao == "over":
        return math.floor(falta) + 1          # Y >= k
    return math.ceil(falta) - 1               # Y <= k


def lambda_do_pre_jogo(prob: float, direcao: str, linha: float) -> float | None:
    """A media que faz P(ganhar) = prob numa Poisson, por bissecao.

    over: P(X >= k) cresce com lambda; under: P(X <= k) cai com lambda."""
    if not (0.0 < prob < 1.0) or direcao not in ("over", "under") or linha is None:
        return None
    k = _alvo(direcao, linha)
    if direcao == "under" and k < 0:
        return None

    def p(lam):
        return 1 - _poisson_ate(k - 1, lam) if direcao == "over" else _poisson_ate(k, lam)

    lo, hi = 1e-4, 80.0
    for _ in range(80):
        meio = (lo + hi) / 2
        cresce = p(meio) < prob if direcao == "over" else p(meio) > prob
        if cresce:
            lo = meio
        else:
            hi = meio
    return (lo + hi) / 2


def fracao_restante(status: str | None, minuto, periodo: str) -> float | None:
    """Que parte do trecho apostado ainda falta jogar (0..1). None = nao sei.

    periodo: 'total', '1t' ou '2t'."""
    m = float(minuto) if minuto is not None else None
    if status in _DEPOIS_DOS_90:
        return 0.0
    if periodo == "1t":
        if status in _PRIMEIRO_TEMPO:
            return max(45 - (m if m is not None else 0), _MINIMO_RESTANTE) / 45
        return 0.0 if status in _INTERVALO | _SEGUNDO_TEMPO else None
    if periodo == "2t":
        if status in _PRIMEIRO_TEMPO | _INTERVALO:
            return 1.0
        if status in _SEGUNDO_TEMPO:
            return max(90 - (m if m is not None else 45), _MINIMO_RESTANTE) / 45
        return None
    if status in _INTERVALO:
        return 0.5
    if status in _PRIMEIRO_TEMPO | _SEGUNDO_TEMPO:
        return max(90 - (m if m is not None else 0), _MINIMO_RESTANTE) / 90
    return None


def chance_agora(prob, direcao: str | None, linha, atual, status: str | None,
                 minuto, periodo: str = "total") -> float | None:
    """A chance de ganhar agora, de 0 a 1, ou None se nao da' pra estimar."""
    if prob is None or linha is None or atual is None or direcao not in ("over", "under"):
        return None
    prob, linha, atual = float(prob), float(linha), float(atual)
    # Ja' decidido pelo contador: nao depende de modelo nenhum.
    if direcao == "over" and atual > linha:
        return 1.0
    if direcao == "under" and atual >= linha:
        return 0.0
    f = fracao_restante(status, minuto, periodo)
    lam = lambda_do_pre_jogo(prob, direcao, linha)
    if f is None or lam is None:
        return None
    resto = lam * f
    k = _alvo(direcao, linha, atual)
    if direcao == "over":
        p = 1 - _poisson_ate(k - 1, resto)
    else:
        p = _poisson_ate(k, resto)
    return round(max(0.0, min(1.0, p)), 3)
