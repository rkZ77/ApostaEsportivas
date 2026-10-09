"""
medir_erro_das_casas.py · engenharia reversa do preco das casas

SOMENTE LEITURA. Pode rodar contra PROD.

Uso (da pasta onde esta' o .env.prod):
  python ApostaEsportivas/src/scripts/medir_erro_das_casas.py [--dias 30] [--limite 400]

POR QUE ESTE SCRIPT (2026-10-09). O usuario quer usar o jeito que a casa monta
o preco contra ela. A casa nao ganha porque o apostador da' red: ela ganha
com a MARGEM embutida na odd (num Over/Under justo a 2,00/2,00 ela paga
1,90/1,90). Quem aposta no preco dela perde a margem no longo prazo, acertando
ou errando cada jogo. Entao a pergunta util tem duas partes:

  1. ONDE o pedagio e' mais barato   -> margem por casa e por mercado
  2. ONDE a casa erra o preco        -> odd que paga MAIS que o justo

O "justo" e' o consenso sem margem das casas no FECHAMENTO (ultima foto ate'
30 min do apito): e' o preco que o mercado inteiro decidiu com toda a
informacao. Odd acima dele = a casa errou, e o green paga mais do que devia.
Isso e' CLV, a metrica que manda no motor (ver medir_calibracao_dos_picks).

A REGRA TESTADA (secoes 4 e 5) usa so' o que se sabia na hora: numa janela
antes do jogo (60, 180, 360, 720 min), a odd de UMA casa e' comparada com o
consenso sem margem das OUTRAS casas naquele mesmo momento. Se ela paga X%
acima ("casa fora da curva"), o sinal dispara. O fechamento diz depois se a
casa estava errada (CLV justo > 0) ou se ela sabia algo (CLV justo < 0).

CADENCIA DAS FOTOS. A coleta pre-jogo roda a cada ~3h. Foto ate' 30 min do
apito so' existe nos jogos COM pick (capturar_fechamento, a cada 10 min). Com
o corte padrao de 30 min, o fechamento so' existe nesses jogos. `--fechamento
180` aceita a ultima foto ate' 3h do apito e cobre quase todo jogo, com um
juiz menos afiado. Janela que nao fica antes do corte e' pulada, pra foto
"cedo" nunca ser a mesma do fechamento.

LIMITES. (a) O juiz e' o consenso de casas "soft" (Bet365, 1xBet, Betano,
Superbet); uma casa afiada como a Pinnacle seria juiz melhor. (b) As linhas do
mesmo jogo andam juntas, entao o ±2ep trata como independente o que nao e':
por isso a secao 5 separa descoberta x confirmacao por data. (c) Handicap
asiatico e placar exato ficam fora: so' entram mercados de 2 ou 3 resultados
completos (Over/Under, Sim/Nao, 1X2...).
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection  # noqa: E402

#: Fechamento = ultima foto pre-jogo, desde que ate' este minuto do apito.
FECHAMENTO_MAX_MIN = 30
#: Janelas (minutos antes do apito) em que a regra olharia o preco.
JANELAS = (60, 180, 360, 720)
#: Quanto acima do consenso das outras casas a odd precisa pagar.
LIMIARES = (0.02, 0.05, 0.08)
#: Limiar usado na confirmacao e na leitura.
LIMIAR_LEITURA = 0.05
#: Overround fora disso e' grupo incompleto ou mercado mal lido.
OVERROUND_MIN, OVERROUND_MAX = 1.0, 1.30

_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")


# ── funcoes puras (testadas em tests/test_erro_das_casas_2026_10.py) ────────

def linha_do_valor(value_name: str | None, line_value) -> str:
    """A linha que junta os lados do mesmo mercado ("Over 2.5" com
    "Under 2.5"). O handicap vem cru, COM sinal: "Home -1" e "Away +1" caem
    em grupos diferentes de um resultado so' e saem pelo filtro -- de
    proposito, ver LIMITES (c)."""
    if line_value not in (None, ""):
        return str(line_value).strip()
    m = _NUMERO.search(value_name or "")
    return m.group(0).replace(",", ".") if m else ""


def foto(linhas: list, minimo: int, maximo: int | None = None) -> dict:
    """{(casa, mercado, linha, valor): odd} da ultima cotacao com pelo menos
    `minimo` minutos para o apito. `linhas` ja' vem ordenada por minuto
    crescente, entao a primeira que passa e' a mais proxima do apito."""
    out = {}
    for casa, mercado, valor, lv, odd, minutos in linhas:
        if minutos is None or minutos < minimo:
            continue
        chave = (casa, mercado, linha_do_valor(valor, lv), valor)
        if chave in out:
            continue
        if maximo is not None and minutos > maximo:
            # Mais longe do apito que o aceito: a chave fica marcada como
            # vista (as proximas linhas so' sao mais antigas) mas sem odd.
            out[chave] = None
            continue
        out[chave] = float(odd)
    return {k: v for k, v in out.items() if v}


def agrupar(f: dict) -> dict:
    """{(casa, mercado, linha): {valor: odd}}."""
    g = defaultdict(dict)
    for (casa, mercado, linha, valor), odd in f.items():
        g[(casa, mercado, linha)][valor] = odd
    return g


def sem_margem(odds: dict):
    """(overround, {valor: prob_justa}) de um grupo completo, ou None."""
    if len(odds) not in (2, 3) or any(":" in (v or "") for v in odds):
        return None
    ov = sum(1.0 / o for o in odds.values())
    if not (OVERROUND_MIN <= ov <= OVERROUND_MAX):
        return None
    return ov, {v: (1.0 / o) / ov for v, o in odds.items()}


def consenso(normalizados: dict, sem_casa=None) -> dict:
    """{(mercado, linha, resultados): {valor: prob}} -- media das casas que
    cotam o MESMO conjunto de resultados. `sem_casa` tira uma casa da conta
    (o consenso "das outras")."""
    soma = defaultdict(lambda: defaultdict(float))
    n = defaultdict(int)
    for (casa, mercado, linha), (_, probs) in normalizados.items():
        if casa == sem_casa:
            continue
        k = (mercado, linha, frozenset(probs))
        n[k] += 1
        for v, p in probs.items():
            soma[k][v] += p
    return {k: {v: s / n[k] for v, s in vs.items()} for k, vs in soma.items()}


class Acum:
    __slots__ = ("n", "s", "s2", "pos")

    def __init__(self):
        self.n, self.s, self.s2, self.pos = 0, 0.0, 0.0, 0

    def add(self, x: float):
        self.n += 1
        self.s += x
        self.s2 += x * x
        self.pos += x > 0

    @property
    def media(self):
        return self.s / self.n if self.n else 0.0

    @property
    def ep(self):
        if self.n < 2:
            return 0.0
        var = max(self.s2 / self.n - self.media ** 2, 0.0) * self.n / (self.n - 1)
        return math.sqrt(var / self.n)


def analisar_jogo(linhas: list, dia, res: dict,
                  fechamento_max: int = FECHAMENTO_MAX_MIN) -> bool:
    """Acumula em `res` tudo o que um jogo ensina. Devolve False quando o
    jogo nao tem fechamento perto do apito (nao entra na conta do CLV)."""
    linhas = sorted(linhas, key=lambda r: r[5])

    fech = {k: x for k, g in agrupar(foto(linhas, 0, fechamento_max)).items()
            if (x := sem_margem(g))}
    if not fech:
        return False
    justo = consenso(fech)
    for (casa, mercado, linha), (ov, probs) in fech.items():
        res["margem_casa"][casa].add(ov - 1)
        res["margem_mercado"][(mercado, casa)].add(ov - 1)

    for janela in JANELAS:
        if janela <= fechamento_max:
            continue
        cedo = {}
        odds_cedo = {}
        for k, g in agrupar(foto(linhas, janela)).items():
            x = sem_margem(g)
            if x:
                cedo[k] = x
                odds_cedo[k] = g
        casas = {c for c, _, _ in cedo}
        outras_por_casa = {c: consenso(cedo, sem_casa=c) for c in casas}
        for (casa, mercado, linha), (_, probs) in cedo.items():
            chave = (mercado, linha, frozenset(probs))
            fim = justo.get(chave)
            outras = outras_por_casa[casa].get(chave)
            if not fim or not outras:
                continue
            for valor, odd in odds_cedo[(casa, mercado, linha)].items():
                clv = odd * fim[valor] - 1
                res["base"][(janela, casa)].add(clv)
                desvio = odd * outras[valor] - 1
                if desvio >= LIMIARES[0]:
                    res["sinais"].append((dia, casa, mercado, janela, desvio, clv))
    return True


# ── banco ───────────────────────────────────────────────────────────────────

def _conexao():
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
    except Exception:
        pass
    return conn


def _nomes(cur, sql: str) -> dict:
    try:
        cur.execute(sql)
        return {a: b for a, b in cur.fetchall()}
    except Exception:
        cur.connection.rollback()
        return {}


def carregar_e_analisar(dias: int, limite: int,
                        fechamento_max: int = FECHAMENTO_MAX_MIN) -> tuple[dict, dict, dict]:
    res = {
        "fechamento_max": fechamento_max,
        "margem_casa": defaultdict(Acum),
        "margem_mercado": defaultdict(Acum),
        "base": defaultdict(Acum),
        "sinais": [],
        "jogos": 0,
        "com_fechamento": 0,
    }
    conn = _conexao()
    try:
        cur = conn.cursor()
        casas = _nomes(cur, "SELECT bookmaker_id, bookmaker_name FROM bookmakers")
        mercados = _nomes(cur, "SELECT bet_id, COALESCE(market_pt, market_en) FROM bet_markets_map")
        cur.execute("""
            SELECT fixture_id, MAX(match_datetime)
              FROM odds_snapshots
             WHERE match_datetime >= %s
               AND match_datetime < NOW() - INTERVAL '2 hours'
             GROUP BY fixture_id
             ORDER BY 2 DESC
             LIMIT %s
        """, (date.today() - timedelta(days=dias), limite))
        jogos = cur.fetchall()
        for fixture_id, quando in jogos:
            cur.execute("""
                SELECT bookmaker_id, market_id, value_name, line_value,
                       odd_value, minutes_to_kickoff
                  FROM odds_snapshots
                 WHERE fixture_id = %s
                   AND minutes_to_kickoff BETWEEN 0 AND 1440
                   AND odd_value > 1
            """, (fixture_id,))
            res["jogos"] += 1
            if analisar_jogo(cur.fetchall(), quando.date() if quando else None, res,
                             fechamento_max):
                res["com_fechamento"] += 1
        cur.close()
    finally:
        conn.close()
    return res, casas, mercados


# ── relatorio ───────────────────────────────────────────────────────────────

def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def _linha_clv(rotulo: str, a: Acum) -> None:
    if not a.n:
        print(f"  {rotulo:34} {'-':>6}")
        return
    print(f"  {rotulo:34} {a.n:>6} {_pct(a.media):>8} {2 * a.ep * 100:>6.1f}pp {a.pos / a.n:>6.0%}")


def _cab_clv() -> None:
    print(f"  {'':34} {'n':>6} {'CLV':>8} {'±2ep':>8} {'% >0':>6}")


def _acumular(sinais, filtro) -> Acum:
    a = Acum()
    for s in sinais:
        if filtro(s):
            a.add(s[5])
    return a


def relatorio(res: dict, casas: dict, mercados: dict) -> None:
    nc = lambda c: str(casas.get(c, c))  # noqa: E731
    nm = lambda m: str(mercados.get(m, m))[:34]  # noqa: E731

    print("Engenharia reversa do preco das casas")
    print(f"Jogos lidos: {res['jogos']} · com fechamento ate' {res['fechamento_max']} min do apito: "
          f"{res['com_fechamento']}")
    if not res["com_fechamento"]:
        print("Nenhum jogo com fechamento: nada a medir.")
        return

    print("\n=== 1. Pedagio (margem) de cada casa no fechamento ===")
    print("  Quanto a casa embute na odd. Menor = green paga mais.")
    print(f"  {'casa':34} {'grupos':>6} {'margem':>8}")
    for c, a in sorted(res["margem_casa"].items(), key=lambda kv: kv[1].media):
        print(f"  {nc(c):34} {a.n:>6} {a.media * 100:>7.2f}%")

    print("\n=== 2. Pedagio por mercado (os 20 com mais linhas) ===")
    todas_casas = sorted(res["margem_casa"])
    por_mercado = defaultdict(dict)
    for (m, c), a in res["margem_mercado"].items():
        por_mercado[m][c] = a
    topo = sorted(por_mercado, key=lambda m: -sum(a.n for a in por_mercado[m].values()))[:20]
    print(f"  {'mercado':34} " + " ".join(f"{nc(c)[:9]:>9}" for c in todas_casas))
    for m in topo:
        cel = []
        for c in todas_casas:
            a = por_mercado[m].get(c)
            cel.append(f"{a.media * 100:>8.1f}%" if a and a.n >= 10 else f"{'-':>9}")
        print(f"  {nm(m):34} " + " ".join(cel))

    print("\n=== 3. Toda odd cedo contra o fechamento justo (sem filtro nenhum) ===")
    print("  Referencia: apostar em tudo. Esperado ~ -margem. E' a regua das secoes 4 e 5.")
    _cab_clv()
    janelas = [j for j in JANELAS if j > res["fechamento_max"]]
    for janela in janelas:
        for c in todas_casas:
            _linha_clv(f"{janela:>4} min · {nc(c)}", res["base"].get((janela, c), Acum()))

    sinais = res["sinais"]
    print("\n=== 4. Casa fora da curva: odd acima do consenso das OUTRAS casas ===")
    print("  Sinal sabido na hora. CLV > 0 = a casa errou e o fechamento confirmou.")
    for lim in LIMIARES:
        print(f"\n  -- paga >= {lim:.0%} acima das outras --")
        _cab_clv()
        for c in todas_casas:
            _linha_clv(nc(c), _acumular(sinais, lambda s: s[4] >= lim and s[1] == c))
        for janela in janelas:
            _linha_clv(f"janela {janela} min",
                       _acumular(sinais, lambda s: s[4] >= lim and s[3] == janela))

    print(f"\n  -- por mercado, paga >= {LIMIAR_LEITURA:.0%} acima (n >= 30) --")
    _cab_clv()
    por_m = defaultdict(Acum)
    for s in sinais:
        if s[4] >= LIMIAR_LEITURA:
            por_m[s[2]].add(s[5])
    for m, a in sorted(por_m.items(), key=lambda kv: -kv[1].media):
        if a.n >= 30:
            _linha_clv(nm(m), a)

    print(f"\n=== 5. Descoberta x confirmacao por data (sinal >= {LIMIAR_LEITURA:.0%}) ===")
    dias = sorted({s[0] for s in sinais if s[0]})
    if len(dias) < 4:
        print("  Poucos dias com sinal para separar em duas metades.")
        return
    corte = dias[len(dias) // 2]
    print(f"  descoberta: antes de {corte} · confirmacao: de {corte} em diante")
    print(f"  {'':34} {'n desc':>7} {'CLV desc':>9} {'n conf':>7} {'CLV conf':>9}")
    grupos = {}
    for s in sinais:
        if s[4] < LIMIAR_LEITURA or not s[0]:
            continue
        metade = 0 if s[0] < corte else 1
        for chave in (("casa", s[1]), ("mercado", s[2]), ("casa+mercado", (s[1], s[2]))):
            grupos.setdefault(chave, (Acum(), Acum()))[metade].add(s[5])
    achados = []
    for (tipo, k), (d, c) in sorted(grupos.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        if d.n < 30 or c.n < 30:
            continue
        rot = (nc(k) if tipo == "casa" else nm(k) if tipo == "mercado"
               else f"{nc(k[0])[:9]} · {nm(k[1])}")[:34]
        print(f"  {rot:34} {d.n:>7} {_pct(d.media):>9} {c.n:>7} {_pct(c.media):>9}")
        total = Acum()
        for a in (d, c):
            total.n += a.n
            total.s += a.s
            total.s2 += a.s2
        if d.media > 0 and c.media > 0 and total.media - 2 * total.ep > 0:
            achados.append((rot, d, c))

    print("\n=== Leitura ===")
    if not achados:
        print("  Nenhum erro de casa confirmado nas duas metades. Ainda nao ha' onde")
        print("  apontar o motor: rode de novo quando o arquivo de odds tiver mais dias.")
    else:
        print("  Erro de casa que se repetiu nas DUAS metades (candidato a sinal no motor,")
        print("  primeiro em sombra, pela regra de medir antes de ligar):")
        for rot, d, c in achados:
            print(f"    {rot}: {_pct(d.media)} na descoberta, {_pct(c.media)} na confirmacao")
    print("  Lembrete: o juiz e' o consenso de casas soft; com a Pinnacle como regua a")
    print("  leitura ficaria mais firme (ver LIMITES no topo do arquivo).")


def main():
    p = argparse.ArgumentParser(description="Engenharia reversa do preco das casas")
    p.add_argument("--dias", type=int, default=30)
    p.add_argument("--limite", type=int, default=400,
                   help="jogos mais recentes lidos (cabe nos 15 min do agendador)")
    p.add_argument("--fechamento", type=int, default=FECHAMENTO_MAX_MIN,
                   help="ultima foto ate' N min do apito vale como fechamento "
                        "(30 = so' jogos com pick; 180 = quase todos)")
    a = p.parse_args()
    res, casas, mercados = carregar_e_analisar(a.dias, a.limite, a.fechamento)
    relatorio(res, casas, mercados)


if __name__ == "__main__":
    main()
