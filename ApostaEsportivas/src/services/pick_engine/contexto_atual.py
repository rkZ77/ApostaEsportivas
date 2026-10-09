"""Contexto ATUAL da partida dentro do motor pre-jogo (2026-10-08).

O PROBLEMA
----------
O motor estima cada linha pela frequencia com que o historico dos dois times
passou dela. Essa conta supoe que o time de hoje e' o time do historico. Tres
coisas quebram a suposicao, e ate' aqui nenhuma mexia na probabilidade:

  tecnico novo       o historico descreve o time do tecnico anterior. Existia
                     so' como booleano no news_score (sombra) e como
                     `teams.structural_change_date`, que e' marcado a mao.
  historico que      a forma recente do time saiu da media da temporada
  mudou              (esquema, elenco, fase), e a media continua pesando igual.
  desfalques         quem esta' fora produzia parte dos gols, chutes, cartoes
                     do historico -- e cada mercado depende de uma parte
                     diferente. O news_score tratava todos igual.

O PRINCIPIO (por que nao e' bonus nem penalidade)
-------------------------------------------------
Contexto aqui NAO empurra a probabilidade pra cima nem pra baixo por decreto.
Ele diz QUANTO do historico ainda descreve o time de hoje -- a AMOSTRA EFETIVA
-- e o encolhimento que o motor ja' faz (bayesian_model.shrink_taxa, prior =
preco no-vig do mercado) faz o resto: com menos evidencia propria, a taxa vai
pro preco do mercado, que ja' embute a noticia (casa de aposta precifica
tecnico novo e desfalque). E' o "power prior" da literatura: o dado antigo
entra com peso a0 em [0, 1].

O a0 sai dos dados, nunca de tabela escrita a mao:

  divergencia   trecho atual (desde o tecnico novo, ou os ultimos N jogos) x
                trecho antigo, NA PROPRIA LINHA. z = diferenca de proporcoes;
                a0 = 1 / (1 + max(0, z^2 - 1)), que e' o estimador de momentos
                da heterogeneidade entre os dois trechos (tau^2 = max(0, d^2 -
                ep^2); peso de agregar = ep^2 / (ep^2 + tau^2)). |z| <= 1:
                nada muda. |z| = 2: o antigo vale 1/4. |z| = 3: 1/9.
  desfalques    fracao da producao do time no historico (gols, chutes, chutes
                no alvo, cartoes, faltas -- o que o mercado conta) que vem de
                quem esta' fora, nunca menor que a fracao de MINUTOS deles.
                a0 = 1 - fracao. Mercado de escanteio de um time sem o
                artilheiro perde so' os minutos dele; o de gols perde os gols.

Como o mesmo teste roda linha por linha, o mesmo tecnico novo pode mudar o
mercado de gols e deixar o de escanteios intacto -- e' o dado que decide.

O QUE NAO VIRA CONTA (e por que)
--------------------------------
Calendario (descanso, pausa, sequencia apertada, jogo perto), viagem e duvida
de escalacao sao gravados como FATORES DE INCERTEZA, vao pro dossie da IA e
pra medicao, mas nao mexem na amostra efetiva. Nao ha' hoje medida que diga
quanto eles valem, e o motor ja' tem dois termos que cobrem parte disso
(context_model.context_score le' a diferenca de descanso; temporal_decay_weight
desconta jogo velho). Ver REDUNDANCIAS abaixo.

REDUNDANCIAS (o mesmo fato nao pune duas vezes)
-----------------------------------------------
  tecnico novo   x news_score (tecnico_mudou)   com MOTOR_CONTEXTO=on o
                                               orchestrator tira news_score
                                               da nota.
  desfalques     x news_score (titulares)       idem.
  forma recente  x temporal_decay_weight        a forma so' mexe na AMOSTRA
                                               EFETIVA, nunca na taxa: a taxa
                                               ja' pesa mais o jogo recente.
  forma recente  x tecnico novo                 time com tecnico novo usa o
                                               corte do tecnico, nunca os dois.
  pausa longa    x temporal_decay_weight        so' fator de incerteza.

MODOS (`MOTOR_CONTEXTO`)
------------------------
  off     nada e' calculado.
  shadow  (padrao) tudo e' calculado e gravado no candidato e no log de
          decisao (`contexto_sombra`), sem mudar pick nenhum. E' a regra do
          projeto: sinal novo entra na conta depois de medido
          (scripts/medir_contexto_atual.py).
  on      a amostra efetiva e a taxa do trecho atual entram na conta; a
          amostra efetiva passa pelo mesmo piso de `min_amostra`; partida com
          historico desatualizado e' barrada.

`MOTOR_CONTEXTO_FATORES` (lista separada por virgula, padrao todos:
tecnico,forma,desfalques,dados) desliga um fator sem desligar os outros --
e' como um ajuste que nao mostrar ganho na medicao sai sem reverter codigo.

SEM VAZAMENTO DE FUTURO
-----------------------
Todo dado tem `instante` (a hora da previsao). Escalacao e calendario so'
entram com data < apito; o cache do tecnico so' vale quando foi consultado
antes do instante da previsao (`conhecido_em`). Desfalque vem de /injuries no
momento da previsao e fica carimbado com o instante -- num replay, desfalque
consultado depois do instante e' ignorado.
"""
from __future__ import annotations

import math
import os
from collections import Counter
from datetime import date, datetime, timedelta

FATORES = ("tecnico", "forma", "desfalques", "dados")

#: Qual "producao" cada familia conta. Sem coluna por jogador (escanteio,
#: impedimento, defesa) o que sobra e' a fracao de minutos.
_PRODUCAO_DA_FAMILIA = {
    "goals": "gols", "goals_1h": "gols", "btts": "gols", "btts_1h": "gols",
    "clean_sheet": "gols", "win_to_nil": "gols",
    "shots": "chutes", "shots_on_target": "chutes_no_alvo",
    "cards": "cartoes", "cards_1h": "cartoes",
    "fouls": "faltas",
}


# ---------------------------------------------------------------------------
# Interruptores
# ---------------------------------------------------------------------------
def modo() -> str:
    m = os.getenv("MOTOR_CONTEXTO", "shadow").strip().lower()
    return m if m in ("off", "shadow", "on") else "shadow"


def fatores_ligados() -> set:
    bruto = os.getenv("MOTOR_CONTEXTO_FATORES", "")
    if not bruto.strip():
        return set(FATORES)
    return {f.strip().lower() for f in bruto.split(",") if f.strip().lower() in FATORES}


# ---------------------------------------------------------------------------
# Utilitarios
# ---------------------------------------------------------------------------
def _dia(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _clamp(p: float) -> float:
    return min(1.0, max(0.0, p))


def peso_do_historico_antigo(p_atual: float, n_atual: float,
                             p_antigo: float, n_antigo: float) -> tuple:
    """(a0, z) entre o trecho atual e o antigo, sobre uma proporcao.

    a0 = 1/(1 + max(0, z^2 - 1)): estimador de momentos da heterogeneidade
    entre os dois trechos (ver docstring do modulo). Sem variancia (os dois
    trechos 0% ou os dois 100%) os trechos concordam: a0 = 1.
    """
    if n_atual <= 0 or n_antigo <= 0:
        return 1.0, None
    p_bar = (n_atual * p_atual + n_antigo * p_antigo) / (n_atual + n_antigo)
    var = p_bar * (1 - p_bar) * (1 / n_atual + 1 / n_antigo)
    if var <= 0:
        return 1.0, 0.0
    z = (p_atual - p_antigo) / math.sqrt(var)
    return round(1.0 / (1.0 + max(0.0, z * z - 1.0)), 4), round(z, 3)


# ---------------------------------------------------------------------------
# 1. Memoria temporal: o regime do tecnico
# ---------------------------------------------------------------------------
def regime_do_tecnico(escalacoes: list, tecnico_api: dict | None = None) -> dict | None:
    """Quem comanda o time hoje e desde quando, a partir das escalacoes.

    `escalacoes`: [(match_date, coach_id, coach_name, formation)] do mais
    recente pro mais antigo (team_lineups, so' jogos antes do apito).
    `tecnico_api`: {"coach_id", "coach_name", "inicio"} da /coachs, quando ha'
    -- e' o unico jeito de saber de um tecnico que AINDA NAO ESTREOU.

    `inicio` e' o primeiro dia que pertence ao regime atual. Pelas escalacoes,
    e' o dia seguinte ao ULTIMO jogo do tecnico anterior (e nao o primeiro
    jogo observado do atual): escalacao que faltou coletar nao empurra o corte
    pra frente.
    """
    def chave(cid, nome):
        return cid if cid is not None else (nome or "").strip().lower() or None

    validas = [e for e in (escalacoes or []) if chave(e[1], e[2])]
    saida: dict = {}
    if validas:
        atual = chave(validas[0][1], validas[0][2])
        seguidos = 0
        for e in validas:
            if chave(e[1], e[2]) != atual:
                break
            seguidos += 1
        saida = {"tecnico": validas[0][2], "tecnico_id": validas[0][1],
                 "jogos_sob_tecnico": seguidos, "jogos_lidos": len(validas),
                 "fonte": "escalacoes"}
        if seguidos < len(validas):
            ultimo_do_anterior = _dia(validas[seguidos][0])
            saida["anterior"] = validas[seguidos][2]
            if ultimo_do_anterior:
                saida["inicio"] = ultimo_do_anterior + timedelta(days=1)
        forms = [e[3] for e in validas[:seguidos] if e[3]]
        if forms:
            mais, vezes = Counter(forms).most_common(1)[0]
            saida["formacao"] = {"mais_usada": mais, "fracao": round(vezes / len(forms), 2),
                                 "distintas": len(set(forms))}
        antes = [e[3] for e in validas[seguidos:] if e[3]]
        if antes and forms:
            saida["formacao_anterior"] = Counter(antes).most_common(1)[0][0]

    if tecnico_api and tecnico_api.get("coach_id") is not None:
        mesmo = (saida.get("tecnico_id") == tecnico_api["coach_id"]
                 or (saida.get("tecnico") or "").strip().lower()
                 == (tecnico_api.get("coach_name") or "").strip().lower())
        inicio_api = _dia(tecnico_api.get("inicio"))
        if saida and not mesmo:
            # Tecnico que a API ja' conhece e que ainda nao aparece em
            # escalacao nenhuma: estreia hoje (ou a coleta de escalacao esta'
            # atrasada). O corte e' o inicio dele; sem inicio, a escalacao
            # mais recente e' o ultimo jogo do anterior.
            ultimo = _dia(validas[0][0]) if validas else None
            saida = {**saida, "anterior": saida.get("tecnico"),
                     "tecnico": tecnico_api.get("coach_name"),
                     "tecnico_id": tecnico_api["coach_id"],
                     "jogos_sob_tecnico": 0, "fonte": "api",
                     "inicio": inicio_api or (ultimo + timedelta(days=1) if ultimo else None)}
            saida.pop("formacao", None)
        elif saida and mesmo and inicio_api:
            # Mesmo tecnico: a data de contratacao e' mais exata que o corte
            # pelas escalacoes, mas nunca o empurra pra tras de um jogo do
            # anterior que as escalacoes viram.
            if not saida.get("inicio") or inicio_api > saida["inicio"]:
                saida["inicio"] = inicio_api
            saida["fonte"] = "escalacoes+api"
        elif not saida:
            saida = {"tecnico": tecnico_api.get("coach_name"),
                     "tecnico_id": tecnico_api["coach_id"],
                     "inicio": inicio_api, "fonte": "api"}
    return saida or None


# ---------------------------------------------------------------------------
# 2. Desfalques: quanto da producao do historico esta' fora
# ---------------------------------------------------------------------------
def producao_perdida(linhas: list, ids_fora: set) -> dict | None:
    """`linhas`: [(fixture_id, player_id, minutos, gols, chutes, chutes_no_alvo,
    cartoes, faltas)] do time nos ultimos jogos antes do apito.

    Devolve {producao: {"perdido": x, "total": y}} + "jogos". A fracao fica
    pra quem combina (um mercado total soma os dois times antes de dividir).
    """
    if not linhas:
        return None
    nomes = ("minutos", "gols", "chutes", "chutes_no_alvo", "cartoes", "faltas")
    total = dict.fromkeys(nomes, 0.0)
    perdido = dict.fromkeys(nomes, 0.0)
    jogos = set()
    for fixture_id, player_id, *valores in linhas:
        jogos.add(fixture_id)
        for nome, v in zip(nomes, valores):
            if v is None:
                continue
            total[nome] += float(v)
            if player_id in ids_fora:
                perdido[nome] += float(v)
    saida = {n: {"perdido": round(perdido[n], 1), "total": round(total[n], 1)}
             for n in nomes if total[n] > 0}
    if not saida:
        return None
    saida["jogos"] = len(jogos)
    return saida


def fracao_perdida(producoes: list, familia: str) -> dict | None:
    """Fracao da producao que a familia conta, somada nos times que o
    mercado le, nunca menor que a fracao de minutos (o jogador fora tambem
    defende, marca, cobra escanteio -- o que a coluna dele nao registra)."""
    producoes = [p for p in producoes if p]
    if not producoes:
        return None

    def fracao(nome):
        tot = sum((p.get(nome) or {}).get("total", 0) for p in producoes)
        if tot <= 0:
            return None
        return sum((p.get(nome) or {}).get("perdido", 0) for p in producoes) / tot

    minutos = fracao("minutos")
    base = _PRODUCAO_DA_FAMILIA.get(familia.replace("handicap_", ""))
    especifica = fracao(base) if base else None
    candidatos = [f for f in (minutos, especifica) if f is not None]
    if not candidatos:
        return None
    f = max(candidatos)
    usada = base if (especifica is not None and especifica >= (minutos or 0)) else "minutos"
    return {"fracao": round(min(f, 1.0), 4), "producao": usada,
            "fracao_minutos": round(minutos, 4) if minutos is not None else None}


# ---------------------------------------------------------------------------
# 3. Calendario e viagem: fatores de incerteza (nao viram conta)
# ---------------------------------------------------------------------------
def fatores_de_calendario(carga: dict | None) -> list:
    """Rotulos de MEDICAO, nao de ajuste. Os cortes so' separam faixas pra
    medir_contexto_atual dizer, um dia, se alguma delas erra mais."""
    if not carga:
        return []
    f = []
    desde = carga.get("dias_desde_o_ultimo")
    ate = carga.get("dias_ate_o_proximo")
    if desde is not None and desde >= 14:
        f.append("pausa_longa")
    if desde is not None and desde < 3:
        f.append("descanso_curto")
    if (carga.get("jogos_ultimos_14_dias") or 0) >= 4:
        f.append("sequencia_apertada")
    if ate is not None and ate <= 3:
        f.append("proximo_jogo_perto")
    return f


def distancia_km(a: tuple | None, b: tuple | None) -> float | None:
    """Haversine entre (lat, lon)."""
    if not a or not b or None in (a[0], a[1], b[0], b[1]):
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return round(6371 * 2 * math.asin(math.sqrt(h)))


# ---------------------------------------------------------------------------
# 4. Validade dos dados: o historico esta' atrasado?
# ---------------------------------------------------------------------------
def jogos_faltando(historico: list, concluidos: list) -> list:
    """Partidas que o time JA JOGOU (calendario) e que nao estao no historico
    que o motor vai ler. So' conta competicao que o historico ja' le e so'
    depois do ultimo jogo dele -- jogo de copa fora do historico de liga e'
    escolha, nao atraso."""
    datas = [d for d in (_dia(m.get("match_date")) for m in historico or []) if d]
    if not datas:
        return []
    ultimo = max(datas)
    ligas = {m.get("league_id") for m in historico if m.get("league_id") is not None}
    saida = []
    for quando, liga in concluidos or []:
        d = _dia(quando)
        if d and d > ultimo and (not ligas or liga in ligas):
            saida.append(str(d))
    return saida


def avaliar_partida(contexto: dict | None, last10_home: list, last10_away: list,
                    config) -> dict | None:
    """Fatores da partida inteira: dados atrasados, calendario, viagem.
    `bloqueio` so' e' preenchido quando o fator `dados` esta' ligado."""
    if not contexto:
        return None
    ligados = fatores_ligados()
    saida: dict = {"fatores_de_incerteza": [], "falhas": list(contexto.get("falhas") or [])}
    faltando = {}
    for lado, hist in (("home", last10_home), ("away", last10_away)):
        t = contexto.get(lado) or {}
        falt = jogos_faltando(hist, t.get("concluidos_recentes"))
        if falt:
            faltando[lado] = falt
        for f in fatores_de_calendario(t.get("calendario")):
            saida["fatores_de_incerteza"].append(f"{lado}:{f}")
        if t.get("duvidas"):
            saida["fatores_de_incerteza"].append(f"{lado}:duvida_de_escalacao")
        regime = t.get("regime") or {}
        if regime.get("fonte") == "api" and regime.get("jogos_sob_tecnico") == 0:
            saida["fatores_de_incerteza"].append(f"{lado}:tecnico_estreia")
    # Quem ja' estava fora NO INSTANTE DA PREVISAO. A reavaliacao perto do apito
    # (reavaliacao.py) compara com isto pra saber o que e' noticia NOVA -- e o
    # que ja' estava na conta nao pode ser contado de novo.
    saida["desfalques_ids"] = {lado: (contexto.get(lado) or {}).get("desfalques_ids") or []
                               for lado in ("home", "away")}
    saida["instante"] = contexto.get("instante")
    viagem = (contexto.get("away") or {}).get("viagem_km")
    if viagem is not None:
        saida["viagem_km_visitante"] = viagem
        if viagem >= 1500:
            saida["fatores_de_incerteza"].append("away:viagem_longa")
    if faltando:
        saida["jogos_faltando_no_historico"] = faltando
        pior = max(len(v) for v in faltando.values())
        if "dados" in ligados and pior >= config.contexto_max_jogos_faltando:
            saida["bloqueio"] = (f"historico desatualizado: {pior} jogo(s) ja' disputado(s) "
                                 f"fora da folha ({faltando})")
    return saida


# ---------------------------------------------------------------------------
# 5. Por mercado: o trecho atual e a amostra efetiva
# ---------------------------------------------------------------------------
def _ordenados(hist: list) -> list:
    return sorted(hist or [], key=lambda m: _dia(m.get("match_date")) or date.min, reverse=True)


def _lados_do_escopo(scope: str | None) -> tuple:
    if scope == "home":
        return ("home",)
    if scope == "away":
        return ("away",)
    return ("home", "away")


def preparar_familia(contexto: dict | None, family: str, scope: str | None,
                     last10_home: list, last10_away: list, config) -> dict | None:
    """O que vale pra todas as linhas de uma familia/escopo: o recorte do
    trecho atual de cada time e a fracao perdida por desfalque."""
    if not contexto:
        return None
    ligados = fatores_ligados()
    cortes = {}
    atuais = {"home": last10_home, "away": last10_away}
    for lado, hist in (("home", last10_home), ("away", last10_away)):
        t = contexto.get(lado) or {}
        regime = t.get("regime") or {}
        inicio = regime.get("inicio")
        ordenados = _ordenados(hist)
        if "tecnico" in ligados and inicio:
            inicio = _dia(inicio)
            atual = [m for m in ordenados if (_dia(m.get("match_date")) or date.min) >= inicio]
            if len(atual) < len(ordenados):
                atuais[lado] = atual
                cortes[lado] = {"tipo": "tecnico", "desde": str(inicio),
                                "jogos_atuais": len(atual), "jogos_lidos": len(ordenados)}
                continue
        janela = config.contexto_janela_recente
        if "forma" in ligados and janela and len(ordenados) > janela:
            atuais[lado] = ordenados[:janela]
            cortes[lado] = {"tipo": "forma", "ultimos": janela,
                            "jogos_lidos": len(ordenados)}

    desf = None
    if "desfalques" in ligados:
        producoes = [(contexto.get(l) or {}).get("producao") for l in _lados_do_escopo(scope)]
        desf = fracao_perdida(producoes, family)
        if desf and desf["fracao"] <= 0:
            desf = None
    if not cortes and not desf:
        return None
    return {"cortes": cortes, "home": atuais["home"], "away": atuais["away"],
            "home_full": last10_home, "away_full": last10_away,
            "desfalques": desf}


def avaliar_linha(prep: dict | None, taxa_full: dict, family: str, scope: str | None,
                  value: str, line: str, reference_date, config,
                  team_id=None, home_team_id=None, away_team_id=None) -> dict | None:
    """A taxa que o motor deve encolher e a amostra efetiva com que encolhe.

    Devolve {"taxa_base", "amostra_efetiva", "amostra", "fatores"} ou None
    quando nada muda. `taxa_base` so' difere da taxa do historico inteiro
    quando ha' corte por TECNICO (a forma recente ja' esta' na taxa via
    temporal_decay_weight -- ver REDUNDANCIAS).
    """
    if not prep or not taxa_full or taxa_full.get("taxa_ponderada") is None:
        return None
    from services.pick_engine import stats_model

    n_full = float(taxa_full.get("amostra") or 0)
    tp_full = float(taxa_full["taxa_ponderada"])
    tb_full = float(taxa_full.get("taxa_bruta") if taxa_full.get("taxa_bruta") is not None
                    else tp_full)
    if n_full <= 0:
        return None
    taxa_base, n_eff = tp_full, n_full
    fatores = []

    lados = _lados_do_escopo(scope)
    cortes = {l: c for l, c in prep["cortes"].items() if l in lados}
    if cortes:
        # So' o time que o mercado le' entra recortado: um "Escanteios Casa"
        # nao muda porque o VISITANTE trocou de tecnico.
        hist_casa = prep["home"] if "home" in cortes else prep["home_full"]
        hist_fora = prep["away"] if "away" in cortes else prep["away_full"]
        cur = stats_model.compute_taxa(family, scope, value, line, hist_casa, hist_fora,
                                       reference_date, config, team_id=team_id,
                                       home_team_id=home_team_id, away_team_id=away_team_id)
        tem_atual = bool(cur) and cur.get("taxa_ponderada") is not None
        n_cur = float(cur["amostra"]) if tem_atual else 0.0
        n_old = n_full - n_cur
        por_tecnico = any(c["tipo"] == "tecnico" for c in cortes.values())
        if n_old > 0:
            fator = {"fator": "tecnico" if por_tecnico else "forma",
                     "cortes": cortes, "jogos_atuais": n_cur, "jogos_antigos": n_old}
            if tem_atual:
                tp_cur = float(cur["taxa_ponderada"])
                tb_cur = float(cur.get("taxa_bruta") if cur.get("taxa_bruta") is not None
                               else tp_cur)
                tb_old = _clamp((n_full * tb_full - n_cur * tb_cur) / n_old)
                tp_old = _clamp((n_full * tp_full - n_cur * tp_cur) / n_old)
                a0, z = peso_do_historico_antigo(tb_cur, n_cur, tb_old, n_old)
                fator.update({"taxa_atual": round(tp_cur, 4), "taxa_antiga": round(tp_old, 4),
                              "z": z, "a0_divergencia": a0})
            else:
                tp_cur, tp_old, a0 = None, tp_full, 1.0
            if por_tecnico:
                # Com poucos jogos do tecnico novo o teste nao tem poder pra
                # achar diferenca nenhuma, e "nao achei" viraria "nao ha'".
                # A rampa diz quanto o historico anterior vale enquanto o
                # tecnico novo ainda nao mostrou o time dele.
                # A rampa conta os jogos DO TIME QUE TROCOU de tecnico, e nao
                # n_cur: num mercado total, n_cur inclui os jogos do outro time
                # (que nao mudou), e um tecnico estreando hoje pareceria ter 20
                # jogos de evidencia. Achado rodando o motor em 08/10.
                jogos_do_novo = min(c.get("jogos_atuais", 0) for c in cortes.values()
                                    if c["tipo"] == "tecnico")
                minimo = max(1, config.contexto_min_jogos_tecnico)
                rampa = (config.contexto_peso_tecnico_sem_jogos
                         + (1 - config.contexto_peso_tecnico_sem_jogos)
                         * min(1.0, jogos_do_novo / minimo))
                a0 = min(a0, rampa)
                fator["a0_rampa"] = round(rampa, 4)
                denom = n_cur + a0 * n_old
                if denom > 0:
                    taxa_base = ((n_cur * tp_cur if tp_cur is not None else 0.0)
                                 + a0 * n_old * tp_old) / denom
            fator["a0"] = round(a0, 4)
            n_eff = n_cur + a0 * n_old
            if a0 < 1.0:
                fatores.append(fator)

    desf = prep.get("desfalques")
    if desf:
        n_eff *= (1.0 - desf["fracao"])
        fatores.append({"fator": "desfalques", **desf})

    if not fatores:
        return None
    return {"taxa_base": round(_clamp(taxa_base), 4), "amostra_efetiva": round(n_eff, 2),
            "amostra": n_full, "fatores": fatores,
            # Fracao do historico que o contexto descontou: 0 = historico
            # inteiro vale, 1 = nada vale. E' a "incerteza contextual" do
            # candidato, separada da probabilidade e do valor.
            "incerteza_contextual": round(1 - n_eff / n_full, 4)}


# ---------------------------------------------------------------------------
# 5b. Motores de modelo proprio (faltas, player stats, boost)
# ---------------------------------------------------------------------------
#: Forca do prior no encolhimento do motor (bayesian_model._DEFAULT_PRIOR_STRENGTH).
_K_PRIOR = 10


def peso_por_media(atuais: list, antigos: list) -> tuple:
    """(a0, z) entre duas listas de contagens (faltas por jogo, chutes do
    jogador...). Mesmo estimador de peso_do_historico_antigo, sobre a media:
    z = diferenca de medias / erro-padrao combinado."""
    a = [float(v) for v in atuais if v is not None]
    b = [float(v) for v in antigos if v is not None]
    if len(a) < 2 or len(b) < 2:
        return 1.0, None
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
    vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
    ep2 = va / len(a) + vb / len(b)
    if ep2 <= 0:
        return 1.0, 0.0
    z = (ma - mb) / math.sqrt(ep2)
    return round(1.0 / (1.0 + max(0.0, z * z - 1.0)), 4), round(z, 3)


def _separar_por_data(serie: list, inicio: date) -> tuple:
    atuais = [v for d, v in serie if (_dia(d) or date.min) >= inicio]
    antigos = [v for d, v in serie if (_dia(d) or date.min) < inicio]
    return atuais, antigos


def ajuste_para_modelo_proprio(contexto: dict | None, family: str, scope: str | None,
                               p: float | None, n: float | None, prior: float | None,
                               series: dict | None, config) -> dict | None:
    """O contexto atual pra quem nao passa por analyze_fixture_markets.

    `series`: {"home": [(data, valor)], "away": [...]} com a contagem que o
    motor usa, jogo a jogo (faltas do time, chutes do jogador). E' sobre ela
    que roda o teste de divergencia; sem serie, so' a rampa do tecnico novo.
    `prior`: probabilidade do mercado (no-vig ou 1/odd).

    A probabilidade de contexto e' a do motor com o afastamento do mercado
    reduzido na mesma proporcao que o encolhimento do motor principal
    reduziria com a amostra efetiva no lugar da amostra:
        w = [n_ef/(n_ef+k)] / [n/(n+k)],   p_ctx = prior + (p - prior) * w
    Nunca afasta do mercado (w <= 1).
    """
    if not contexto or p is None or not n:
        return None
    ligados = fatores_ligados()
    n = float(n)
    n_eff = n
    fatores = []
    for lado in _lados_do_escopo(scope):
        t = contexto.get(lado) or {}
        serie = sorted((series or {}).get(lado) or [],
                       key=lambda dv: _dia(dv[0]) or date.min, reverse=True)
        inicio = _dia((t.get("regime") or {}).get("inicio"))
        if "tecnico" in ligados and inicio and serie:
            atuais, antigos = _separar_por_data(serie, inicio)
            if antigos:
                a0, z = peso_por_media(atuais, antigos)
                minimo = max(1, config.contexto_min_jogos_tecnico)
                rampa = (config.contexto_peso_tecnico_sem_jogos
                         + (1 - config.contexto_peso_tecnico_sem_jogos)
                         * min(1.0, len(atuais) / minimo))
                a0 = min(a0, rampa)
                fracao_antiga = len(antigos) / len(serie)
                if a0 < 1.0:
                    n_eff *= (1 - fracao_antiga) + a0 * fracao_antiga
                    fatores.append({"fator": "tecnico", "lado": lado, "z": z, "a0": a0,
                                    "jogos_atuais": len(atuais), "jogos_antigos": len(antigos)})
                continue
        janela = config.contexto_janela_recente
        if "forma" in ligados and janela and len(serie) > janela:
            atuais = [v for _, v in serie[:janela]]
            antigos = [v for _, v in serie[janela:]]
            a0, z = peso_por_media(atuais, antigos)
            if a0 < 1.0:
                fracao_antiga = len(antigos) / len(serie)
                n_eff *= (1 - fracao_antiga) + a0 * fracao_antiga
                fatores.append({"fator": "forma", "lado": lado, "z": z, "a0": a0})
    if "desfalques" in ligados:
        producoes = [(contexto.get(l) or {}).get("producao") for l in _lados_do_escopo(scope)]
        desf = fracao_perdida(producoes, family)
        if desf and desf["fracao"] > 0:
            n_eff *= 1.0 - desf["fracao"]
            fatores.append({"fator": "desfalques", **desf})
    if not fatores:
        return None
    w = ((n_eff / (n_eff + _K_PRIOR)) / (n / (n + _K_PRIOR))) if n_eff > 0 else 0.0
    p_ctx = p if prior is None else prior + (p - prior) * min(1.0, w)
    return {"taxa": round(_clamp(p_ctx), 4), "taxa_sem_contexto": round(p, 4),
            "amostra_efetiva": round(n_eff, 2), "amostra": n,
            "incerteza_contextual": round(1 - n_eff / n, 4), "fatores": fatores}


def probabilidade_para_modelo_proprio(contexto: dict | None, family: str, scope: str | None,
                                      p: float | None, n: float | None, odd: float | None,
                                      series: dict | None, config,
                                      prior: float | None = None) -> tuple:
    """(probabilidade a usar, registro ou None) -- o ponto unico pelos motores
    de modelo proprio. Em `shadow` devolve `p` intacta e o registro; em `on`,
    a probabilidade de contexto. Nunca sobe a probabilidade (w <= 1 e o pick
    so' existe com p acima do mercado)."""
    m = modo()
    if m == "off" or not contexto or p is None:
        return p, None
    if prior is None and odd and odd > 1:
        prior = 1 / odd
    aj = ajuste_para_modelo_proprio(contexto, family, scope, p, n, prior, series, config)
    if not aj:
        return p, None
    aj["ev"] = round(aj["taxa"] * odd - 1, 4) if odd else None
    aj["edge"] = round(aj["taxa"] - prior, 4) if prior is not None else None
    aj["aplicado"] = m == "on"
    return (aj["taxa"] if m == "on" else p), aj


def bloqueio_da_partida(contexto: dict | None, hist_casa: list, hist_fora: list,
                        config) -> tuple:
    """(avaliacao da partida, motivo de bloqueio so' em `on`)."""
    if modo() == "off" or not contexto:
        return None, None
    av = avaliar_partida(contexto, hist_casa, hist_fora, config)
    motivo = (av or {}).get("bloqueio") if modo() == "on" else None
    return av, motivo


# ---------------------------------------------------------------------------
# 6. Coleta (DB + /coachs com cache) -- chamada pelo dossie, uma vez por jogo
# ---------------------------------------------------------------------------
_DDL_TECNICO = (
    """CREATE TABLE IF NOT EXISTS tecnico_atual_cache (
        team_id       INTEGER PRIMARY KEY,
        coach_id      INTEGER,
        coach_name    TEXT,
        inicio        DATE,
        consultado_em TIMESTAMP NOT NULL DEFAULT NOW()
    )""",
)


def tecnico_da_api(resposta: list, team_id: int) -> dict | None:
    """O tecnico com passagem ABERTA (end nulo) no time, a de inicio mais
    recente. Tecnico antigo com `end` nulo por falha da API perde pro mais
    recente."""
    melhor = None
    for c in resposta or []:
        for p in c.get("career") or []:
            if ((p.get("team") or {}).get("id") == team_id and not p.get("end")
                    and p.get("start")):
                if melhor is None or p["start"] > melhor["inicio"]:
                    melhor = {"coach_id": c.get("id"), "coach_name": c.get("name"),
                              "inicio": p["start"]}
    return melhor


def tecnico_atual(cur, team_id: int, instante: datetime | None = None) -> tuple:
    """(tecnico ou None, falha ou None). Cache de 24h por time em
    `tecnico_atual_cache`: no maximo uma chamada de /coachs por time por dia,
    e so' dos times que jogam. `MOTOR_CONTEXTO_COACHS=off` usa so' o cache.

    `instante` None = previsao ao vivo, no relogio do BANCO (consultado_em e'
    gravado com NOW() de la'; comparar com datetime.now() do processo erraria
    pelo fuso). Com instante (replay), registro consultado depois dele nao e'
    conhecido -- e nada e' consultado na API, que so' sabe o presente."""
    try:
        for sql in _DDL_TECNICO:
            cur.execute(sql)
        cur.execute("""
            SELECT coach_id, coach_name, inicio, consultado_em,
                   (NOW() - consultado_em) < INTERVAL '24 hours' AS fresco
              FROM tecnico_atual_cache
             WHERE team_id = %s AND (%s::timestamp IS NULL OR consultado_em <= %s)
        """, (team_id, instante, instante))
        linha = cur.fetchone()
    except Exception as e:
        cur.connection.rollback()
        return None, f"cache do tecnico: {e}"
    cache = None
    if linha and linha[0] is not None:
        cache = {"coach_id": linha[0], "coach_name": linha[1], "inicio": linha[2],
                 "conhecido_em": str(linha[3])}
    fresco = bool(linha and linha[4])
    if (fresco or instante is not None
            or os.getenv("MOTOR_CONTEXTO_COACHS", "on").strip().lower() == "off"):
        return cache, None
    try:
        # CUSTO (2026-10-08): no maximo uma chamada por time por dia, e so'
        # com folga larga de cota -- o tecnico e' informacao boa de ter, nao
        # pode disputar cota com odd, folha e liquidacao. Sem folga, vale o
        # cache e a escalacao.
        from services import api_quota
        if not api_quota.pode_gastar(1, margem=500):
            return cache, "/coachs adiada: cota do dia sem folga"
        from utils.api_client import buscar
        resposta = buscar("coachs", {"team": team_id}, origem="motor_contexto")
    except Exception as e:
        # Falha da API: o cache velho ainda e' informacao verdadeira de ONTEM,
        # e a escalacao continua dizendo quem dirigiu o ultimo jogo.
        return cache, f"/coachs time {team_id}: {e}"
    achado = tecnico_da_api(resposta, team_id)
    try:
        cur.execute("""
            INSERT INTO tecnico_atual_cache (team_id, coach_id, coach_name, inicio, consultado_em)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (team_id) DO UPDATE SET coach_id = EXCLUDED.coach_id,
                coach_name = EXCLUDED.coach_name, inicio = EXCLUDED.inicio,
                consultado_em = NOW()
        """, (team_id, (achado or {}).get("coach_id"), (achado or {}).get("coach_name"),
              (achado or {}).get("inicio")))
        cur.connection.commit()
    except Exception:
        cur.connection.rollback()
    if achado:
        achado["conhecido_em"] = "agora"
    return achado, None


def _escalacoes_longas(cur, team_id: int, antes_de, instante=None, limite: int = 40) -> list:
    cur.execute("""
        SELECT match_date, coach_id, coach_name, formation
          FROM team_lineups
         WHERE team_id = %s AND match_date < %s
           AND (%s::timestamp IS NULL OR coletado_em <= %s)
         ORDER BY match_date DESC
         LIMIT %s
    """, (team_id, antes_de, instante, instante, limite))
    return cur.fetchall()


def _linhas_de_producao(cur, team_id: int, antes_de, jogos: int = 10) -> list:
    cur.execute("""
        WITH ultimos AS (
            SELECT fixture_id, MAX(match_date) AS dia
              FROM player_match_stats
             WHERE team_id = %s AND match_date < %s
             GROUP BY fixture_id
             ORDER BY dia DESC
             LIMIT %s
        )
        SELECT p.fixture_id, p.player_id, p.minutes, p.goals_total, p.shots_total,
               p.shots_on,
               COALESCE(p.cards_yellow, 0) + 2 * COALESCE(p.cards_red, 0),
               p.fouls_committed
          FROM player_match_stats p
          JOIN ultimos u ON u.fixture_id = p.fixture_id
         WHERE p.team_id = %s
    """, (team_id, antes_de, jogos, team_id))
    return cur.fetchall()


def _concluidos_recentes(cur, team_id: int, quando: datetime, dias: int = 21) -> list:
    cur.execute("""
        SELECT match_datetime, league_id FROM calendario_jogos
         WHERE (home_team_id = %s OR away_team_id = %s)
           AND status IN ('FT', 'AET', 'PEN')
           AND match_datetime BETWEEN %s AND %s
         ORDER BY match_datetime
    """, (team_id, team_id, quando - timedelta(days=dias), quando - timedelta(hours=3)))
    return [(str(r[0]), r[1]) for r in cur.fetchall()]


def _coords(cur, cidade: str | None, pais: str | None):
    """So' cache de geocoding: nenhuma requisicao no caminho do motor."""
    if not cidade:
        return None
    try:
        from collectors.clima_service import PAIS_ISO, _chave
        cur.execute("SELECT latitude, longitude FROM geocode_cidades "
                    "WHERE chave = %s AND encontrada", (_chave(cidade, PAIS_ISO.get(pais or "")),))
        linha = cur.fetchone()
        return tuple(linha) if linha else None
    except Exception:
        cur.connection.rollback()
        return None


def _viagem_do_visitante(cur, fixture_id, fora: int, quando: datetime) -> float | None:
    """Distancia entre a cidade do jogo anterior do visitante e a deste."""
    try:
        cur.execute("SELECT venue_city, pais FROM calendario_jogos WHERE fixture_id = %s",
                    (fixture_id,))
        aqui = cur.fetchone()
        cur.execute("""
            SELECT venue_city, pais FROM calendario_jogos
             WHERE (home_team_id = %s OR away_team_id = %s)
               AND match_datetime < %s AND venue_city IS NOT NULL
             ORDER BY match_datetime DESC LIMIT 1
        """, (fora, fora, quando - timedelta(hours=3)))
        antes = cur.fetchone()
    except Exception:
        cur.connection.rollback()
        return None
    if not aqui or not antes:
        return None
    return distancia_km(_coords(cur, *antes), _coords(cur, *aqui))


def coletar(cur, fixture_id: int, casa: int, fora: int, quando: datetime,
            desfalques: dict, calendario: dict, instante: datetime | None = None) -> dict:
    """Tudo que o motor precisa da partida, numa passada. Cada fonte falha
    sozinha: o que nao veio fica ausente e a falha vai em `falhas`.

    `desfalques`: {"home": {"fora": set(ids), "duvidas": [nomes]}, "away": ...}
    vindo do dossie (/injuries, ja' consultado la').
    `calendario`: {team_id: carga_do_time} do dossie.
    `instante`: None na previsao ao vivo; em replay, o momento da previsao.
    """
    saida: dict = {"instante": str(instante or datetime.now()), "kickoff": str(quando),
                   "falhas": []}
    for lado, team_id in (("home", casa), ("away", fora)):
        t: dict = {"team_id": team_id}
        try:
            escal = _escalacoes_longas(cur, team_id, quando, instante)
        except Exception as e:
            cur.connection.rollback()
            escal = []
            saida["falhas"].append(f"escalacoes {lado}: {e}")
        api, falha = (None, None)
        if "tecnico" in fatores_ligados():
            api, falha = tecnico_atual(cur, team_id, instante)
        if falha:
            saida["falhas"].append(falha)
        regime = regime_do_tecnico(escal, api)
        if regime:
            t["regime"] = {k: (str(v) if isinstance(v, (date, datetime)) else v)
                           for k, v in regime.items()}
        d = (desfalques or {}).get(lado) or {}
        ids = set(d.get("fora") or ())
        if ids:
            t["desfalques_ids"] = sorted(ids)
            try:
                t["producao"] = producao_perdida(_linhas_de_producao(cur, team_id, quando), ids)
            except Exception as e:
                cur.connection.rollback()
                saida["falhas"].append(f"producao {lado}: {e}")
        if d.get("duvidas"):
            t["duvidas"] = list(d["duvidas"])
        if d.get("falhou"):
            saida["falhas"].append(f"/injuries {lado}")
        if (calendario or {}).get(team_id):
            t["calendario"] = calendario[team_id]
        try:
            t["concluidos_recentes"] = _concluidos_recentes(cur, team_id, quando)
        except Exception as e:
            cur.connection.rollback()
            saida["falhas"].append(f"calendario {lado}: {e}")
        saida[lado] = t
    km = _viagem_do_visitante(cur, fixture_id, fora, quando)
    if km is not None:
        saida["away"]["viagem_km"] = km
    return saida


def resumo_para_ia(contexto: dict | None) -> dict | None:
    """O mesmo contexto, enxuto, pro dossie da IA. A IA interpreta; a conta
    fica aqui."""
    if not contexto:
        return None
    saida = {}
    for lado, nome in (("home", "mandante"), ("away", "visitante")):
        t = contexto.get(lado) or {}
        bloco = {}
        r = t.get("regime") or {}
        if r:
            bloco["tecnico"] = {k: r[k] for k in ("tecnico", "anterior", "inicio",
                                                  "jogos_sob_tecnico", "formacao",
                                                  "formacao_anterior") if r.get(k) is not None}
        prod = t.get("producao")
        if prod:
            bloco["producao_dos_desfalcados"] = {
                k: f"{v['perdido']:.0f} de {v['total']:.0f}"
                for k, v in prod.items() if isinstance(v, dict) and v.get("perdido")}
        if t.get("duvidas"):
            bloco["duvidas"] = t["duvidas"][:6]
        if t.get("viagem_km") is not None:
            bloco["viagem_km"] = t["viagem_km"]
        if bloco:
            saida[nome] = bloco
    if contexto.get("falhas"):
        saida["fontes_que_falharam"] = contexto["falhas"][:5]
    return saida or None
