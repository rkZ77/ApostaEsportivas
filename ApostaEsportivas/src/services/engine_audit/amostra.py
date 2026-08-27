"""A AMOSTRA: quais jogos o motor realmente olhou, em formato exibivel.

O PROBLEMA QUE ISTO RESOLVE
---------------------------
O motor le historico e devolve uma probabilidade. Entre as duas pontas ficava
um vazio: ninguem -- nem o admin, nem o assinante no "Entenda esta analise" --
conseguia ver QUAIS jogos entraram na conta. E o recorte muda por competicao:

  · liga: os jogos daquele time NAQUELA liga e temporada
    (MatchStatsService.get_all_matches_full);
  · copa de clube e selecao: TODAS as competicoes do time
    (get_last_n_all_competitions), porque a propria competicao nao acumula
    jogo suficiente -- ver competition_profile.uses_all_competitions_history.

Quem olhava a tela de forma recente do site via sempre o primeiro recorte, e
em jogo de copa isso e' uma amostra que o motor nunca usou.

E ha' um segundo recorte, o do CONFRONTO: mata-mata tem jogo de ida, agregado
e regra de classificacao, e classico tem excesso de cartao medido. O motor ja'
calcula tudo isso (context_gate.build_context -> tie / rivalidade); o numero
saia na decisao e a frase nunca chegava a lugar nenhum.

O QUE ESTE MODULO E' E O QUE ELE NAO E'
--------------------------------------
E' um FORMATADOR. Recebe as listas de historico que o pipeline ja' carregou e
o contexto que ele ja' montou, e devolve um dicionario pequeno pra gravar em
`engine_debug` e em `engine_decisions.context`.

Nao le banco, nao chama API, nao recalcula nada. Se recalculasse, a amostra
exibida poderia divergir da que decidiu -- que e' exatamente o defeito que ele
existe pra fechar.

TETO DE 10 JOGOS POR TIME
-------------------------
O motor le mais que isso (DEFAULT_LIMIT_LEAGUE pega a temporada inteira). Dez
e' o teto de EXIBICAO, pedido pelo usuario: o objetivo e' visibilidade
gerencial, e uma lista de 38 linhas por time num modal de celular nao e'
visibilidade. `jogos_lidos` guarda quantos o motor de fato usou, entao a tela
pode dizer "10 de 34" e nao fingir que a amostra era dez.
"""
from __future__ import annotations

#: Teto de jogos GRAVADOS por time. Ver a docstring: e' limite de exibicao,
#: nao de analise.
MAX_JOGOS = 10


def _iso(data) -> str | None:
    if data is None:
        return None
    return data.isoformat() if hasattr(data, "isoformat") else str(data)


def _num(valor):
    """Numero puro pra JSON. Decimal do psycopg2 nao serializa sozinho."""
    if valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _linha_do_jogo(jogo: dict, team_id: int) -> dict:
    """Um jogo do historico, do ponto de vista do time analisado.

    `pro`/`contra` sao resolvidos por team_id e nunca pela coluna home/away:
    o mesmo time aparece dos dois lados ao longo da temporada, e ler pela
    coluna inverteria metade da amostra.
    """
    e_mandante = jogo.get("home_team_id") == team_id
    gols_pro = jogo.get("home_goals") if e_mandante else jogo.get("away_goals")
    gols_contra = jogo.get("away_goals") if e_mandante else jogo.get("home_goals")

    ht_casa = jogo.get("home_goals_ht")
    ht_fora = jogo.get("away_goals_ht")
    gols_ht = (None if ht_casa is None or ht_fora is None
               else int(ht_casa) + int(ht_fora))

    return {
        "data": _iso(jogo.get("match_date")),
        "league_id": jogo.get("league_id"),
        "adversario": jogo.get("opponent_name"),
        "mando": "casa" if e_mandante else "fora",
        "gols_pro": _num(gols_pro),
        "gols_contra": _num(gols_contra),
        "gols_total": _num(jogo.get("total_goals")),
        "gols_ht": gols_ht,
        # Contadores das outras familias, pra a mesma amostra servir a
        # escanteios/cartoes/faltas sem uma segunda leitura.
        "escanteios_total": _num(jogo.get("total_corners")),
        "cartoes_total": _num(jogo.get("total_yellow_cards")),
        "faltas_pro": _num(jogo.get("home_fouls") if e_mandante else jogo.get("away_fouls")),
        "faltas_contra": _num(jogo.get("away_fouls") if e_mandante else jogo.get("home_fouls")),
        "chutes_alvo_pro": _num(jogo.get("home_shots_on") if e_mandante else jogo.get("away_shots_on")),
        "chutes_alvo_contra": _num(jogo.get("away_shots_on") if e_mandante else jogo.get("home_shots_on")),
    }


def do_time(historico: list, team_id: int, nome: str | None = None,
            mando_do_jogo: str | None = None, max_jogos: int = MAX_JOGOS) -> dict:
    """A amostra de UM time: os `max_jogos` mais recentes que o motor leu.

    `historico` chega ordenado do mais recente pro mais antigo (todos os
    leitores de MatchStatsService ordenam por match_date DESC), entao o corte
    e' um fatiamento -- nao ha ordenacao nova aqui, que poderia divergir da do
    motor.
    """
    historico = historico or []
    jogos = [_linha_do_jogo(j, team_id) for j in historico[:max_jogos]]
    ligas = {j.get("league_id") for j in historico if j.get("league_id")}
    return {
        "team_id": team_id,
        "time": nome,
        "mando_do_jogo": mando_do_jogo,
        # Quantos o motor USOU, contra quantos estao listados aqui. As duas
        # coisas sao diferentes e a tela precisa das duas pra nao mentir.
        "jogos_lidos": len(historico),
        "jogos_exibidos": len(jogos),
        # Mais de uma liga na lista = o recorte multi-competicao entrou (copa
        # ou selecao). E' o jeito de a tela dizer de onde a amostra veio sem
        # precisar reconsultar competition_profile.
        "multi_competicao": len(ligas) > 1,
        "competicoes": sorted(ligas),
        "jogos": jogos,
    }


def _do_confronto(match_context: dict | None) -> dict | None:
    """O contexto do CONFRONTO, achatado pra leitura.

    Sai do que `context_gate.build_context` ja' devolveu: mata-mata, perna,
    jogo de ida, agregado e rivalidade. Nada recalculado.
    """
    if not match_context:
        return None
    tie = match_context.get("tie") or {}
    rivalidade = match_context.get("rivalidade") or {}

    contexto = {
        "descricao": match_context.get("descricao") or None,
        "fase": tie.get("fase"),
        "is_mata_mata": bool(tie.get("is_mata_mata")),
        "is_jogo_de_volta": bool(tie.get("is_jogo_de_volta")),
        # De onde veio a afirmacao de que este e' o jogo de volta: "rotulo"
        # (a API disse) ou "inferido". Quem le a explicacao precisa poder
        # saber se aquilo e' fato ou deducao.
        "leg_origem": tie.get("leg_origem"),
        "formato": tie.get("formato"),
        "formato_origem": tie.get("formato_origem"),
        # "Classico" aqui nao e' rotulo editorial: e' o EXCESSO de cartao
        # medido no confronto direto contra a linha de base da familia
        # (rivalry_model). `label` e' 'rivalidade_alta' | 'normal' |
        # 'confronto_frio' | 'desconhecido', e so' o primeiro conta -- com
        # `confiavel=False` a amostra de H2H era curta demais pra afirmar
        # qualquer coisa, e ausencia de dado nunca vira evidencia de calma.
        "rivalidade_label": rivalidade.get("label"),
        "is_classico": bool(rivalidade.get("confiavel")
                            and rivalidade.get("label") == "rivalidade_alta"),
        "rivalidade_confrontos": rivalidade.get("confrontos"),
        "rivalidade_excesso": rivalidade.get("excesso"),
    }

    # Jogo de ida: so' existe quando a perna 2 foi identificada E o placar da
    # ida foi resolvido por team_id (ver match_context_model.tie_context).
    ida = tie.get("placar_ida") or {}
    if ida:
        contexto["jogo_de_ida"] = {
            "data": _iso(ida.get("data")),
            # Nomeados pelo mando de HOJE, nao pelo da ida: o mando inverte
            # entre as pernas, e e' exatamente ai' que a leitura costuma
            # trocar de lado.
            "gols_mandante_atual": _num(ida.get("gols_mandante_atual")),
            "gols_visitante_atual": _num(ida.get("gols_visitante_atual")),
        }
        contexto["agregado"] = {
            "home": _num(tie.get("agregado_home")),
            "away": _num(tie.get("agregado_away")),
            "diferenca": _num(tie.get("diferenca_agregada")),
            "gols_para_reverter": _num(tie.get("gols_para_reverter")),
            "lider": tie.get("lider_agregado"),
            "empate_classifica": tie.get("empate_classifica"),
        }
    return contexto


def build(*, home_team_id: int, away_team_id: int,
          historico_home: list, historico_away: list,
          home_team: str | None = None, away_team: str | None = None,
          match_context: dict | None = None,
          max_jogos: int = MAX_JOGOS) -> dict:
    """A amostra completa de uma partida, pronta pra gravar e pra exibir.

    Chamado com as MESMAS listas que o motor passou pro modelo. Passar outra
    lista aqui produziria uma tela que explica um pick que nao foi esse.
    """
    return {
        "max_exibidos": max_jogos,
        "mandante": do_time(historico_home, home_team_id, home_team,
                            mando_do_jogo="casa", max_jogos=max_jogos),
        "visitante": do_time(historico_away, away_team_id, away_team,
                             mando_do_jogo="fora", max_jogos=max_jogos),
        "confronto": _do_confronto(match_context),
    }
