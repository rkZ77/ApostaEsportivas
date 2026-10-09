"""Efeito MEDIDO do confronto tatico sobre cada mercado (2026-10-08).

A PERGUNTA
----------
O motor ja' espera, pra cada lado, o que o time FAZ e o que o adversario
CEDE (stats_model.expected_value_convergence). Isso nao sabe COMO os dois
jogam: um time de posse alta contra um bloco baixo pode render mais
escanteios do que as duas medias somadas dizem; um ataque direto contra uma
linha alta pode render mais gols. A pergunta e' se o estilo dos dois
ACRESCENTA informacao ao que as medias ja dizem.

A FORMULACAO (por que isso nao conta nada duas vezes)
-----------------------------------------------------
Regressao de Poisson com OFFSET no lambda do modelo-base:

    log E[contagem do time] = log(lambda_base) + b0 + soma(b_i * x_i)

O offset faz a regressao explicar so' o RESIDUO do modelo-base. Tudo que a
media de feitos/cedidos ja captura fica com o offset; os b_i so' ficam
diferentes de zero se o estilo explicar o que sobra. As features sao
padronizadas (media 0, desvio 1 na amostra de estimacao): feature ausente
vira 0, ou seja, NEUTRA -- sem dado, o lambda e' o de sempre.

`b0` (intercepto) e' estimado e NAO e' aplicado: ele corrige o nivel do
modelo-base, que e' trabalho da recalibracao, nao da tatica.

Arbitro fica FORA das features de cartao de proposito: ele ja' tem lambda
proprio no motor (referee_model). Desfalque entra como titular habitual
fora POR POSICAO -- e sai da conta quando o contexto atual ja' o usa (ver
`multiplicadores`, regra de redundancia).

A VALIDACAO (scripts/medir_efeito_tatico.py)
--------------------------------------------
Estima na metade mais antiga, valida na mais nova, por mercado e por
competicao: log-verossimilhanca por jogo, Brier e log-loss das linhas
padrao (P(total > linha) com a dispersao medida do motor). Coeficiente so'
fica com |b/ep| >= 2 (ep com a sobredispersao estimada), e so' fica se o
SINAL se repete estimado so' na metade nova. Mercado so' e' `aprovado` com
ganho fora da amostra maior que 2 erros-padrao.

`MOTOR_TATICO`: off | shadow (padrao) | on. Em `on` so' os mercados
aprovados entram na conta.
"""
from __future__ import annotations

import json
import math
import os
import time

#: Contagem do time -> familia do motor e coluna da folha.
ESTATISTICAS = {
    "gols": ("goals", "goals"),
    "escanteios": ("corners", "corners"),
    "cartoes": ("cards", "yellow_cards"),     # = convencao de stats_model (amarelos)
    "faltas": ("fouls", "fouls"),
    "chutes": ("shots", "total_shots"),
}
FAMILIA_PARA_ESTATISTICA = {fam: est for est, (fam, _) in ESTATISTICAS.items()}

#: Features, sempre do ponto de vista do time cuja contagem se explica.
FEATURES = (
    "posse_propria", "posse_adv", "choque_de_posse",
    "diretividade_propria", "diretividade_adv",
    "fora_da_area_propria", "xg_por_chute_proprio",
    "linha_alta_propria", "linha_alta_adv", "faltas_adv",
    "linha_de_tres_propria", "linha_de_tres_adv",
    "ausentes_defesa_propria", "ausentes_ataque_propria", "ausentes_defesa_adv",
    "tecnico_novo_proprio", "chuva_mm", "vento_kmh", "altitude_visitante",
)
#: Desfalque: as features que saem quando o contexto atual ja' conta desfalque.
FEATURES_DE_DESFALQUE = ("ausentes_defesa_propria", "ausentes_ataque_propria",
                         "ausentes_defesa_adv")

#: Teto do multiplicador: nenhum estilo vale mais que +-25% do lambda. Rede de
#: seguranca contra feature extrema fora da faixa da estimacao, nao ajuste.
TETO_LOG = math.log(1.25)


def modo() -> str:
    m = os.getenv("MOTOR_TATICO", "shadow").strip().lower()
    return m if m in ("off", "shadow", "on") else "shadow"


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
def _enc(perfil: dict | None, nome: str):
    v = ((perfil or {}).get("metricas") or {}).get(nome)
    return None if v is None else v.get("encolhida")


def vetor(perfil_proprio: dict, perfil_adv: dict, extras: dict | None = None) -> dict:
    """As features cruas (antes de padronizar). Ausente = None."""
    e = extras or {}
    posse_p, posse_a = _enc(perfil_proprio, "posse"), _enc(perfil_adv, "posse")
    return {
        "posse_propria": posse_p, "posse_adv": posse_a,
        "choque_de_posse": ((posse_p - 50) * (posse_a - 50) / 100
                            if posse_p is not None and posse_a is not None else None),
        "diretividade_propria": _enc(perfil_proprio, "chutes_por_100_passes"),
        "diretividade_adv": _enc(perfil_adv, "chutes_por_100_passes"),
        "fora_da_area_propria": _enc(perfil_proprio, "fracao_chutes_fora_da_area"),
        "xg_por_chute_proprio": _enc(perfil_proprio, "xg_por_chute"),
        "linha_alta_propria": _enc(perfil_proprio, "impedimentos_provocados"),
        "linha_alta_adv": _enc(perfil_adv, "impedimentos_provocados"),
        "faltas_adv": _enc(perfil_adv, "faltas"),
        "linha_de_tres_propria": e.get("linha_de_tres_propria"),
        "linha_de_tres_adv": e.get("linha_de_tres_adv"),
        "ausentes_defesa_propria": e.get("ausentes_defesa_propria"),
        "ausentes_ataque_propria": e.get("ausentes_ataque_propria"),
        "ausentes_defesa_adv": e.get("ausentes_defesa_adv"),
        "tecnico_novo_proprio": e.get("tecnico_novo_proprio"),
        "chuva_mm": e.get("chuva_mm"), "vento_kmh": e.get("vento_kmh"),
        "altitude_visitante": e.get("altitude_visitante"),
    }


def padronizar(cru: dict, medias: dict, desvios: dict) -> list:
    """Na ordem de FEATURES. Ausente ou sem desvio -> 0 (neutro)."""
    saida = []
    for f in FEATURES:
        v, m, d = cru.get(f), medias.get(f), desvios.get(f)
        saida.append(0.0 if v is None or m is None or not d else (float(v) - m) / d)
    return saida


def medias_e_desvios(linhas: list) -> tuple:
    """Media e desvio de cada feature crua, so' nos valores presentes."""
    medias, desvios = {}, {}
    for f in FEATURES:
        vals = [float(r[f]) for r in linhas if r.get(f) is not None]
        if len(vals) < 30:
            continue
        m = sum(vals) / len(vals)
        d = math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
        if d > 0:
            medias[f], desvios[f] = m, d
    return medias, desvios


# ---------------------------------------------------------------------------
# Regressao de Poisson com offset (IRLS + ridge), Python puro
# ---------------------------------------------------------------------------
def _resolver(a: list, b: list) -> list:
    """Gauss com pivoteamento parcial. `a` e' p x p, `b` tem p."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-12:
            raise ValueError("matriz singular")
        m[c], m[piv] = m[piv], m[c]
        for r in range(c + 1, n):
            f = m[r][c] / m[c][c]
            if f:
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][k] * x[k] for k in range(r + 1, n))) / m[r][r]
    return x


def _inversa(a: list) -> list:
    n = len(a)
    cols = [_resolver(a, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]
    return [[cols[j][i] for j in range(n)] for i in range(n)]


def ajustar_poisson(X: list, y: list, offset: list, ridge: float = 1.0,
                    iteracoes: int = 25, tol: float = 1e-7) -> dict:
    """Poisson com log-link e offset. Coluna 0 de X deve ser o intercepto
    (sem penalidade). Devolve coeficientes, erro-padrao QUASI-POISSON
    (escalado pela dispersao de Pearson) e a dispersao."""
    p = len(X[0])
    beta = [0.0] * p
    for _ in range(iteracoes):
        xtwx = [[0.0] * p for _ in range(p)]
        xtwz = [0.0] * p
        for xi, yi, oi in zip(X, y, offset):
            eta_sem = sum(b * v for b, v in zip(beta, xi))
            mu = math.exp(min(max(oi + eta_sem, -20), 20))
            z = eta_sem + (yi - mu) / mu
            for a in range(p):
                xa = xi[a]
                if not xa:
                    continue
                wxa = mu * xa
                xtwz[a] += wxa * z
                linha = xtwx[a]
                for b in range(a, p):
                    linha[b] += wxa * xi[b]
        for a in range(p):
            for b in range(a):
                xtwx[a][b] = xtwx[b][a]
            if a > 0:
                xtwx[a][a] += ridge
        novo = _resolver(xtwx, xtwz)
        mudou = max(abs(n - o) for n, o in zip(novo, beta))
        beta = novo
        if mudou < tol:
            break
    pearson, n = 0.0, len(y)
    for xi, yi, oi in zip(X, y, offset):
        mu = math.exp(min(max(oi + sum(b * v for b, v in zip(beta, xi)), -20), 20))
        pearson += (yi - mu) ** 2 / mu
    phi = max(1.0, pearson / max(1, n - p))
    cov = _inversa(xtwx)
    ep = [math.sqrt(max(cov[i][i], 0.0) * phi) for i in range(p)]
    return {"beta": beta, "ep": ep, "dispersao": phi, "n": n}


def loglik_poisson(y: int, mu: float) -> float:
    mu = max(mu, 1e-9)
    return y * math.log(mu) - mu - math.lgamma(y + 1)


# ---------------------------------------------------------------------------
# Aplicacao
# ---------------------------------------------------------------------------
def contribuicoes(z: list, coefs: dict, excluir: tuple = ()) -> dict:
    """{feature: b*x} so' das features com coeficiente guardado."""
    saida = {}
    for f, x in zip(FEATURES, z):
        c = coefs.get(f)
        if c is None or f in excluir or not x:
            continue
        saida[f] = round(c["beta"] * x, 5)
    return saida


def multiplicador(contrib: dict) -> float:
    s = sum(contrib.values())
    return round(math.exp(max(-TETO_LOG, min(TETO_LOG, s))), 4)


_CACHE: dict = {"em": 0.0, "tabela": None}
_TTL = 3600


DDL = """CREATE TABLE IF NOT EXISTS efeitos_taticos (
    estatistica  TEXT PRIMARY KEY,
    coefs        JSONB NOT NULL,
    medias       JSONB NOT NULL,
    desvios      JSONB NOT NULL,
    aprovado     BOOLEAN NOT NULL DEFAULT FALSE,
    validacao    JSONB,
    ajustado_em  TIMESTAMP DEFAULT NOW()
)"""


def tabela_em_cache() -> dict:
    """{estatistica: {coefs, medias, desvios, aprovado, validacao}} ou {}.
    Sem tabela (ninguem rodou a medicao com --gravar) -> {} e nada muda."""
    agora = time.time()
    if _CACHE["tabela"] is not None and agora - _CACHE["em"] < _TTL:
        return _CACHE["tabela"]
    tabela = {}
    try:
        from utils.db_utils import get_connection
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT estatistica, coefs, medias, desvios, aprovado, validacao "
                        "FROM efeitos_taticos")
            for est, coefs, medias, desvios, aprovado, validacao in cur.fetchall():
                ler = lambda v: json.loads(v) if isinstance(v, str) else (v or {})
                tabela[est] = {"coefs": ler(coefs), "medias": ler(medias),
                               "desvios": ler(desvios), "aprovado": bool(aprovado),
                               "validacao": ler(validacao)}
        finally:
            cur.close()
            conn.close()
    except Exception:
        tabela = {}
    _CACHE.update(em=agora, tabela=tabela)
    return tabela


def multiplicadores(perfil_casa: dict, perfil_fora: dict, extras_casa: dict,
                    extras_fora: dict, tabela: dict | None = None,
                    excluir_desfalques: bool = False) -> dict:
    """{estatistica: {"home": {...}, "away": {...}, "aprovado": bool}}.

    Cada lado: multiplicador do lambda e as contribuicoes feature a feature
    (o rastro do porque). `excluir_desfalques`: o contexto atual ja' conta
    desfalque na amostra efetiva; aqui ele sai pra nao punir duas vezes."""
    tabela = tabela if tabela is not None else tabela_em_cache()
    excluir = FEATURES_DE_DESFALQUE if excluir_desfalques else ()
    saida = {}
    for est, t in (tabela or {}).items():
        lados = {}
        for lado, (pp, pa, ex) in (("home", (perfil_casa, perfil_fora, extras_casa)),
                                   ("away", (perfil_fora, perfil_casa, extras_fora))):
            z = padronizar(vetor(pp, pa, ex), t["medias"], t["desvios"])
            contrib = contribuicoes(z, t["coefs"], excluir)
            lados[lado] = {"multiplicador": multiplicador(contrib),
                           "contribuicoes": dict(sorted(contrib.items(),
                                                        key=lambda kv: -abs(kv[1]))[:5])}
        saida[est] = {**lados, "aprovado": t.get("aprovado", False),
                      **({"redundante_com_contexto": list(excluir)} if excluir else {})}
    return saida


def _do_regime(jogos: list, regime: dict | None, minimo: int = 5) -> list:
    """Os jogos do tecnico atual quando ele tem `minimo`+ -- o mesmo recorte
    da estimacao (scripts/medir_efeito_tatico.montar_linhas)."""
    from services.pick_engine.contexto_atual import _dia
    inicio = _dia((regime or {}).get("inicio"))
    if not inicio:
        return jogos
    do_regime = [m for m in jogos or [] if (_dia(m.get("match_date")) or inicio) >= inicio]
    return do_regime if len(do_regime) >= minimo else jogos


def preparar_partida(contexto: dict | None, last10_home: list, last10_away: list,
                     home_team_id: int, away_team_id: int, tabela: dict | None = None,
                     excluir_desfalques: bool = False) -> dict | None:
    """Perfis, extras e multiplicadores da partida -- uma vez por jogo.

    None quando MOTOR_TATICO=off ou quando nao ha' tabela medida: sem
    coeficiente estimado nao existe efeito a registrar, e o motor fica como
    esta'. Dado ausente vira feature neutra, nunca um palpite."""
    if modo() == "off":
        return None
    tabela = tabela if tabela is not None else tabela_em_cache()
    if not tabela:
        return None
    from services.pick_engine import team_profile_model as tpm
    ctx = contexto or {}
    ref = ctx.get("referencia_tatica")
    perfis, extras = {}, {}
    for lado, tid, hist in (("home", home_team_id, last10_home), ("away", away_team_id, last10_away)):
        t = ctx.get(lado) or {}
        regime = t.get("regime") or {}
        perfis[lado] = tpm.perfil_tatico(_do_regime(hist, regime), tid, ref)
        aus = t.get("ausentes_por_posicao") or {}
        jogos_tec = regime.get("jogos_sob_tecnico")
        cl = ctx.get("clima") or {}
        alt = cl.get("altitude_m")
        extras[lado] = {
            "linha_de_tres_propria": t.get("linha_de_tres"),
            "ausentes_defesa_propria": aus.get("defesa"),
            "ausentes_ataque_propria": aus.get("ataque"),
            "tecnico_novo_proprio": (None if jogos_tec is None else (1.0 if jogos_tec < 5 else 0.0)),
            "chuva_mm": (min(float(cl["chuva_mm"]), 10.0) if cl.get("chuva_mm") is not None else None),
            "vento_kmh": (float(cl["vento_kmh"]) if cl.get("vento_kmh") is not None else None),
            "altitude_visitante": ((float(alt) / 1000 if lado == "away" else 0.0)
                                   if alt is not None else None),
        }
    for lado, adv in (("home", "away"), ("away", "home")):
        extras[lado]["linha_de_tres_adv"] = extras[adv]["linha_de_tres_propria"]
        extras[lado]["ausentes_defesa_adv"] = extras[adv]["ausentes_defesa_propria"]
    mult = multiplicadores(perfis["home"], perfis["away"], extras["home"], extras["away"],
                           tabela, excluir_desfalques=excluir_desfalques)
    return {"perfis": perfis, "extras": extras, "multiplicadores": mult}


def lambda_tatico(lam: float | None, scope: str | None, lam_casa: float | None,
                  lam_fora: float | None, mult: dict) -> float | None:
    """O lambda do mercado com o efeito de cada lado. Total: o lambda do
    motor reescalado pela soma dos lados ajustados (o lambda total do motor
    inclui a mistura por causa e nao e' exatamente casa + fora)."""
    if lam is None or not mult:
        return None
    mh = (mult.get("home") or {}).get("multiplicador", 1.0)
    ma = (mult.get("away") or {}).get("multiplicador", 1.0)
    if scope == "home":
        return round(lam * mh, 4)
    if scope == "away":
        return round(lam * ma, 4)
    if lam_casa and lam_fora:
        return round(lam * (lam_casa * mh + lam_fora * ma) / (lam_casa + lam_fora), 4)
    return round(lam * (mh + ma) / 2, 4)
