"""COMBINATION ENGINE -- a camada 3 da alavancagem, separada do motor simples.

POR QUE ESTE MODULO EXISTE
--------------------------
Ate' aqui a alavancagem tinha UM motor: `_find_combo` pegava as pernas que o
pick_engine aprovou individualmente, tentava dupla -> tripla -> simples, e
aceitava a primeira combinacao cujo PRODUTO DAS ODDS caisse em [1.40, 1.55],
desempatando pelo produto das confidences. Nenhuma pergunta era feita sobre a
combinacao em si: nem se as duas pernas se contradizem, nem se a probabilidade
do bilhete sobrevive a multiplicacao, nem se o risco de uma perna contamina a
outra. Duas pernas boas entravam e saiam "um bilhete bom" por construcao.

O QUE A MEDICAO DIZ (historico liquidado, base de DEV ate' 28/08)
-----------------------------------------------------------------
    simples       25 bilhetes   22 GREEN /  3 RED   +91.15u
    dupla          4 bilhetes    3 GREEN /  1 RED    -0.45u
    combinacao     2 bilhetes    1 GREEN /  1 RED    -0.50u

Seis combinacoes no total. E' amostra pequena demais pra calibrar limiar em
cima (§57), mas grande o bastante pra olhar o que cada RED foi -- e os DOIS
sao a mesma estrutura:

  21/06  "Over 1.5 gols" (Belgium x Iran) + "Over 0.5 gols do 2o tempo"
         (Spain x Saudi Arabia). Duas pernas `goals`, jogos diferentes,
         multiplicadas como independentes: 0.8988 x 0.9154 = 82%.
  23/08  "Under 3.5" (Ponte Preta x Avai) + "Under 4.5" (Palmeiras x Vasco).
         Duas pernas `goals`, jogos diferentes, mesma multiplicacao. As
         confidences gravadas foram 0.92 e 0.9148 -- as duas acima de 90% com
         amostra curta, que e' exatamente o que o §46 proibe.

Independentes no gramado, nao no MODELO: e' a mesma estimativa de gols
aplicada duas vezes, e a docstring do `_find_combo` antigo assumia esse buraco
por escrito ("erro sistematico do modelo... a escolha aqui e' explicita, nao
esquecimento"). As duas vezes que ele apareceu, ele custou o bilhete.

Nao vira proibicao: a terceira combinacao dessa estrutura (24/06, dois
mercados de resultado em jogos diferentes) foi GREEN, e 1G/2R nao sustenta um
veto (§57). Vira DESCONTO -- correlacao MEDIA, com o preco declarado em
`desconto_correlacao_media`.

A CONTA QUE MUDA TUDO
---------------------
A faixa da alavancagem ([1.40, 1.55]) e' do TOTAL do bilhete. Entao uma dupla
nesta faixa paga EXATAMENTE o mesmo que uma simples nesta faixa. Combinar nao
aumenta o retorno aqui: aumenta so' o numero de maneiras de perder.

Isso derruba a premissa implicita do motor antigo, que tentava dupla primeiro
"porque combo e' o formato preferido do produto". Nao existe premio pelo
formato. A combinacao so' se justifica em dois casos:

  1. NAO HA' SIMPLES NA FAIXA. E' a razao original do formato existir -- em
     30/07 a melhor perna do dia estava a 1.39 contra um piso de 1.40, e o dia
     ficou sem produto por um centavo. Duas pernas baratas alcancam a faixa.
  2. A COMBINACAO TEM PROBABILIDADE MAIOR QUE A MELHOR SIMPLES, pelo mesmo
     preco. Acontece quando a simples disponivel na faixa e' cara em risco e
     duas pernas muito seguras se multiplicam pra um numero melhor.

Fora desses dois casos, combinar e' trocar probabilidade por nada. E' o §52
("nao forcar alavancagem") escrito como aritmetica, e nao como preferencia.

O QUE ESTE MODULO NAO FAZ
-------------------------
Nao toca no motor individual. Probabilidade, encolhimento bayesiano, edge, EV,
escolha de linha e confidence continuam saindo inteiros do pick_engine (§3). O
que entra aqui ja' passou por todos os gates de la'; este modulo so' responde
uma pergunta que ninguem estava fazendo: "estas pernas continuam boas JUNTAS?"
"""
from dataclasses import dataclass

from services.pick_engine import ranking
from services.pick_engine.variance_model import CV_HIGH_THRESHOLD


# ---------------------------------------------------------------------------
# §8  CLASSIFICACAO DE AMOSTRA
#
# O motor ja' encolhe a taxa pela amostra (bayesian_model, dentro do
# pick_engine) -- este mapa NAO encolhe de novo, senao a mesma evidencia seria
# cobrada duas vezes. Ele responde outra coisa: quanto credito a estimativa
# merece como PECA DE UM BILHETE, onde o erro de uma perna multiplica o da
# outra em vez de se diluir.
# ---------------------------------------------------------------------------
_AMOSTRA_TIERS = (
    (30, "forte",       100.0),
    (20, "boa",          80.0),
    (10, "razoavel",     60.0),
    (5,  "limitada",     35.0),
    (0,  "muito_fraca",   0.0),
)


def classificar_amostra(n: int | None) -> dict:
    """(classe, score 0-100) da amostra. `None` cai em muito_fraca: dado
    ausente nunca e' tratado como favoravel."""
    n = int(n or 0)
    for piso, classe, score in _AMOSTRA_TIERS:
        if n >= piso:
            return {"n": n, "classe": classe, "score": score}
    return {"n": n, "classe": "muito_fraca", "score": 0.0}


# ---------------------------------------------------------------------------
# §15 / §16 / §26 / §27  CORRELACAO
#
# A chave do veto antigo era (fixture_id, correlation_group): duas pernas so'
# se excluiam quando falavam do mesmo jogo E da mesma familia. Isso deixava
# dois buracos, os dois com RED no historico:
#
#   MESMO JOGO, FAMILIAS DIFERENTES -- "Over 2.5 gols" + "Casa vence" nao sao
#     a mesma familia, mas sao o mesmo jogo e a mesma causa (o ataque da casa
#     funcionando). Nenhum veto pegava, e o bilhete de 28/06 foi exatamente
#     isso: "South Africa x Canada: Away" + "South Africa x Canada: Under 3.5".
#     Saiu GREEN -- o que nao o torna um bilhete correto, so' um que deu certo:
#     o motor anunciou 0.78 x 0.82 = 64% pra dois eventos que o placar decide
#     juntos.
#   JOGOS DIFERENTES, MESMA FAMILIA -- independentes no gramado, nao no
#     modelo. Se a estimativa de gols estiver enviesada hoje, as duas erram
#     juntas. A docstring do `_find_combo` antigo assumia esse buraco de
#     proposito ("o preco medido foi ficar sem produto na maioria dos dias").
#     Com a faixa do bilhete sendo a mesma da simples, esse preco nao se paga
#     mais: quando nao ha' combo seguro, a simples entrega o mesmo retorno.
#
# O mapa abaixo e' de MECANISMO, nao de medicao -- cada par esta' aqui porque
# ha' uma causa fisica comum, nomeada. Par que nao esta' no mapa dentro do
# MESMO jogo e' DESCONHECIDO, nunca independente (§16).
# ---------------------------------------------------------------------------
BAIXA = "LOW"
MEDIA = "MEDIUM"
ALTA = "HIGH"
DESCONHECIDA = "UNKNOWN"

#: Pares de familias DENTRO DO MESMO JOGO, com o mecanismo que os liga.
_CORRELACAO_MESMO_JOGO = {
    # O placar e o vencedor sao o mesmo evento visto de dois angulos.
    frozenset(("goals", "result")): (ALTA, "o vencedor sai do placar"),
    # Volume ofensivo e' a causa comum de gol, chute e chute no alvo.
    frozenset(("goals", "shots")): (ALTA, "gol e chute saem do mesmo volume ofensivo"),
    # Defesa de goleiro = chute no alvo sofrido que nao virou gol. A relacao e'
    # quase mecanica: 0.678 defesas por chute no alvo, correlacao 0.88 medida
    # em 1892 atuacoes (ver goalkeeper_model.py).
    frozenset(("saves", "shots")): (ALTA, "defesa e' chute no alvo que nao entrou"),
    frozenset(("goals", "saves")): (ALTA, "gol e defesa dividem o mesmo chute no alvo"),
    # Cartao nasce de falta. Nao ha' como separar os dois no mesmo jogo.
    frozenset(("cards", "fouls")): (ALTA, "cartao nasce de falta"),
    # Escanteio vem de ataque interrompido -- mesma fonte que chute.
    frozenset(("corners", "shots")): (ALTA, "escanteio vem de ataque que virou chute bloqueado"),

    # Ligacao real, mas com folga: a causa comum explica parte, nao tudo.
    frozenset(("corners", "goals")): (MEDIA, "pressao ofensiva move os dois"),
    frozenset(("corners", "result")): (MEDIA, "quem pressiona tende a vencer"),
    frozenset(("cards", "result")): (MEDIA, "o placar muda a intensidade"),
    frozenset(("fouls", "result")): (MEDIA, "quem defende vantagem falta mais"),
    frozenset(("cards", "goals")): (MEDIA, "jogo aberto e jogo faltoso sao regimes ligados"),
    frozenset(("fouls", "goals")): (MEDIA, "jogo aberto e jogo faltoso sao regimes ligados"),
    frozenset(("cards", "corners")): (MEDIA, "intensidade da partida move os dois"),
    frozenset(("fouls", "corners")): (MEDIA, "intensidade da partida move os dois"),
    frozenset(("offsides", "goals")): (MEDIA, "linha alta e ataque em profundidade"),
    frozenset(("offsides", "shots")): (MEDIA, "volume de ataque move os dois"),
    frozenset(("saves", "corners")): (MEDIA, "pressao ofensiva move os dois"),
    frozenset(("saves", "result")): (MEDIA, "quem sofre pressao tende a nao vencer"),
    frozenset(("cards", "saves")): (MEDIA, "intensidade da partida move os dois"),
    frozenset(("fouls", "saves")): (MEDIA, "intensidade da partida move os dois"),
    frozenset(("cards", "shots")): (MEDIA, "intensidade da partida move os dois"),
    frozenset(("fouls", "shots")): (MEDIA, "intensidade da partida move os dois"),
    frozenset(("offsides", "corners")): (MEDIA, "volume de ataque move os dois"),
    frozenset(("offsides", "result")): (MEDIA, "quem ataca mais fica impedido mais"),
    frozenset(("offsides", "cards")): (MEDIA, "intensidade da partida move os dois"),
    frozenset(("offsides", "fouls")): (MEDIA, "intensidade da partida move os dois"),
    frozenset(("offsides", "saves")): (MEDIA, "volume de ataque move os dois"),
}


def _familia(leg: dict) -> str:
    return ranking.correlation_group(leg.get("market_type") or "")


def _fixture_id(leg: dict) -> int | None:
    return (leg.get("_fixture") or {}).get("fixture_id")


def _direcao(leg: dict) -> str:
    return (leg.get("_direction") or "").strip().lower()


def classificar_correlacao(a: dict, b: dict) -> dict:
    """Correlacao entre DUAS pernas: nivel, mecanismo e o sinal da dependencia.

    `sinal` diz PRA QUE LADO o produto das probabilidades erra, e e' o que
    decide se uma dependencia media e' tolerável:

      "positivo"  as duas pernas ganham juntas -> P(A e B) > P(A)P(B), o
                  produto SUBESTIMA. Erro conservador: o bilhete e' melhor do
                  que o motor anuncia.
      "negativo"  uma tende a excluir a outra -> o produto SUPERESTIMA. E' o
                  erro perigoso, e o exemplo ja' esta' no codigo: "Under 2.5 +
                  Ambas Marcam" so' paga em 1-1 (~12%) e o produto anunciava
                  ~28% (ver _CORRELATION_GROUP_OVERRIDES em ranking.py).
      "indefinido" nao da' pra dizer -- tratado como negativo por precaucao.
    """
    fam_a, fam_b = _familia(a), _familia(b)
    mesmo_jogo = (_fixture_id(a) is not None
                  and _fixture_id(a) == _fixture_id(b))

    if mesmo_jogo:
        if fam_a == fam_b:
            return {"nivel": ALTA, "mesmo_jogo": True, "sinal": "indefinido",
                    "motivo": f"mesma familia ({fam_a}) no mesmo jogo"}
        par = _CORRELACAO_MESMO_JOGO.get(frozenset((fam_a, fam_b)))
        if par is None:
            # §16: sem mecanismo mapeado nao se assume independencia.
            return {"nivel": DESCONHECIDA, "mesmo_jogo": True, "sinal": "indefinido",
                    "motivo": f"relacao entre {fam_a} e {fam_b} no mesmo jogo nao esta' mapeada"}
        nivel, motivo = par
        return {"nivel": nivel, "mesmo_jogo": True,
                "sinal": _sinal_da_dependencia(a, b), "motivo": motivo}

    # Jogos diferentes. Independentes no gramado; a pergunta que sobra e' se
    # sao independentes no MODELO.
    if fam_a == fam_b:
        return {"nivel": MEDIA, "mesmo_jogo": False, "sinal": "indefinido",
                "motivo": f"jogos diferentes, mas a mesma estimativa de {fam_a} "
                          f"sustenta as duas pernas"}
    return {"nivel": BAIXA, "mesmo_jogo": False, "sinal": "positivo",
            "motivo": "jogos diferentes e familias diferentes"}


def _sinal_da_dependencia(a: dict, b: dict) -> str:
    """Sinal da dependencia entre duas pernas do mesmo jogo, pela DIRECAO.

    Duas pernas 'over' no mesmo jogo apontam pro mesmo regime (jogo movimentado)
    -- ganham juntas, o produto subestima, erro conservador. 'over' contra
    'under' apontam pra regimes opostos: o produto superestima, que e' o erro
    que quebra bilhete. Direcao ausente (mercado sem over/under, como
    resultado) nao permite a leitura e vira indefinido, tratado como negativo.
    """
    da, db = _direcao(a), _direcao(b)
    if da not in ("over", "under") or db not in ("over", "under"):
        return "indefinido"
    return "positivo" if da == db else "negativo"


_ORDEM_CORRELACAO = {BAIXA: 0, MEDIA: 1, DESCONHECIDA: 2, ALTA: 3}


def correlacao_do_combo(legs: list) -> dict:
    """A PIOR correlacao entre todos os pares. Um bilhete e' tao correlacionado
    quanto o par mais ligado que ele carrega -- a media esconderia um par
    ALTO atras de dois pares BAIXOS."""
    if len(legs) < 2:
        return {"nivel": BAIXA, "mesmo_jogo": False, "sinal": "positivo",
                "motivo": "perna unica", "pares": []}
    pares = []
    for i in range(len(legs)):
        for j in range(i + 1, len(legs)):
            par = classificar_correlacao(legs[i], legs[j])
            par["pernas"] = (i + 1, j + 1)
            pares.append(par)
    pior = max(pares, key=lambda p: _ORDEM_CORRELACAO[p["nivel"]])
    return {**pior, "pares": pares}


# ---------------------------------------------------------------------------
# §30  REDUNDANCIA
#
# Correlacao mede quanto dois eventos andam juntos. Redundancia e' o caso
# extremo: um evento CONTEM o outro, e o bilhete e' na verdade uma perna so'
# cotada pior. Foi o RED de 21/06 ("Over 1.5" + "Over 0.5" no mesmo jogo).
#
# O veto de familia ja' pega esse caso especifico. Este detector existe pros
# que ele nao pega: mesma familia, mesmo escopo, linhas encaixadas.
# ---------------------------------------------------------------------------
def detectar_redundancia(a: dict, b: dict) -> str | None:
    """Motivo, quando uma perna implica a outra. None quando nao ha'."""
    if _fixture_id(a) != _fixture_id(b) or _familia(a) != _familia(b):
        return None
    if (a.get("scope") or "") != (b.get("scope") or ""):
        return None
    da, db = _direcao(a), _direcao(b)
    la, lb = a.get("_line_val"), b.get("_line_val")
    if da != db or da not in ("over", "under") or la is None or lb is None:
        # Mesma familia, mesmo jogo, direcoes opostas: nao e' redundancia, e'
        # contradicao -- e o veto de familia ja' recusa o par.
        return "mesma familia e mesmo escopo no mesmo jogo"
    if da == "over" and float(la) >= float(lb):
        return f"Over {la} implica Over {lb}: o bilhete e' a perna mais exigente sozinha"
    if da == "under" and float(la) <= float(lb):
        return f"Under {la} implica Under {lb}: o bilhete e' a perna mais exigente sozinha"
    return "mesma familia e mesmo escopo no mesmo jogo"


# ---------------------------------------------------------------------------
# CONFIGURACAO (§6, §7, §22, §25, §40)
#
# Tudo que e' limiar mora aqui, com o numero declarado e o motivo ao lado --
# §19 pede pesos configuraveis e validados por backtest, e nenhum destes
# numeros foi calibrado contra as 6 combinacoes do historico (§57: seis linhas
# nao sustentam limiar). Sao numeros de PRINCIPIO: cada um diz uma regra que
# se sustenta sem olhar o resultado passado.
# ---------------------------------------------------------------------------
@dataclass
class ComboConfig:
    # §7 -- a combinacao exige mais que a simples. O motor individual ja' cobra
    # min_edge=0.05 (PickEngineConfig); aqui a perna precisa de mais margem
    # porque o erro dela vai multiplicar o erro da outra.
    min_edge_simple: float = 0.05
    min_edge_combination: float = 0.08
    # §23/§24 -- depois de multiplicar, o bilhete inteiro ainda precisa de
    # margem propria contra o preco combinado.
    min_edge_combinado: float = 0.03
    # §6 -- EV do bilhete estritamente positivo, calculado sobre a
    # probabilidade AJUSTADA (§24), nunca sobre a bruta.
    min_ev_combinado: float = 0.0

    # §25 -- pisos de qualidade da PERNA pra ela poder entrar num combo.
    min_prob_calibrada_perna: float = 0.70
    min_data_quality_perna: float = 75.0
    min_amostra_perna: int = 10
    # §13 -- perna de risco ALTO nunca entra em combinacao. Como simples ela
    # ainda pode sair (o motor individual decide), mas duas incertezas
    # multiplicadas nao viram uma certeza.
    risco_maximo_perna: str = "MEDIO"

    # §25 -- pisos do BILHETE.
    min_prob_combinada: float = 0.62
    risco_maximo_combo: str = "MEDIO"
    # §16 -- correlacao ALTA nunca; DESCONHECIDA so' se o operador ligar.
    permitir_correlacao_desconhecida: bool = False

    # §27 -- mesmo jogo. O produto so' e' aproximacao aceitavel quando a
    # dependencia empurra pro lado conservador (sinal positivo). Fora disso a
    # combinacao no mesmo jogo nao sai. Ver a nota de produto no topo do
    # pipeline: o formato "dois mercados no mesmo jogo" continua existindo,
    # so' deixou de sair quando a conta nao fecha.
    permitir_mesmo_jogo: bool = True
    exigir_sinal_positivo_mesmo_jogo: bool = True

    # §18 -- PENALIZACAO DA PROBABILIDADE COMBINADA.
    #
    # Aplicada PERNA A PERNA, antes de multiplicar, e nao no produto final.
    # E' onde o vies mora: se cada perna esta' otimista em d, o produto de duas
    # esta' otimista em ~2d. Descontar no produto trataria o vies como se ele
    # nascesse da multiplicacao.
    #
    # O corte NAO se aplica ao formato simples (§3: o motor simples esta'
    # medido e nao se mexe nele).
    desconto_por_perna: float = 0.02
    desconto_correlacao_media: float = 0.03
    desconto_correlacao_desconhecida: float = 0.08
    desconto_amostra_limitada: float = 0.03   # alguma perna com amostra < boa
    desconto_data_quality: float = 0.03       # alguma perna com dq < 80
    desconto_divergencia: float = 0.03        # modelo x historico discordando

    # §40 -- teto de pernas. 3 e' excepcional (§39) e so' passa pelos limiares
    # reforcados abaixo.
    max_combination_legs: int = 3
    # §39 -- pra abrir a terceira perna, TODAS precisam destes numeros.
    min_prob_calibrada_perna_3x: float = 0.80
    min_amostra_perna_3x: int = 20
    correlacao_maxima_3x: str = BAIXA
    min_prob_combinada_3x: float = 0.66

    # §46 -- confianca alta exige evidencia extraordinaria.
    confianca_alta: float = 0.90
    amostra_para_confianca_alta: int = 20

    # §52/§53 -- QUANDO TROCAR A SIMPLES POR UM COMBO.
    #
    # A faixa do bilhete e' do TOTAL, entao dupla e simples pagam o mesmo
    # preco. Trocar so' se justifica com probabilidade MAIOR, e por uma margem
    # que cubra o fato de a estimativa do combo ser a menos confiavel das duas
    # (duas estimativas multiplicadas contra uma).
    margem_para_preferir_combo: float = 0.03

    # §19 -- PESOS DO COMBINATION_SCORE. Sao renormalizados no uso, entao zerar
    # um peso redistribui o resto na proporcao, sem precisar reescrever os
    # outros.
    #
    # peso_ev=0 E' DELIBERADO e e' a unica divergencia da tabela do §19, que
    # pedia 15%. A regra permanente do motor -- ja' aplicada no pre-jogo
    # generico, no ao vivo e no Pick Jogador -- e' que PRECO ELIMINA NOS GATES
    # E NUNCA ORDENA: EV e odd decidem se um candidato vive, jamais qual
    # candidato vence. O §20 deste mesmo pedido diz a mesma coisa ("nao
    # selecionar pelo maior EV", "EV pode ser inflado por uma probabilidade
    # superestimada") e lista EV como o ULTIMO criterio de prioridade. O EV
    # continua sendo gate duro (min_ev_combinado), que e' onde ele pesa.
    peso_qualidade_pernas: float = 0.25
    peso_probabilidade: float = 0.20
    peso_ev: float = 0.00
    peso_risco: float = 0.15
    peso_correlacao: float = 0.10
    peso_data_quality: float = 0.05
    peso_amostra: float = 0.05
    peso_convergencia: float = 0.05


DEFAULT_COMBO_CONFIG = ComboConfig()

_NIVEIS_RISCO = ("BAIXO", "MEDIO", "ALTO")
_SCORE_RISCO = {"BAIXO": 1.0, "MEDIO": 0.5, "ALTO": 0.0}
_SCORE_CORRELACAO = {BAIXA: 1.0, MEDIA: 0.5, DESCONHECIDA: 0.2, ALTA: 0.0}


def _pior_risco(a: str, b: str) -> str:
    return _NIVEIS_RISCO[max(_NIVEIS_RISCO.index(a), _NIVEIS_RISCO.index(b))]


def _rebaixar(risco: str, degraus: int = 1) -> str:
    return _NIVEIS_RISCO[min(len(_NIVEIS_RISCO) - 1,
                             _NIVEIS_RISCO.index(risco) + degraus)]


# ---------------------------------------------------------------------------
# §31  CONVERGENCIA  ·  §32  CONTRADICOES
# ---------------------------------------------------------------------------
def convergencia_da_perna(leg: dict) -> dict:
    """Quanto as leituras independentes daquela perna concordam entre si.

    Sao tres confirmadores que o motor ja' calcula e que morriam como numeros
    soltos no rastro: o desacordo entre modelo (Poisson/NegBin) e historico, o
    desacordo do modelo de arbitro, e a convergencia feitos/cedidos. Cada um
    ausente e' NEUTRO (0.5), nunca favoravel."""
    partes = []
    for chave in ("model_fit_diff", "referee_fit_diff"):
        diff = leg.get(chave)
        if diff is not None:
            # 0pp de desacordo -> 1.0; 20pp ou mais -> 0.0.
            partes.append(max(0.0, 1.0 - abs(float(diff)) / 0.20))
    conv = leg.get("convergence")
    if isinstance(conv, dict) and "converged" in conv:
        partes.append(1.0 if conv["converged"] else 0.0)
    projecao = leg.get("projecao") or {}
    classe = projecao.get("classe")
    if classe:
        partes.append({"a_favor": 1.0, "em_cima_da_linha": 0.3,
                       "contra_a_linha": 0.0}.get(classe, 0.5))
    score = round(sum(partes) / len(partes), 4) if partes else 0.5
    return {"score": score, "sinais": len(partes)}


#: Gravidade das contradicoes. CRITICA bloqueia sozinha; duas GRAVES bloqueiam
#: juntas; uma GRAVE desconta o score. §32.
CRITICA, GRAVE = "critica", "grave"


def detectar_contradicoes(leg: dict, cfg: ComboConfig = DEFAULT_COMBO_CONFIG) -> list:
    """Contradicoes DENTRO de uma perna -- §32. Sao pares de sinais que, cada
    um sozinho, passariam nos gates, e que juntos dizem que o numero nao
    merece o credito que ele esta' pedindo."""
    achados = []
    conf = float(leg.get("confidence") or 0)
    amostra = int(leg.get("amostra") or 0)
    prob = float(leg.get("taxa_real") or 0)
    ev = float(leg.get("ev") or 0)
    dq = leg.get("data_quality_score")
    fit = leg.get("model_fit_diff")

    # §46 -- 4/4, 5/5 e 6/6 nao sao evidencia extraordinaria.
    if conf >= cfg.confianca_alta and amostra < cfg.amostra_para_confianca_alta:
        achados.append({
            "tipo": "confianca_alta_amostra_curta", "gravidade": GRAVE,
            "detalhe": f"confidence {conf:.0%} com amostra de {amostra} jogos",
        })

    # historico forte, modelo fraco
    if fit is not None and abs(float(fit)) >= 0.20 and prob >= 0.75:
        achados.append({
            "tipo": "historico_forte_modelo_fraco", "gravidade": GRAVE,
            "detalhe": f"taxa {prob:.0%} com o modelo discordando em "
                       f"{abs(float(fit)):.0%}",
        })

    # EV alto sustentado por estimativa pouco confiavel
    if ev >= 0.20 and (amostra < cfg.min_amostra_perna
                       or (dq is not None and float(dq) < cfg.min_data_quality_perna)):
        achados.append({
            "tipo": "ev_alto_prob_pouco_confiavel", "gravidade": GRAVE,
            "detalhe": f"EV {ev:+.0%} com amostra {amostra} e qualidade "
                       f"{'-' if dq is None else f'{float(dq):.0f}'}",
        })

    # A projecao aponta pro lado oposto do pick.
    if (leg.get("projecao") or {}).get("classe") == "contra_a_linha":
        achados.append({
            "tipo": "projecao_contra_a_linha", "gravidade": GRAVE,
            "detalhe": "a projecao do modelo aponta contra a linha escolhida",
        })

    var = leg.get("variance") or {}
    cv = var.get("coefficient_of_variation") if isinstance(var, dict) else None
    if cv is not None and float(cv) > CV_HIGH_THRESHOLD and conf >= 0.85:
        achados.append({
            "tipo": "confianca_alta_dispersao_alta", "gravidade": GRAVE,
            "detalhe": f"confidence {conf:.0%} sobre uma contagem de CV {float(cv):.2f}",
        })
    return achados


# ---------------------------------------------------------------------------
# §5  CAMADA 2 -- VALIDACAO INDIVIDUAL
# ---------------------------------------------------------------------------
def perfil_da_perna(leg: dict, cfg: ComboConfig = DEFAULT_COMBO_CONFIG) -> dict:
    """Todos os campos que o §5 exige, cada um com o nome dele, saindo do que o
    pick_engine ja' calculou -- nada e' recalculado aqui.

    §10 pede tres probabilidades separadas, e as tres ja' existem no motor com
    outros nomes:
      probability_raw         taxa empirica antes do encolhimento bayesiano
      probability_model       Poisson/Binomial Negativa pra mesma linha
      probability_calibrated  a que passou pelos gates e vira edge/EV/odd justa
    """
    amostra = classificar_amostra(leg.get("amostra"))
    conv = convergencia_da_perna(leg)
    prob = float(leg.get("taxa_real") or 0)
    dq = leg.get("data_quality_score")
    projecao = leg.get("projecao") or {}
    return {
        "market": leg.get("market_name"),
        "market_type": leg.get("market_type"),
        "correlation_group": _familia(leg),
        "scope": leg.get("scope"),
        "selection": leg.get("value_label"),
        "fixture_id": _fixture_id(leg),
        "odd": leg.get("odd"),
        "probability_raw": leg.get("taxa_bruta_pre_bayes"),
        "probability_model": leg.get("poisson_probability"),
        "probability_calibrated": prob,
        "probability": prob,
        "confidence": leg.get("confidence"),
        "fair_odd": round(1.0 / prob, 4) if prob > 0 else None,
        "edge": leg.get("edge"),
        "EV": leg.get("ev"),
        "risk": leg.get("risco"),
        "sample_quality": amostra,
        "data_quality": dq,
        "projection": projecao.get("valor"),
        "projection_margin": projecao.get("margem_em_sigmas"),
        "projection_class": projecao.get("classe"),
        "convergence": conv["score"],
        "contradicoes": detectar_contradicoes(leg, cfg),
    }


def validar_individual(leg: dict, cfg: ComboConfig = DEFAULT_COMBO_CONFIG) -> dict:
    """Aprova ou reprova a perna para cada um dos dois destinos.

    `simples_ok` e `combo_ok` sao respostas DIFERENTES pra perguntas diferentes
    (§35): uma perna pode ser um pick simples excelente e uma peca de bilhete
    ruim. Nao ha' caminho em que combo_ok seja True e simples_ok False -- a
    exigencia do combo contem a da simples.
    """
    perfil = perfil_da_perna(leg, cfg)
    prob = float(perfil["probability_calibrated"] or 0)
    edge = float(perfil["edge"] or 0)
    ev = float(perfil["EV"] or 0)
    dq = perfil["data_quality"]
    amostra = perfil["sample_quality"]["n"]
    risco = perfil["risk"] or "ALTO"
    graves = [c for c in perfil["contradicoes"] if c["gravidade"] in (CRITICA, GRAVE)]

    motivos_simples, motivos_combo = [], []

    # §6 e §7 -- EV e edge sao gates, nos dois destinos.
    if ev <= 0:
        motivos_simples.append(f"EV nao positivo ({ev:+.1%})")
    if edge <= 0:
        motivos_simples.append(f"edge nao positivo ({edge:+.1%})")
    if edge < cfg.min_edge_simple:
        motivos_simples.append(f"edge abaixo do minimo da simples "
                               f"({edge:.1%} < {cfg.min_edge_simple:.0%})")

    motivos_combo += list(motivos_simples)
    if edge < cfg.min_edge_combination:
        motivos_combo.append(f"edge abaixo do minimo de combinacao "
                             f"({edge:.1%} < {cfg.min_edge_combination:.0%})")
    if prob < cfg.min_prob_calibrada_perna:
        motivos_combo.append(f"probabilidade calibrada abaixo do piso de combinacao "
                             f"({prob:.1%} < {cfg.min_prob_calibrada_perna:.0%})")
    if amostra < cfg.min_amostra_perna:
        motivos_combo.append(f"amostra de {amostra} jogos "
                             f"({perfil['sample_quality']['classe']}) abaixo de "
                             f"{cfg.min_amostra_perna}")
    if dq is None or float(dq) < cfg.min_data_quality_perna:
        motivos_combo.append(f"qualidade de dados "
                             f"{'ausente' if dq is None else f'{float(dq):.0f}'} "
                             f"abaixo de {cfg.min_data_quality_perna:.0f}")
    if _pior_risco(risco, cfg.risco_maximo_perna) != cfg.risco_maximo_perna:
        motivos_combo.append(f"risco {risco} acima do teto de combinacao "
                             f"({cfg.risco_maximo_perna})")
    for c in graves:
        motivos_combo.append(f"contradicao {c['tipo']}: {c['detalhe']}")

    return {
        **perfil,
        "simples_ok": not motivos_simples,
        "combo_ok": not motivos_combo,
        "motivos_simples": motivos_simples,
        "motivos_combo": motivos_combo,
    }


# ---------------------------------------------------------------------------
# §17 / §18  PROBABILIDADE COMBINADA
# ---------------------------------------------------------------------------
def probabilidade_combinada(perfis: list, correlacao: dict,
                            cfg: ComboConfig = DEFAULT_COMBO_CONFIG) -> dict:
    """RAW e ADJUSTED, com a conta dos descontos aberta.

    RAW e' o produto das probabilidades calibradas -- a aproximacao de
    independencia, valida so' quando a correlacao e' baixa (§17).

    ADJUSTED desconta ANTES de multiplicar. Cada perna entra na conta com a
    probabilidade dela menos o desconto que ela merece, e o produto sai dos
    numeros ja' descontados. E' onde o vies mora: se cada perna esta' otimista
    em d, o produto de duas esta' otimista em ~2d -- descontar no produto
    trataria o vies como se ele nascesse da multiplicacao.

    Perna unica NAO e' descontada (§3: o motor simples esta' medido, e cobrar
    dele um desconto que nasceu da multiplicacao seria mudar o que funciona).
    """
    probs = [float(p["probability_calibrated"] or 0) for p in perfis]
    raw = 1.0
    for p in probs:
        raw *= p

    if len(perfis) < 2:
        return {"raw": round(raw, 4), "adjusted": round(raw, 4),
                "desconto_por_perna": 0.0, "descontos": []}

    descontos = [("multiplicacao de estimativas", cfg.desconto_por_perna)]
    if correlacao["nivel"] == MEDIA:
        descontos.append((f"correlacao MEDIA ({correlacao['motivo']})",
                          cfg.desconto_correlacao_media))
    elif correlacao["nivel"] == DESCONHECIDA:
        descontos.append((f"correlacao DESCONHECIDA ({correlacao['motivo']})",
                          cfg.desconto_correlacao_desconhecida))

    if any(p["sample_quality"]["score"] < 80.0 for p in perfis):
        descontos.append(("alguma perna com amostra abaixo de 20 jogos",
                          cfg.desconto_amostra_limitada))
    if any(p["data_quality"] is None or float(p["data_quality"]) < 80.0 for p in perfis):
        descontos.append(("alguma perna com qualidade de dados abaixo de 80",
                          cfg.desconto_data_quality))
    if any(p["convergence"] < 0.5 for p in perfis):
        descontos.append(("modelo e historico discordando em alguma perna",
                          cfg.desconto_divergencia))

    total = round(sum(d for _, d in descontos), 4)
    ajustadas = [max(0.0, p - total) for p in probs]
    adjusted = 1.0
    for p in ajustadas:
        adjusted *= p

    return {
        "raw": round(raw, 4),
        "adjusted": round(adjusted, 4),
        "desconto_por_perna": total,
        "descontos": [{"motivo": m, "valor": v} for m, v in descontos],
    }


# ---------------------------------------------------------------------------
# §14  RISCO DA COMBINACAO
# ---------------------------------------------------------------------------
def risco_combinado(perfis: list, correlacao: dict) -> dict:
    """Nunca melhor que a pior perna (§14), e rebaixado pelo que so' existe no
    bilhete: correlacao e numero de pernas."""
    base = "BAIXO"
    for p in perfis:
        base = _pior_risco(base, p["risk"] or "ALTO")
    motivos = [f"pior perna: {base}"]
    nivel = base

    if len(perfis) < 2:
        return {"nivel": nivel, "motivos": motivos}

    if correlacao["nivel"] == ALTA:
        nivel = "ALTO"
        motivos.append("correlacao ALTA entre pernas")
    elif correlacao["nivel"] == DESCONHECIDA:
        nivel = _rebaixar(nivel, 2)
        motivos.append("correlacao DESCONHECIDA")
    elif correlacao["nivel"] == MEDIA:
        nivel = _rebaixar(nivel, 1)
        motivos.append("correlacao MEDIA")

    if len(perfis) >= 3:
        nivel = _rebaixar(nivel, 1)
        motivos.append("tres pernas")

    # Uma contradicao GRAVE em qualquer perna sobe o risco do bilhete inteiro.
    if any(c["gravidade"] in (CRITICA, GRAVE)
           for p in perfis for c in p["contradicoes"]):
        nivel = _rebaixar(nivel, 1)
        motivos.append("contradicao em alguma perna")

    return {"nivel": nivel, "motivos": motivos}


# ---------------------------------------------------------------------------
# §29  DIVERSIFICACAO
# ---------------------------------------------------------------------------
def diversificacao(perfis: list, legs: list) -> dict:
    """0 a 1. Jogos diferentes e familias diferentes sobem; repetir qualquer um
    dos dois derruba. NAO compensa EV negativo nem risco -- entra so' no
    score, e o score nunca destrava um gate (§29)."""
    if len(perfis) < 2:
        return {"score": 0.0, "jogos": 1, "familias": 1}
    jogos = len({_fixture_id(l) for l in legs})
    familias = len({p["correlation_group"] for p in perfis})
    n = len(perfis)
    score = round(0.5 * (jogos / n) + 0.5 * (familias / n), 4)
    return {"score": score, "jogos": jogos, "familias": familias}


# ---------------------------------------------------------------------------
# §19 / §35  SCORES
# ---------------------------------------------------------------------------
def qualidade_da_perna(perfil: dict) -> float:
    """0 a 1. Evidencia, e nada de preco -- odd e EV nao entram aqui nem no
    SIMPLE_SCORE nem no COMBINATION_SCORE (ver o comentario de peso_ev)."""
    prob = float(perfil["probability_calibrated"] or 0)
    conf = float(perfil["confidence"] or 0)
    amostra = perfil["sample_quality"]["score"] / 100.0
    dq = (float(perfil["data_quality"]) / 100.0) if perfil["data_quality"] is not None else 0.5
    risco = _SCORE_RISCO.get(perfil["risk"] or "ALTO", 0.0)
    conv = float(perfil["convergence"])
    return round(0.30 * prob + 0.20 * conf + 0.15 * amostra
                 + 0.10 * dq + 0.15 * risco + 0.10 * conv, 4)


def simple_score(perfil: dict) -> float:
    """§35 -- a nota da perna COMO APOSTA SIMPLES. Hoje e' a propria qualidade:
    sem segunda perna, nao ha' correlacao, diversificacao nem multiplicacao
    pra pesar. Existe como funcao propria porque a pergunta e' outra, e as
    duas notas precisam poder divergir sem uma arrastar a outra."""
    return qualidade_da_perna(perfil)


def _normalizar(pesos: dict) -> dict:
    total = sum(pesos.values())
    if total <= 0:
        return {k: 0.0 for k in pesos}
    return {k: v / total for k, v in pesos.items()}


def combination_score(perfis: list, combinado: dict, correlacao: dict,
                      risco: dict, cfg: ComboConfig = DEFAULT_COMBO_CONFIG) -> dict:
    """§19. Pesos configuraveis e renormalizados -- zerar um redistribui o
    resto na proporcao."""
    qualidades = [qualidade_da_perna(p) for p in perfis]
    # §60: a MEDIA premiava o bilhete desequilibrado (uma perna otima puxando
    # uma mediana). Metade do termo e' a pior perna, pra que duas medianas
    # nunca virem "uma aposta forte" por soma.
    q = 0.5 * min(qualidades) + 0.5 * (sum(qualidades) / len(qualidades))

    p_adj = combinado["adjusted"]
    piso = cfg.min_prob_combinada
    termo_prob = max(0.0, min(1.0, (p_adj - piso) / max(1e-9, 1.0 - piso)))
    termo_ev = max(0.0, min(1.0, combinado.get("ev", 0.0) / 0.30))
    termo_risco = _SCORE_RISCO.get(risco["nivel"], 0.0)
    termo_corr = _SCORE_CORRELACAO.get(correlacao["nivel"], 0.0)
    dqs = [(float(p["data_quality"]) / 100.0) if p["data_quality"] is not None else 0.5
           for p in perfis]
    termo_dq = min(dqs)
    termo_amostra = min(p["sample_quality"]["score"] for p in perfis) / 100.0
    termo_conv = min(float(p["convergence"]) for p in perfis)

    pesos = _normalizar({
        "qualidade_pernas": cfg.peso_qualidade_pernas,
        "probabilidade": cfg.peso_probabilidade,
        "ev": cfg.peso_ev,
        "risco": cfg.peso_risco,
        "correlacao": cfg.peso_correlacao,
        "data_quality": cfg.peso_data_quality,
        "amostra": cfg.peso_amostra,
        "convergencia": cfg.peso_convergencia,
    })
    termos = {
        "qualidade_pernas": q, "probabilidade": termo_prob, "ev": termo_ev,
        "risco": termo_risco, "correlacao": termo_corr,
        "data_quality": termo_dq, "amostra": termo_amostra,
        "convergencia": termo_conv,
    }
    score = round(sum(pesos[k] * termos[k] for k in termos), 4)
    return {"score": score, "termos": {k: round(v, 4) for k, v in termos.items()},
            "pesos": {k: round(v, 4) for k, v in pesos.items()}}


# ---------------------------------------------------------------------------
# §25 / §50  AVALIACAO DO BILHETE
# ---------------------------------------------------------------------------
_TIPO_POR_TAMANHO = {1: "simples", 2: "dupla", 3: "tripla"}


def avaliar(legs: list, odd_combinada: float,
            cfg: ComboConfig = DEFAULT_COMBO_CONFIG) -> dict:
    """Avalia UM bilhete (1, 2 ou 3 pernas) e devolve o documento do §50:
    pernas, numeros do combinado, todos os gates com o veredito de cada um, e
    a decisao. Nunca levanta excecao -- um bilhete reprovado volta com
    `decision: NO_PICK` e o motivo, porque o motivo e' o produto (§51).
    """
    perfis = [validar_individual(l, cfg) for l in legs]
    n = len(perfis)
    correlacao = correlacao_do_combo(legs)
    combinado = probabilidade_combinada(perfis, correlacao, cfg)

    # §23 -- a implicita ignora a margem da casa de proposito: sem tirar o vig
    # ela sai ALTA, o edge sai BAIXO, e o erro cai pro lado conservador.
    implicita = round(1.0 / float(odd_combinada), 4) if odd_combinada else None
    p_adj = combinado["adjusted"]
    # §24 -- EV sobre a AJUSTADA, nunca sobre a bruta.
    ev = round(p_adj * float(odd_combinada) - 1.0, 4)
    edge = round(p_adj - implicita, 4) if implicita is not None else None
    combinado["ev"] = ev
    risco = risco_combinado(perfis, correlacao)
    div = diversificacao(perfis, legs)
    score = combination_score(perfis, combinado, correlacao, risco, cfg)

    gates: dict = {}
    motivos: list = []

    def gate(nome: str, ok: bool, motivo: str):
        gates[nome] = bool(ok)
        if not ok:
            motivos.append(motivo)

    gate("individual_quality",
         all(p["combo_ok"] if n > 1 else p["simples_ok"] for p in perfis),
         "; ".join(m for p in perfis
                   for m in (p["motivos_combo"] if n > 1 else p["motivos_simples"])))
    gate("EV", ev > cfg.min_ev_combinado,
         f"EV combinado {ev:+.1%} nao supera {cfg.min_ev_combinado:+.0%}")
    if n > 1:
        gate("edge", edge is not None and edge >= cfg.min_edge_combinado,
             f"edge combinado {0 if edge is None else edge:+.1%} abaixo de "
             f"{cfg.min_edge_combinado:.0%}")
        gate("probability", p_adj >= cfg.min_prob_combinada,
             f"probabilidade ajustada {p_adj:.1%} abaixo do piso "
             f"{cfg.min_prob_combinada:.0%}")
        gate("risk",
             _pior_risco(risco["nivel"], cfg.risco_maximo_combo) == cfg.risco_maximo_combo,
             f"risco do bilhete {risco['nivel']} acima de {cfg.risco_maximo_combo}")
        correlacao_ok = correlacao["nivel"] != ALTA and (
            correlacao["nivel"] != DESCONHECIDA or cfg.permitir_correlacao_desconhecida)
        gate("correlation", correlacao_ok,
             f"correlacao {correlacao['nivel']}: {correlacao['motivo']}")

        # §30 -- redundancia. Checada por par, e nao pelo nivel de correlacao:
        # uma perna que CONTEM a outra pode aparecer com nivel ALTA como
        # qualquer outro par de mesma familia, e o motivo publicado precisa
        # dizer que o bilhete e' uma aposta so'.
        redundantes = [
            (i + 1, j + 1, motivo)
            for i in range(n) for j in range(i + 1, n)
            if (motivo := detectar_redundancia(legs[i], legs[j]))
        ]
        gate("redundancy", not redundantes,
             "; ".join(f"pernas {i} e {j}: {m}" for i, j, m in redundantes))

        # §27 -- mesmo jogo.
        if correlacao["mesmo_jogo"]:
            mesmo_jogo_ok = cfg.permitir_mesmo_jogo and (
                not cfg.exigir_sinal_positivo_mesmo_jogo
                or correlacao["sinal"] == "positivo")
            gate("same_fixture", mesmo_jogo_ok,
                 "pernas do mesmo jogo com dependencia de sinal "
                 f"{correlacao['sinal']}: o produto das probabilidades "
                 "superestima o bilhete")
        else:
            gates["same_fixture"] = True

        # §39 -- tres pernas sao excepcionais.
        if n >= 3:
            tres_ok = (
                all(float(p["probability_calibrated"] or 0) >= cfg.min_prob_calibrada_perna_3x
                    for p in perfis)
                and all(p["sample_quality"]["n"] >= cfg.min_amostra_perna_3x for p in perfis)
                and correlacao["nivel"] == cfg.correlacao_maxima_3x
                and p_adj >= cfg.min_prob_combinada_3x
                and n <= cfg.max_combination_legs
            )
            gate("three_legs", tres_ok,
                 "tres pernas exigem todas as pernas com probabilidade >= "
                 f"{cfg.min_prob_calibrada_perna_3x:.0%}, amostra >= "
                 f"{cfg.min_amostra_perna_3x}, correlacao "
                 f"{cfg.correlacao_maxima_3x} e probabilidade combinada >= "
                 f"{cfg.min_prob_combinada_3x:.0%}")
    else:
        for nome in ("edge", "probability", "risk", "correlation",
                     "redundancy", "same_fixture"):
            gates[nome] = True

    # §32 -- contradicoes. Duas GRAVES no bilhete bloqueiam; uma so' ja' foi
    # cobrada no risco e na probabilidade ajustada.
    graves = [c for p in perfis for c in p["contradicoes"]
              if c["gravidade"] in (CRITICA, GRAVE)]
    criticas = [c for c in graves if c["gravidade"] == CRITICA]
    gate("contradiction", not criticas and len(graves) < 2,
         "; ".join(f"{c['tipo']} ({c['detalhe']})" for c in graves))

    aprovado = all(gates.values())
    return {
        "type": _TIPO_POR_TAMANHO.get(n, f"{n}x"),
        "legs": [{
            "market": p["market"], "market_type": p["market_type"],
            "selection": p["selection"], "fixture_id": p["fixture_id"],
            "odd": p["odd"],
            "probability_raw": p["probability_raw"],
            "probability_model": p["probability_model"],
            "probability_calibrated": p["probability_calibrated"],
            "probability": p["probability"], "confidence": p["confidence"],
            "fair_odd": p["fair_odd"], "edge": p["edge"], "EV": p["EV"],
            "risk": p["risk"], "data_quality": p["data_quality"],
            "sample_quality": p["sample_quality"],
            "projection": p["projection"],
            "projection_margin": p["projection_margin"],
            "convergence": p["convergence"],
            "quality_score": qualidade_da_perna(p),
            "simple_score": simple_score(p),
            "contradictions": p["contradicoes"],
            "combo_ok": p["combo_ok"], "motivos_combo": p["motivos_combo"],
        } for p in perfis],
        "combined": {
            "odd": round(float(odd_combinada), 4),
            "implied_probability": implicita,
            "probability_raw": combinado["raw"],
            "probability_adjusted": p_adj,
            "probability_discounts": combinado["descontos"],
            "discount_per_leg": combinado["desconto_por_perna"],
            "fair_odd": round(1.0 / p_adj, 4) if p_adj > 0 else None,
            "edge": edge,
            "EV": ev,
            "risk": risco["nivel"], "risk_reasons": risco["motivos"],
            "correlation": correlacao["nivel"],
            "correlation_reason": correlacao["motivo"],
            "correlation_pairs": correlacao["pares"],
            "diversification": div["score"], "diversification_raw": div,
            "score": score["score"], "score_terms": score["termos"],
            "score_weights": score["pesos"],
        },
        "gates": gates,
        "decision": "PICK" if aprovado else "NO_PICK",
        # §51 -- o motivo E' o produto. Sem ele um dia sem alavancagem e' um
        # silencio, e silencio nao se audita.
        "reasons": [m for m in motivos if m],
    }


# ---------------------------------------------------------------------------
# §52 / §53  A ESCOLHA FINAL
# ---------------------------------------------------------------------------
def escolher(avaliacoes: list, cfg: ComboConfig = DEFAULT_COMBO_CONFIG) -> dict | None:
    """Recebe bilhetes ja' avaliados (de qualquer formato) e devolve o que sai,
    ou None.

    A ORDEM NAO E' POR SCORE, E' POR FORMATO, e o motivo e' aritmetico: a faixa
    [1.40, 1.55] e' do TOTAL do bilhete, entao uma dupla nessa faixa paga
    exatamente o que uma simples nessa faixa paga. Sem premio de preco, a unica
    coisa que a segunda perna acrescenta e' uma segunda maneira de perder.

    Entao a simples ganha por padrao, e o combo so' passa na frente quando
    entrega PROBABILIDADE AJUSTADA maior por uma margem (`margem_para_preferir
    _combo`) -- margem que existe porque a estimativa do combo e' a menos
    confiavel das duas: duas probabilidades multiplicadas contra uma.

    Quando nao ha' simples aprovada, o combo sai sozinho -- que e' a razao
    original do formato existir (30/07: a melhor perna do dia a 1.39 contra um
    piso de 1.40, e o dia ficou sem produto por um centavo).
    """
    aprovados = [a for a in avaliacoes if a["decision"] == "PICK"]
    if not aprovados:
        return None

    simples = [a for a in aprovados if len(a["legs"]) == 1]
    combos = [a for a in aprovados if len(a["legs"]) > 1]

    melhor_simples = max(simples, key=lambda a: a["combined"]["score"], default=None)
    melhor_combo = max(combos, key=lambda a: a["combined"]["score"], default=None)

    if melhor_simples is None:
        melhor_combo["escolha"] = "combo: nenhuma simples chegou a faixa"
        return melhor_combo
    if melhor_combo is None:
        melhor_simples["escolha"] = "simples: nenhuma combinacao passou nos gates"
        return melhor_simples

    p_simples = melhor_simples["combined"]["probability_adjusted"]
    p_combo = melhor_combo["combined"]["probability_adjusted"]
    if p_combo >= p_simples + cfg.margem_para_preferir_combo:
        melhor_combo["escolha"] = (
            f"combo: probabilidade ajustada {p_combo:.1%} supera a da melhor "
            f"simples ({p_simples:.1%}) em mais de "
            f"{cfg.margem_para_preferir_combo:.0%}, pelo mesmo preco")
        return melhor_combo
    melhor_simples["escolha"] = (
        f"simples: a melhor combinacao ({p_combo:.1%}) nao supera a simples "
        f"({p_simples:.1%}) o bastante pra pagar a segunda maneira de perder")
    return melhor_simples
