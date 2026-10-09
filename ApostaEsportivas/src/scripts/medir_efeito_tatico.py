"""
medir_efeito_tatico.py · o confronto tatico acrescenta informacao ao modelo-base?

Uso:
  DB_ENV=prod python src/scripts/medir_efeito_tatico.py            (so' le e mede)
  DB_ENV=prod python src/scripts/medir_efeito_tatico.py --gravar   (grava efeitos_taticos)

SEM --gravar e' SOMENTE LEITURA.

O QUE FAZ
---------
1. Monta, pra CADA partida encerrada da base e pros DOIS times dela, a linha
   de estimacao -- usando so' o que existia ANTES daquela partida:
     perfil tatico (team_profile_model.perfil_tatico), do regime do tecnico
       da partida quando ele tem 5+ jogos, encolhido pra media da competicao
       acumulada ate' ali;
     o lambda do modelo-base (stats_model.expected_value_convergence nos
       15 jogos anteriores de cada time);
     titulares habituais fora (escalacao da partida x 5 anteriores), formacao,
       tecnico novo, clima.
   Isto e' o "sem vazamento": a linha da partida N nunca le a partida N nem
   nenhuma depois dela.
2. Por mercado (gols, escanteios, cartoes, faltas, chutes): estima a
   regressao de Poisson com offset no lambda-base (services/pick_engine/
   efeito_tatico.py) na METADE MAIS ANTIGA, guarda so' coeficiente com
   |b/ep| >= 2, e avalia na METADE MAIS NOVA contra o modelo-base (mesmas
   partidas): log-verossimilhanca por jogo, Brier, log-loss e calibracao da
   linha padrao do mercado, no geral, por competicao e liga x copa.
3. ESTABILIDADE: re-estima so' na metade nova; coeficiente cujo sinal nao se
   repete (ou some) nao e' aplicado. Esse corte so' REPROVA -- nao escolhe o
   que melhora a metrica, entao nao contamina a validacao.
4. APROVADO = ganho de log-verossimilhanca > 2 erros-padrao, log-loss da
   linha padrao menor que o do base, e pelo menos um coeficiente estavel.
5. --gravar: re-estima em tudo, guarda os coeficientes significativos e o
   veredito em `efeitos_taticos`. O motor so' APLICA os aprovados, e so' com
   MOTOR_TATICO=on; em shadow ele registra todos.

ROI: nao da' pra medir aqui -- nao ha' odd historica dessas linhas pra base
inteira (odds_snapshots guarda 45 dias, so' dos jogos coletados). O ROI sai
do bloco PICKS, que cruza o `tatico_sombra` gravado no log de decisao com o
resultado dos picks.
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pick_engine import efeito_tatico as et  # noqa: E402
from services.pick_engine import team_profile_model as tpm  # noqa: E402

JANELA = 15            # jogos anteriores por time (a janela do motor)
MIN_JOGOS = 5          # abaixo disto o time nao entra na estimacao
MIN_JOGOS_TECNICO = 5  # perfil do regime do tecnico so' com 5+ jogos dele
Z_MINIMO = 2.0
MAX_LINHAS = 30000     # por mercado, as mais recentes (IRLS em Python puro)
MIN_COMPETICAO = 150   # partidas pra reportar uma competicao
LINHAS_PADRAO = {"gols": 2.5, "escanteios": 9.5, "cartoes": 3.5,
                 "faltas": 24.5, "chutes": 24.5}

_COLUNAS = (
    "fixture_id", "match_date", "league_id", "season", "home_team_id", "away_team_id",
    "home_goals", "away_goals", "home_goals_ht", "away_goals_ht",
    "home_corners", "away_corners", "home_corners_1h", "away_corners_1h",
    "home_yellow_cards", "away_yellow_cards", "home_red_cards", "away_red_cards",
    "home_fouls", "away_fouls", "home_offsides", "away_offsides",
    "home_possession", "away_possession", "home_passes", "away_passes",
    "home_passes_accuracy", "away_passes_accuracy",
    "home_total_shots", "away_total_shots", "home_total_shots_1h", "away_total_shots_1h",
    "home_shots_on", "away_shots_on",
    "home_shots_insidebox", "away_shots_insidebox",
    "home_shots_outsidebox", "away_shots_outsidebox", "home_xg", "away_xg",
)


# ---------------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------------
def carregar(cur) -> tuple:
    cur.execute(f"""SELECT {', '.join(_COLUNAS)} FROM match_statistics
                     WHERE status IN ('FT','AET','PEN') AND match_date IS NOT NULL
                     ORDER BY match_date, fixture_id""")
    jogos = [dict(zip(_COLUNAS, r)) for r in cur.fetchall()]
    escal = {}
    try:
        cur.execute("SELECT fixture_id, team_id, coach_id, coach_name, formation, titulares "
                    "FROM team_lineups")
        for fid, tid, cid, cnome, form, tit in cur.fetchall():
            escal[(fid, tid)] = {"coach": cid if cid is not None else cnome,
                                 "formation": form, "titulares": set(tit or [])}
    except Exception:
        cur.connection.rollback()
    posicoes = {}
    try:
        cur.execute("""SELECT player_id, position FROM (
                           SELECT player_id, position,
                                  ROW_NUMBER() OVER (PARTITION BY player_id
                                                     ORDER BY COUNT(*) DESC) AS r
                             FROM player_match_stats WHERE position IS NOT NULL
                            GROUP BY player_id, position) x WHERE r = 1""")
        posicoes = dict(cur.fetchall())
    except Exception:
        cur.connection.rollback()
    clima = {}
    try:
        cur.execute("SELECT fixture_id, chuva_mm, vento_kmh, altitude_m FROM clima_partida")
        clima = {r[0]: r[1:] for r in cur.fetchall()}
    except Exception:
        cur.connection.rollback()
    return jogos, escal, posicoes, clima


# ---------------------------------------------------------------------------
# Linha de estimacao (sem vazamento)
# ---------------------------------------------------------------------------
def _contagem(m: dict, lado: str, est: str):
    col = et.ESTATISTICAS[est][1]
    v = m.get(f"{lado}_{col}")
    return None if v is None else int(v)


def _base_chutes(hist_c: list, hist_f: list, c_id: int, f_id: int, lado: str):
    """Mesma conta de expected_value_convergence (feitos do time no mando
    + cedidos do adversario no mando oposto, /2), pra chutes, que o motor nao
    modela por Poisson."""
    def medias(hist, tid, mando):
        feitos, cedidos = [], []
        for m in hist:
            em_casa = m["home_team_id"] == tid
            if (mando == "home") != em_casa:
                continue
            eu, ele = ("home", "away") if em_casa else ("away", "home")
            if m.get(f"{eu}_total_shots") is not None and m.get(f"{ele}_total_shots") is not None:
                feitos.append(m[f"{eu}_total_shots"])
                cedidos.append(m[f"{ele}_total_shots"])
        return ((sum(feitos) / len(feitos), sum(cedidos) / len(cedidos)) if feitos else (None, None))
    fc, cc = medias(hist_c, c_id, "home")
    ff, cf = medias(hist_f, f_id, "away")
    if lado == "home":
        return None if fc is None or cf is None else (fc + cf) / 2
    return None if ff is None or cc is None else (ff + cc) / 2


def _base(est: str, hist_c, hist_f, c_id, f_id, lado):
    if est == "chutes":
        return _base_chutes(hist_c, hist_f, c_id, f_id, lado)
    from services.pick_engine import stats_model
    r = stats_model.expected_value_convergence(hist_c, hist_f, et.ESTATISTICAS[est][0], lado,
                                               home_team_id=c_id, away_team_id=f_id)
    return r["expected_value"] if r else None


def _ausentes(atual: dict | None, anteriores: list, posicoes: dict) -> tuple:
    """(defesa, ataque) de titulares habituais (3+ inicios nos 5 anteriores)
    que nao estao no XI desta partida. None sem escalacao suficiente."""
    if not atual or len(anteriores) < 3:
        return None, None
    inicios: dict = defaultdict(int)
    for e in anteriores[-5:]:
        for p in e["titulares"]:
            inicios[p] += 1
    fora = [p for p, n in inicios.items() if n >= 3 and p not in atual["titulares"]]
    defesa = sum(1 for p in fora if posicoes.get(p) in ("D", "G"))
    ataque = sum(1 for p in fora if posicoes.get(p) in ("M", "F"))
    return defesa, ataque


def montar_linhas(jogos: list, escal: dict, posicoes: dict, clima: dict) -> list:
    """As linhas de estimacao, em ordem de data. Cada partida usa so' o
    estado acumulado ANTES dela; o estado so' e' atualizado depois."""
    hist: dict = defaultdict(lambda: deque(maxlen=60))
    escal_ant: dict = defaultdict(list)          # team -> escalacoes anteriores
    ref_soma: dict = defaultdict(lambda: defaultdict(float))
    ref_n: dict = defaultdict(lambda: defaultdict(int))
    linhas = []
    for m in jogos:
        c_id, f_id, liga = m["home_team_id"], m["away_team_id"], m["league_id"]
        hc, hf = list(hist[c_id])[::-1][:JANELA], list(hist[f_id])[::-1][:JANELA]
        if len(hc) >= MIN_JOGOS and len(hf) >= MIN_JOGOS:
            ref = {k: ref_soma[liga][k] / ref_n[liga][k] for k in ref_soma[liga]
                   if ref_n[liga][k] >= 30}
            perfis, extras = {}, {}
            for lado, tid, h in (("home", c_id, hc), ("away", f_id, hf)):
                atual = escal.get((m["fixture_id"], tid))
                ant = escal_ant[tid]
                regime = h
                tecnico_novo = None
                if atual and ant:
                    seguidos = 0
                    for e in reversed(ant):
                        if e["coach"] != atual["coach"]:
                            break
                        seguidos += 1
                    tecnico_novo = 1.0 if seguidos < MIN_JOGOS_TECNICO else 0.0
                    if seguidos >= MIN_JOGOS_TECNICO:
                        datas = {e["data"] for e in ant[-seguidos:]}
                        do_regime = [j for j in h if j["match_date"] in datas]
                        if len(do_regime) >= MIN_JOGOS_TECNICO:
                            regime = do_regime
                perfis[lado] = tpm.perfil_tatico(regime, tid, ref)
                forms = [tpm.linha_de_defesa(e["formation"]) for e in ant[-5:] if e["formation"]]
                defesa, ataque = _ausentes(atual, ant, posicoes)
                cl = clima.get(m["fixture_id"])
                extras[lado] = {
                    "linha_de_tres_propria": (sum(1 for f in forms if f == 3) / len(forms)
                                              if forms else None),
                    "ausentes_defesa_propria": defesa, "ausentes_ataque_propria": ataque,
                    "tecnico_novo_proprio": tecnico_novo,
                    "chuva_mm": (min(float(cl[0]), 10.0) if cl and cl[0] is not None else None),
                    "vento_kmh": (float(cl[1]) if cl and cl[1] is not None else None),
                    "altitude_visitante": ((float(cl[2]) / 1000 if lado == "away" else 0.0)
                                           if cl and cl[2] is not None else None),
                }
            for lado, adv in (("home", "away"), ("away", "home")):
                extras[lado]["linha_de_tres_adv"] = extras[adv]["linha_de_tres_propria"]
                extras[lado]["ausentes_defesa_adv"] = extras[adv]["ausentes_defesa_propria"]
            for lado, adv, tid in (("home", "away", c_id), ("away", "home", f_id)):
                cru = et.vetor(perfis[lado], perfis[adv], extras[lado])
                y, base = {}, {}
                for est in et.ESTATISTICAS:
                    v, b = _contagem(m, lado, est), _base(est, hc, hf, c_id, f_id, lado)
                    if v is not None and b and b > 0:
                        y[est], base[est] = v, b
                if y:
                    linhas.append({"fixture_id": m["fixture_id"], "data": m["match_date"],
                                   "league_id": liga, "team_id": tid, "lado": lado,
                                   "y": y, "base": base, "cru": cru})
        # Depois da linha: so' agora a partida entra no estado.
        hist[c_id].append(m)
        hist[f_id].append(m)
        for tid in (c_id, f_id):
            e = escal.get((m["fixture_id"], tid))
            if e:
                escal_ant[tid].append({**e, "data": m["match_date"]})
            for k, v in tpm.metricas_taticas_do_jogo(m, tid).items():
                ref_soma[liga][k] += v
                ref_n[liga][k] += 1
    return linhas


# ---------------------------------------------------------------------------
# Estimacao e validacao
# ---------------------------------------------------------------------------
def _matriz(linhas, est, medias, desvios, so=None):
    X, y, off = [], [], []
    for r in linhas:
        if est not in r["y"]:
            continue
        z = et.padronizar(r["cru"], medias, desvios)
        if so is not None:
            z = [v if f in so else 0.0 for f, v in zip(et.FEATURES, z)]
        X.append([1.0] + z)
        y.append(r["y"][est])
        off.append(math.log(r["base"][est]))
    return X, y, off


def estimar(linhas: list, est: str) -> dict | None:
    """Ajuste completo + selecao |z| >= 2. None sem dado."""
    medias, desvios = et.medias_e_desvios([r["cru"] for r in linhas if est in r["y"]])
    X, y, off = _matriz(linhas, est, medias, desvios)
    if len(y) < 200:
        return None
    fit = et.ajustar_poisson(X, y, off)
    base = et.ajustar_poisson([[1.0] for _ in y], y, off)
    coefs = {}
    for f, b, e in zip(et.FEATURES, fit["beta"][1:], fit["ep"][1:]):
        if e > 0 and abs(b / e) >= Z_MINIMO and f in desvios:
            coefs[f] = {"beta": round(b, 5), "ep": round(e, 5), "z": round(b / e, 2)}
    return {"medias": medias, "desvios": desvios, "coefs": coefs,
            "b0": fit["beta"][0], "b0_base": base["beta"][0],
            "dispersao": fit["dispersao"], "n": fit["n"]}


def _prob_over(lam: float, linha: float, fam: str) -> float:
    from services.pick_engine import probability_model as pm
    return pm.prob_over(linha, lam, pm.dispersao(fam, "total"))


def _m_ep(v: list) -> tuple:
    n = len(v)
    if n < 2:
        return (sum(v) / n if n else 0.0), None
    m = sum(v) / n
    return m, math.sqrt(sum((a - m) ** 2 for a in v) / (n - 1)) / math.sqrt(n)


def avaliar(linhas_val: list, est: str, modelo: dict) -> dict:
    """Modelo tatico x modelo-base, NAS MESMAS partidas da validacao."""
    from services.pick_engine.competition_profile import uses_all_competitions_history
    coefs = modelo["coefs"]
    d_ll, por_jogo = [], defaultdict(dict)
    for r in linhas_val:
        if est not in r["y"]:
            continue
        z = et.padronizar(r["cru"], modelo["medias"], modelo["desvios"])
        s = sum(coefs[f]["beta"] * x for f, x in zip(et.FEATURES, z) if f in coefs)
        mu_t = r["base"][est] * math.exp(modelo["b0"] + s)
        mu_b = r["base"][est] * math.exp(modelo["b0_base"])
        d_ll.append(et.loglik_poisson(r["y"][est], mu_t) - et.loglik_poisson(r["y"][est], mu_b))
        por_jogo[r["fixture_id"]][r["lado"]] = (r["y"][est], mu_t, mu_b, r["league_id"])
    fam, linha = et.ESTATISTICAS[est][0], LINHAS_PADRAO[est]
    pares = []
    for fid, lados in por_jogo.items():
        if len(lados) != 2:
            continue
        yt = sum(v[0] for v in lados.values())
        pt = _prob_over(sum(v[1] for v in lados.values()), linha, fam)
        pb = _prob_over(sum(v[2] for v in lados.values()), linha, fam)
        pares.append((1 if yt > linha else 0, pt, pb, lados["home"][3]))

    def metricas(ps):
        if not ps:
            return None
        ll = lambda o, p: -(o * math.log(max(p, 1e-6)) + (1 - o) * math.log(max(1 - p, 1e-6)))
        d_brier = [(p_t - o) ** 2 - (p_b - o) ** 2 for o, p_t, p_b, _ in ps]
        d_logl = [ll(o, p_t) - ll(o, p_b) for o, p_t, p_b, _ in ps]
        mb, eb = _m_ep(d_brier)
        ml, el = _m_ep(d_logl)
        return {"n": len(ps), "brier_base": sum((p_b - o) ** 2 for o, _, p_b, _ in ps) / len(ps),
                "d_brier": mb, "ep_brier": eb, "d_logloss": ml, "ep_logloss": el,
                "ece_base": _ece([(p_b, o) for o, _, p_b, _ in ps]),
                "ece_tatico": _ece([(p_t, o) for o, p_t, _, _ in ps])}

    m_ll, e_ll = _m_ep(d_ll)
    por_liga = defaultdict(list)
    por_tipo = defaultdict(list)
    for p in pares:
        por_liga[p[3]].append(p)
        por_tipo["copa" if uses_all_competitions_history(p[3]) else "liga"].append(p)
    return {"n_linhas": len(d_ll), "d_loglik": m_ll, "ep_loglik": e_ll,
            "linha": linha, "mercado": metricas(pares),
            "por_tipo": {k: metricas(v) for k, v in por_tipo.items()},
            "por_competicao": {str(k): metricas(v) for k, v in por_liga.items()
                               if len(v) >= MIN_COMPETICAO}}


def _ece(pares: list, faixas: int = 10) -> float | None:
    if not pares:
        return None
    caixas = defaultdict(list)
    for p, o in pares:
        caixas[min(int(p * faixas), faixas - 1)].append((p, o))
    return sum(abs(sum(p for p, _ in c) / len(c) - sum(o for _, o in c) / len(c)) * len(c)
               for c in caixas.values()) / len(pares)


def estaveis(desc: dict, conf: dict | None) -> list:
    """Coeficientes da descoberta cujo sinal se repete na confirmacao com
    |z| >= 1. So' REPROVA -- nao escolhe pela metrica."""
    if not conf:
        return []
    saida = []
    for f, c in desc["coefs"].items():
        outro = conf.get("todos", {}).get(f)
        if outro and outro["beta"] * c["beta"] > 0 and abs(outro["z"]) >= 1:
            saida.append(f)
    return saida


def estimar_todos(linhas: list, est: str) -> dict | None:
    """Ajuste guardando TODOS os coeficientes (pra checar estabilidade)."""
    medias, desvios = et.medias_e_desvios([r["cru"] for r in linhas if est in r["y"]])
    X, y, off = _matriz(linhas, est, medias, desvios)
    if len(y) < 200:
        return None
    fit = et.ajustar_poisson(X, y, off)
    return {"todos": {f: {"beta": b, "z": (b / e if e else 0)}
                      for f, b, e in zip(et.FEATURES, fit["beta"][1:], fit["ep"][1:])}}


def veredito(av: dict, n_estaveis: int) -> tuple:
    merc = av.get("mercado") or {}
    if not av.get("ep_loglik") or merc.get("ep_logloss") is None:
        return False, "amostra insuficiente"
    ganho = av["d_loglik"] > 2 * av["ep_loglik"]
    linha_melhor = merc["d_logloss"] < 0
    if ganho and linha_melhor and n_estaveis:
        return True, (f"APROVADO: +{av['d_loglik']:.4f} de log-verossimilhanca por jogo "
                      f"({av['d_loglik'] / av['ep_loglik']:.1f} EP), log-loss da linha "
                      f"{merc['d_logloss']:+.4f}, {n_estaveis} coeficiente(s) estavel(is)")
    motivo = []
    if not ganho:
        motivo.append(f"ganho de verossimilhanca {av['d_loglik']:+.4f} nao passa de 2 EP")
    if not linha_melhor:
        motivo.append(f"log-loss da linha {merc['d_logloss']:+.4f} nao melhora")
    if not n_estaveis:
        motivo.append("nenhum coeficiente estavel entre as metades")
    return False, "nao aprovado: " + "; ".join(motivo)


def _cortar(linhas, est):
    com = [r for r in linhas if est in r["y"]]
    return com[-MAX_LINHAS:]


def rodar(linhas: list) -> dict:
    resultado = {}
    datas = sorted({r["data"] for r in linhas})
    if not datas:
        return resultado
    corte = datas[len(datas) // 2]
    for est in et.ESTATISTICAS:
        todas = _cortar(linhas, est)
        desc_l = [r for r in todas if r["data"] < corte]
        conf_l = [r for r in todas if r["data"] >= corte]
        desc = estimar(desc_l, est)
        if not desc:
            resultado[est] = {"aprovado": False, "motivo": "amostra insuficiente"}
            continue
        conf = estimar_todos(conf_l, est)
        est_ok = estaveis(desc, conf)
        av = avaliar(conf_l, est, desc)
        aprovado, motivo = veredito(av, len(est_ok))
        completo = estimar(todas, est)
        coefs_aplicaveis = ({f: c for f, c in completo["coefs"].items() if f in est_ok}
                            if completo else {})
        resultado[est] = {
            "aprovado": aprovado and bool(coefs_aplicaveis), "motivo": motivo,
            "descoberta": {"n": desc["n"], "coefs": desc["coefs"]},
            "estaveis": est_ok, "validacao": av,
            # Em shadow o motor registra com TODOS os significativos do ajuste
            # completo; em `on` so' aplica estes se o mercado foi aprovado.
            "producao": completo, "coefs_aprovados": coefs_aplicaveis,
        }
    return resultado


# ---------------------------------------------------------------------------
# Picks: o tatico_sombra gravado no log x resultado
# ---------------------------------------------------------------------------
def picks(cur) -> dict | None:
    try:
        cur.execute("""SELECT fixture_id, candidates FROM engine_decisions
                        WHERE fixture_id IS NOT NULL AND created_at >= '2026-10-08'""")
        sombra = {}
        for fid, cands in cur.fetchall():
            if isinstance(cands, str):
                cands = json.loads(cands)
            for c in cands or []:
                t = c.get("tatico_sombra")
                if t and t.get("prob") is not None and t.get("prob_modelo") is not None:
                    sombra[(fid, c.get("market_type"), c.get("line"))] = t
        cur.execute("""SELECT fixture_id, market_type, line, result, profit FROM picks_ledger
                        WHERE result IN ('GREEN','RED') AND match_date >= '2026-10-08'""")
        pares = [(sombra[(f, mt, ln)], 1 if r == "GREEN" else 0, p)
                 for f, mt, ln, r, p in cur.fetchall() if (f, mt, ln) in sombra]
    except Exception:
        cur.connection.rollback()
        return None
    if not pares:
        return {"n": 0}
    d = [(t["prob"] - o) ** 2 - (t["prob_modelo"] - o) ** 2 for t, o, _ in pares]
    m, e = _m_ep(d)
    lucro = [float(p) for _, _, p in pares if p is not None]
    return {"n": len(pares), "d_brier": m, "ep": e,
            "roi_por_unidade": (sum(lucro) / len(lucro)) if lucro else None}


# ---------------------------------------------------------------------------
def _fmt(v, d=4):
    return "-" if v is None else f"{v:+.{d}f}"


def imprimir(res: dict, pk: dict | None) -> list:
    aprovados = []
    for est, r in res.items():
        print(f"\n== {est}")
        if "validacao" not in r:
            print(f"   {r['motivo']}")
            continue
        av = r["validacao"]
        merc = av.get("mercado") or {}
        print(f"   descoberta: {r['descoberta']['n']} linhas; coeficientes |z|>=2: "
              + (", ".join(f"{f} {c['beta']:+.3f} (z {c['z']:+.1f})"
                           for f, c in r["descoberta"]["coefs"].items()) or "nenhum"))
        print(f"   estaveis na metade nova: {', '.join(r['estaveis']) or 'nenhum'}")
        print(f"   validacao ({av['n_linhas']} linhas): d log-verossimilhanca/jogo "
              f"{_fmt(av['d_loglik'])} ± {av['ep_loglik'] or 0:.4f}")
        if merc:
            print(f"   linha {av['linha']} (n={merc['n']}): Brier base {merc['brier_base']:.4f} "
                  f"d {_fmt(merc['d_brier'])} ± {merc['ep_brier'] or 0:.4f} | log-loss d "
                  f"{_fmt(merc['d_logloss'])} ± {merc['ep_logloss'] or 0:.4f} | ECE base "
                  f"{merc['ece_base']:.3f} tatico {merc['ece_tatico']:.3f}")
        for nome, grupo in (("tipo", av.get("por_tipo") or {}),
                            ("competicao", av.get("por_competicao") or {})):
            for k, g in grupo.items():
                if g:
                    print(f"     {nome} {k:>6}: n={g['n']:5d} d log-loss {_fmt(g['d_logloss'])} "
                          f"± {g['ep_logloss'] or 0:.4f}")
        print(f"   {r['motivo']}")
        if r["aprovado"]:
            aprovados.append(est)
    print("\nPICKS (tatico_sombra x resultado):",
          "sem dado" if not pk or not pk.get("n") else
          f"n={pk['n']} d Brier {_fmt(pk['d_brier'])} ± {pk['ep'] or 0:.4f}, ROI/u {pk['roi_por_unidade']}")
    return aprovados


def gravar(cur, res: dict) -> None:
    cur.execute(et.DDL)
    for est, r in res.items():
        prod = r.get("producao")
        if not prod:
            continue
        cur.execute("""
            INSERT INTO efeitos_taticos (estatistica, coefs, medias, desvios, aprovado,
                                         validacao, ajustado_em)
            VALUES (%s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s::jsonb, NOW())
            ON CONFLICT (estatistica) DO UPDATE SET coefs = EXCLUDED.coefs,
                medias = EXCLUDED.medias, desvios = EXCLUDED.desvios,
                aprovado = EXCLUDED.aprovado, validacao = EXCLUDED.validacao,
                ajustado_em = NOW()
        """, (est, json.dumps(r["coefs_aprovados"] if r["aprovado"] else prod["coefs"]),
              json.dumps(prod["medias"]), json.dumps(prod["desvios"]), r["aprovado"],
              json.dumps({"motivo": r["motivo"], "validacao": r["validacao"],
                          "estaveis": r["estaveis"]}, default=str)))
    cur.connection.commit()


def main():
    from utils.db_utils import get_connection
    gravar_tabela = "--gravar" in sys.argv
    conn = get_connection()
    if not gravar_tabela:
        try:
            conn.set_session(readonly=True)
        except Exception:
            pass
    cur = conn.cursor()
    jogos, escal, posicoes, clima = carregar(cur)
    print(f"{len(jogos)} partidas · {len(escal)} escalacoes · {len(posicoes)} posicoes · "
          f"{len(clima)} climas")
    linhas = montar_linhas(jogos, escal, posicoes, clima)
    print(f"{len(linhas)} linhas de estimacao (time x partida, so' com passado)")
    res = rodar(linhas)
    aprovados = imprimir(res, picks(cur))
    if gravar_tabela:
        gravar(cur, res)
        print("\nefeitos_taticos gravada.")
    cur.close()
    conn.close()
    print("\n=== Leitura ===")
    print(("Mercados com efeito tatico APROVADO fora da amostra: " + ", ".join(aprovados)
           + ". Pode ligar MOTOR_TATICO=on (so' eles entram na conta).") if aprovados else
          "Nenhum mercado com ganho tatico comprovado fora da amostra. Manter MOTOR_TATICO=shadow.")


if __name__ == "__main__":
    main()
