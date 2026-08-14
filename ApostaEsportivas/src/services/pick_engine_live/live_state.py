"""Estado completo da partida, eventos e qualidade do dado (freshness).

POR QUE FRESHNESS E' UM GATE E NAO UM AVISO
-------------------------------------------
No pre-jogo, dado atrasado produz um pick pior. Ao vivo, dado atrasado produz
um pick sobre OUTRA PARTIDA -- a que existia dois minutos atras. Um Over 9.5
de escanteios calculado sobre uma folha que ainda mostra 6 quando o jogo ja
tem 9 nao e' uma estimativa imprecisa: e' uma resposta a uma pergunta que nao
foi feita.

Por isso `STALE` bloqueia a analise inteira, antes de qualquer modelo rodar.

COMO O ATRASO E' MEDIDO SEM A API DIZER
---------------------------------------
/fixtures/statistics nao carrega carimbo de atualizacao. Mas /fixtures traz
`fixture.timestamp` (o apito inicial em epoch) e `status.elapsed` (o minuto que
o provedor acredita). Com os dois da' pra estimar:

    minuto_esperado = (agora - apito) / 60  -  intervalo, quando ja passou

e comparar com o minuto reportado. Uma diferenca de 1 a 3 minutos e' normal
(acrescimo, VAR, o proprio arredondamento do provedor). Uma diferenca grande
significa feed parado.

O segundo sinal e' o RELOGIO CONGELADO entre duas leituras nossas: se a rodada
anterior viu o minuto 55 ha 8 minutos de relogio de parede e o provedor ainda
diz 55, o feed travou -- e esse sinal nao depende de estimativa nenhuma.
"""
from __future__ import annotations

from datetime import datetime, timezone

from services.pick_engine_live.config import DEFAULT_LIVE_CONFIG, LiveEngineConfig

FRESH = "FRESH"
DELAYED = "DELAYED"
STALE = "STALE"
UNKNOWN = "UNKNOWN"

#: Duracao tipica do intervalo. Entra na conta do minuto esperado porque o
#: relogio do jogo para no HT e o relogio de parede nao.
INTERVALO_MINUTOS = 15

#: Contadores que precisam existir pra a folha ser considerada completa. Nao
#: inclui "Dangerous Attacks" nem "expected_goals" de proposito: os dois sao
#: opcionais na API-Football e exigir os dois reprovaria a folha da maioria
#: das ligas.
CONTADORES_ESSENCIAIS = ("Total Shots", "Shots on Goal", "Corner Kicks")


def _agora_epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


def montar_estado(fixture_bruto: dict, home_stats: dict, away_stats: dict,
                  eventos: list | None = None) -> dict:
    """Retrato normalizado e COMPLETO da partida neste instante.

    E' este dicionario que vira o snapshot gravado no pick, entao ele responde
    literalmente "o que o motor sabia quando decidiu". Nada que nao esteja aqui
    influenciou a decisao.
    """
    fixture = fixture_bruto.get("fixture", {}) or {}
    bloco_status = fixture.get("status", {}) or {}
    gols = fixture_bruto.get("goals", {}) or {}
    times = fixture_bruto.get("teams", {}) or {}
    liga = fixture_bruto.get("league", {}) or {}

    def par(campo: str, peso_vermelho: bool = False):
        casa, fora = home_stats.get(campo), away_stats.get(campo)
        total = None if (casa is None or fora is None) else casa + fora
        return casa, fora, total

    home_goals, away_goals = gols.get("home"), gols.get("away")
    gols_total = (None if home_goals is None or away_goals is None
                  else int(home_goals) + int(away_goals))

    c_casa, c_fora, c_total = par("Corner Kicks")
    s_casa, s_fora, s_total = par("Total Shots")
    a_casa, a_fora, a_total = par("Shots on Goal")
    d_casa, d_fora, d_total = par("Dangerous Attacks")
    b_casa, b_fora, b_total = par("Blocked Shots")
    y_casa, y_fora, _ = par("Yellow Cards")
    r_casa, r_fora, r_total = par("Red Cards")

    return {
        "fixture_id": fixture.get("id"),
        "kickoff_epoch": fixture.get("timestamp"),
        "status": bloco_status.get("short", "NS"),
        "periodo": _periodo(bloco_status.get("short")),
        "minuto": bloco_status.get("elapsed"),
        "minuto_extra": bloco_status.get("extra") or 0,

        "league_id": liga.get("id"),
        "league_name": liga.get("name"),
        "home_team": (times.get("home") or {}).get("name"),
        "away_team": (times.get("away") or {}).get("name"),
        "home_team_id": (times.get("home") or {}).get("id"),
        "away_team_id": (times.get("away") or {}).get("id"),

        "home_goals": home_goals,
        "away_goals": away_goals,
        "goals_total": gols_total,
        # Modulo: "o jogo esta' apertado?". E' o que ritmo e ajuste de estado
        # perguntam, e por isso continua existindo com este nome.
        "diferenca_gols": (None if gols_total is None
                           else abs(int(home_goals) - int(away_goals))),
        # COM SINAL (>0 = mandante na frente): "quem precisa do resultado?".
        # Pergunta diferente, e ate 2026-08-14 impossivel de fazer -- o abs()
        # acima era o unico placar que o motor guardava, entao um 2x0 e um 0x2
        # eram indistinguiveis pra ele. Sem o sinal nao ha como cruzar o placar
        # com o agregado do mata-mata nem com a necessidade de tabela.
        "saldo_mandante": (None if gols_total is None
                           else int(home_goals) - int(away_goals)),

        "corners_home": c_casa, "corners_away": c_fora, "corners_total": c_total,
        "shots_home": s_casa, "shots_away": s_fora, "shots_total": s_total,
        "shots_on_target_home": a_casa, "shots_on_target_away": a_fora,
        "shots_on_target_total": a_total,
        "dangerous_attacks_home": d_casa, "dangerous_attacks_away": d_fora,
        "dangerous_attacks_total": d_total,
        "blocked_shots_home": b_casa, "blocked_shots_away": b_fora,
        "blocked_shots_total": b_total,
        "yellow_home": y_casa, "yellow_away": y_fora,
        "red_home": r_casa, "red_away": r_fora, "red_cards_total": r_total,
        "possession_home": home_stats.get("Ball Possession"),
        "possession_away": away_stats.get("Ball Possession"),
        "xg_home": home_stats.get("expected_goals"),
        "xg_away": away_stats.get("expected_goals"),

        "eventos_recentes": eventos or [],
        # Retrato bruto dos dois lados: e' o que permite recalcular qualquer
        # sinal depois sem recoletar. Barato de guardar, caro de recuperar.
        "_folha_home": dict(home_stats),
        "_folha_away": dict(away_stats),
    }


def _periodo(status: str | None) -> str | None:
    return {"1H": "1o_tempo", "HT": "intervalo", "2H": "2o_tempo",
            "ET": "prorrogacao", "BT": "intervalo_prorrogacao",
            "P": "penaltis"}.get(status or "")


# ─────────────────────────────────────────────────────────────────────────
# EVENTOS
# ─────────────────────────────────────────────────────────────────────────
#: Tipos de /fixtures/events que mudam o ESTADO do jogo, nao so' a contagem.
#: Substituicao entra porque troca de peca ofensiva no fim de jogo e' um dos
#: sinais mais fortes de "o time vai forcar" -- mas so' e' registrada, nao
#: pesa no modelo da V1 (nao ha como distinguir troca ofensiva de defensiva
#: sem dado de posicao, e chutar isso seria inventar sinal).
TIPOS_RELEVANTES = ("Goal", "Card", "subst", "Var")

#: Eventos que, sozinhos, justificam reavaliar a partida.
EVENTOS_QUE_MUDAM_O_JOGO = ("Goal", "Red Card", "Penalty")


def ler_eventos(brutos: list, minuto_atual: int | None = None,
                janela: int = 15) -> list[dict]:
    """Normaliza /fixtures/events e marca o que e' recente.

    A API devolve o evento com `time.elapsed`, que e' o MINUTO em que
    aconteceu. E' a unica fonte de "quando" que o feed tem -- a folha de
    estatistica so' sabe somar. Sem isso o motor sabe que teve um vermelho e
    nao sabe se foi aos 12' ou aos 80', que sao partidas diferentes.
    """
    saida: list[dict] = []
    for e in brutos or []:
        tipo = (e.get("type") or "").strip()
        detalhe = (e.get("detail") or "").strip()
        minuto = ((e.get("time") or {}).get("elapsed"))
        if minuto is None:
            continue
        vermelho = tipo == "Card" and "Red" in detalhe
        penalti = "Penalty" in detalhe
        registro = {
            "minuto": int(minuto),
            "extra": (e.get("time") or {}).get("extra"),
            "tipo": tipo,
            "detalhe": detalhe,
            "time": ((e.get("team") or {}).get("name")),
            "team_id": ((e.get("team") or {}).get("id")),
            "jogador": ((e.get("player") or {}).get("name")),
            "vermelho": vermelho,
            "penalti": penalti,
            "gol": tipo == "Goal",
            "recente": (minuto_atual is not None
                        and int(minuto) >= int(minuto_atual) - janela),
        }
        saida.append(registro)
    saida.sort(key=lambda r: r["minuto"])
    return saida


def resumo_de_eventos(eventos: list, minuto_atual: int | None = None) -> dict:
    """O que aconteceu, com minuto, pro modelo e pra explicacao.

    `vermelho_minuto` importa mais que "houve vermelho": expulsao aos 20' muda
    75 minutos de jogo, aos 85' quase nao muda nada. O modelo de estado usa o
    minuto pra pesar isso.
    """
    if not eventos:
        return {"total": 0, "gols": 0, "vermelhos": 0, "penaltis": 0,
                "vermelho_minuto": None, "ultimo_gol_minuto": None,
                "recentes": [], "disponivel": False}
    gols = [e for e in eventos if e["gol"]]
    vermelhos = [e for e in eventos if e["vermelho"]]
    return {
        "total": len(eventos),
        "gols": len(gols),
        "vermelhos": len(vermelhos),
        "penaltis": len([e for e in eventos if e["penalti"]]),
        "vermelho_minuto": min(e["minuto"] for e in vermelhos) if vermelhos else None,
        "ultimo_gol_minuto": max(e["minuto"] for e in gols) if gols else None,
        "recentes": [e for e in eventos if e.get("recente")],
        "disponivel": True,
    }


# ─────────────────────────────────────────────────────────────────────────
# FRESHNESS
# ─────────────────────────────────────────────────────────────────────────
def completude(home_stats: dict, away_stats: dict) -> dict:
    presentes = [c for c in CONTADORES_ESSENCIAIS
                 if home_stats.get(c) is not None and away_stats.get(c) is not None]
    return {
        "essenciais": len(CONTADORES_ESSENCIAIS),
        "presentes": len(presentes),
        "faltando": [c for c in CONTADORES_ESSENCIAIS if c not in presentes],
        "fracao": round(len(presentes) / len(CONTADORES_ESSENCIAIS), 3),
    }


def freshness(estado: dict, observacoes: list | None = None,
              config: LiveEngineConfig = DEFAULT_LIVE_CONFIG,
              agora_epoch: float | None = None) -> dict:
    """FRESH | DELAYED | STALE | UNKNOWN, com os motivos.

    Tres verificacoes independentes, da mais forte pra mais fraca:

    1. RELOGIO CONGELADO entre duas leituras nossas. Nao depende de estimativa:
       se ha 8 minutos de relogio de parede o provedor dizia 55' e continua
       dizendo 55', o feed travou.
    2. MINUTO ESPERADO vs reportado, a partir do apito inicial.
    3. COMPLETUDE da folha.

    Qualquer uma delas em nivel critico derruba pra STALE, e STALE bloqueia a
    analise. Empurrar pra DELAYED nao bloqueia, mas entra na confianca.
    """
    agora = agora_epoch if agora_epoch is not None else _agora_epoch()
    motivos: list[str] = []
    niveis: list[str] = []

    minuto = estado.get("minuto")
    if minuto is None:
        return {"nivel": UNKNOWN, "motivos": ["provedor nao publicou o minuto"],
                "atraso_estimado": None, "completude": completude(
                    estado.get("_folha_home") or {}, estado.get("_folha_away") or {})}

    # 1 · relogio congelado
    congelado = None
    if observacoes:
        anterior = observacoes[0] if isinstance(observacoes[0], dict) else None
        if anterior and anterior.get("minuto") is not None and anterior.get("epoch"):
            decorrido_parede = (agora - float(anterior["epoch"])) / 60.0
            avanco_relogio = int(minuto) - int(anterior["minuto"])
            if decorrido_parede >= 5 and avanco_relogio <= 0:
                congelado = round(decorrido_parede, 1)
                motivos.append(
                    f"relogio do provedor parado em {minuto}' ha {congelado} min de relogio real")
                niveis.append(STALE)

    # 2 · minuto esperado a partir do apito
    atraso = None
    kickoff = estado.get("kickoff_epoch")
    if kickoff:
        decorrido = (agora - float(kickoff)) / 60.0
        esperado = decorrido
        # Depois do intervalo, o relogio do jogo perdeu ~15 minutos de parede.
        if estado.get("status") in ("2H", "ET", "BT", "P") or int(minuto) > 45:
            esperado -= INTERVALO_MINUTOS
        atraso = round(esperado - int(minuto), 1)
        if atraso > config.atraso_maximo_minutos * 2:
            motivos.append(f"minuto reportado {atraso:.0f} min atras do esperado")
            niveis.append(STALE)
        elif atraso > config.atraso_maximo_minutos:
            motivos.append(f"minuto reportado {atraso:.0f} min atras do esperado")
            niveis.append(DELAYED)

    # 3 · completude da folha
    comp = completude(estado.get("_folha_home") or {}, estado.get("_folha_away") or {})
    if comp["presentes"] == 0:
        motivos.append("folha de estatistica vazia")
        niveis.append(STALE)
    elif comp["fracao"] < 1.0:
        motivos.append(f"folha incompleta: falta {', '.join(comp['faltando'])}")
        niveis.append(DELAYED)

    if STALE in niveis:
        nivel = STALE
    elif DELAYED in niveis:
        nivel = DELAYED
    else:
        nivel = FRESH
    return {"nivel": nivel, "motivos": motivos, "atraso_estimado": atraso,
            "relogio_congelado_min": congelado, "completude": comp}
