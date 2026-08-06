"""Calibracao de probabilidade por regressao isotonica (algoritmo PAVA).

O PROBLEMA QUE ISTO RESOLVE
--------------------------
Nenhum modelo sai calibrado de fabrica. O motor pode declarar 70% e acertar
55% naquela faixa -- ordena bem os candidatos e mente sobre o nivel. EV e
Kelly consomem o NIVEL, nao a ordem, entao um modelo mal calibrado dimensiona
aposta errado mesmo escolhendo o mercado certo.

`calibration.py` (existente) ja' faz uma versao disso com um numero so' por
mercado: um delta aplicado ao confidence. Isso corrige a media, mas nao a
FORMA da curva -- um mercado pode ser otimista em 80% e pessimista em 55% ao
mesmo tempo, e um delta unico nao alcanca esse caso. Aqui a curva inteira e'
ajustada.

POR QUE ISOTONICA E NAO PLATT
-----------------------------
Platt scaling ajusta uma sigmoide de 2 parametros: e' robusto com pouca
amostra, mas impoe uma forma. A isotonica so' impoe MONOTONICIDADE (se o
modelo diz mais, tem que acontecer mais) e deixa os dados escolherem o resto.
Como a monotonicidade e' a unica propriedade que realmente se quer preservar
-- ela garante que a calibracao NUNCA reordena candidatos, so' corrige nivel
-- a isotonica e' a escolha certa aqui.

O preco e' amostra: com poucos pontos a isotonica decora. Por isso
`fit()` exige um minimo e devolve None abaixo dele, e a aplicacao interpola
linearmente entre os degraus em vez de usar a funcao escada crua (degrau puro
produz saltos de probabilidade que viram saltos de stake).

NAO REORDENA, ENTAO E' SEGURO
-----------------------------
Uma transformacao monotonica nao troca a ordem de nenhum par de candidatos.
Ligar a calibracao muda quanto se aposta, nunca em que se aposta. E' a
alteracao de menor risco entre todas as propostas do documento V2, e por isso
a primeira a ser implementada.
"""
from __future__ import annotations

# Amostra minima pra ajustar uma curva. Abaixo disso a isotonica decora os
# proprios pontos e a "calibracao" viraria ruido amplificado. 30 e' o piso
# usual pra este tipo de ajuste; com menos, `calibration.calibration_adjustment`
# (delta unico, encolhido por evidencia) continua sendo a ferramenta certa.
MIN_AMOSTRA_FIT = 30


def _pava(y: list[float], w: list[float]) -> list[float]:
    """Pool Adjacent Violators: menor ajuste monotono nao-decrescente de `y`
    ponderado por `w`, em tempo linear.

    Percorre da esquerda pra direita mantendo uma pilha de blocos; sempre que
    o bloco novo viola a monotonicidade contra o anterior, funde os dois na
    media ponderada e reavalia. E' a solucao exata de minimos quadrados sob
    restricao de monotonicidade, nao uma heuristica.
    """
    # Cada bloco e' [soma_ponderada, peso_total]; o valor e' soma/peso.
    blocos: list[list[float]] = []
    for valor, peso in zip(y, w):
        blocos.append([valor * peso, peso])
        # Funde enquanto o bloco anterior tiver media MAIOR que a do atual.
        while len(blocos) > 1 and (blocos[-2][0] / blocos[-2][1]) > (blocos[-1][0] / blocos[-1][1]):
            s2, w2 = blocos.pop()
            blocos[-1][0] += s2
            blocos[-1][1] += w2

    resultado: list[float] = []
    for soma, peso in blocos:
        resultado.extend([soma / peso] * int(round(peso)))
    return resultado


class IsotonicCalibrator:
    """Curva de calibracao ajustada e aplicavel.

    Uso:
        cal = IsotonicCalibrator.fit(probabilidades, desfechos)
        p_calibrada = cal.predict(0.72) if cal else 0.72
    """

    def __init__(self, x: list[float], y: list[float], n: int):
        # Pontos de quebra da escada (x crescente, y monotono nao-decrescente).
        self.x = x
        self.y = y
        self.n = n

    # ------------------------------------------------------------------
    @classmethod
    def fit(cls, probabilidades: list[float], desfechos: list[int],
            min_amostra: int = MIN_AMOSTRA_FIT) -> "IsotonicCalibrator | None":
        """Ajusta a curva. None quando a amostra nao sustenta -- nunca
        devolve um calibrador fraco que o chamador aplicaria sem saber.

        `desfechos` e' 1 pra GREEN e 0 pra RED. PUSH nao entra (nao e' nem
        acerto nem erro da probabilidade declarada, mesmo criterio de
        metrics._binary_outcome).
        """
        pares = [
            (float(p), int(o))
            for p, o in zip(probabilidades, desfechos)
            if p is not None and o in (0, 1)
        ]
        if len(pares) < min_amostra:
            return None

        pares.sort(key=lambda t: t[0])
        xs = [p for p, _ in pares]
        ys = [float(o) for _, o in pares]
        ajustado = _pava(ys, [1.0] * len(ys))

        # Comprime degraus repetidos: a escada so' precisa dos pontos onde
        # o valor muda, e isso deixa predict() barato.
        bx, by = [], []
        for xi, yi in zip(xs, ajustado):
            if by and abs(by[-1] - yi) < 1e-12:
                bx[-1] = xi          # estende o degrau ate o ultimo x dele
                continue
            bx.append(xi)
            by.append(yi)

        return cls(bx, by, len(pares))

    # ------------------------------------------------------------------
    def predict(self, p: float | None) -> float | None:
        """Probabilidade calibrada, com interpolacao linear entre degraus.

        Fora do intervalo observado devolve o degrau da ponta (extrapolacao
        constante). Extrapolar linearmente aqui seria inventar comportamento
        numa regiao onde nao houve observacao -- e justamente nas pontas
        (probabilidade muito alta ou muito baixa) e' onde o erro custa mais.
        """
        if p is None or not self.x:
            return None
        valor = float(p)
        if valor <= self.x[0]:
            return round(self.y[0], 4)
        if valor >= self.x[-1]:
            return round(self.y[-1], 4)

        # Busca o intervalo que contem `valor`.
        baixo, alto = 0, len(self.x) - 1
        while alto - baixo > 1:
            meio = (baixo + alto) // 2
            if self.x[meio] <= valor:
                baixo = meio
            else:
                alto = meio

        x0, x1 = self.x[baixo], self.x[alto]
        y0, y1 = self.y[baixo], self.y[alto]
        if x1 == x0:
            return round(y1, 4)
        peso = (valor - x0) / (x1 - x0)
        return round(y0 + peso * (y1 - y0), 4)

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        """Serializa pra guardar junto do pick (auditoria: qual curva estava
        valendo quando esta aposta foi dimensionada)."""
        return {"x": self.x, "y": self.y, "n": self.n}

    @classmethod
    def from_dict(cls, d: dict | None) -> "IsotonicCalibrator | None":
        if not d or not d.get("x"):
            return None
        return cls(list(d["x"]), list(d["y"]), int(d.get("n", 0)))


def fit_por_grupo(linhas: list, chave: str,
                  min_amostra: int = MIN_AMOSTRA_FIT) -> dict:
    """Um calibrador por grupo (market_type, liga, o que for).

    `linhas` sao pernas do picks_ledger. Grupo sem amostra suficiente
    simplesmente nao entra no dicionario -- o chamador cai no comportamento
    nao calibrado, que e' o certo: melhor nao corrigir do que corrigir por
    ruido.
    """
    grupos: dict = {}
    for linha in linhas:
        resultado = str(linha.get("result") or "").upper()
        if resultado not in ("GREEN", "RED"):
            continue
        prob = linha.get("probability")
        if prob is None:
            continue
        grupos.setdefault(str(linha.get(chave)), []).append(
            (float(prob), 1 if resultado == "GREEN" else 0)
        )

    calibradores = {}
    for nome, pares in grupos.items():
        cal = IsotonicCalibrator.fit([p for p, _ in pares], [o for _, o in pares], min_amostra)
        if cal is not None:
            calibradores[nome] = cal
    return calibradores
