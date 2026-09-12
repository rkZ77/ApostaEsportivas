"""A auditoria final (§42) e o rastro da decisao (§41).

POR QUE A CHECKLIST E' CODIGO E NAO COMENTARIO
----------------------------------------------
O §42 lista vinte perguntas e manda reprovar se qualquer item critico falhar.
Escrever isso como uma sequencia de `if` dentro do pipeline funciona e tem um
defeito conhecido: a auditoria passa a mostrar so' o PRIMEIRO item que falhou, e
quem le' o painel conclui que o pick morreu de amostra quando ele morreria de
minutos logo depois.

Aqui as vinte perguntas sao avaliadas TODAS, sempre, e o que sai e' a lista
inteira com o veredito de cada uma. O motivo publicado continua sendo o primeiro
critico -- e' o que cabe num card -- mas o resto fica gravado.

CRITICO E INFORMATIVO
---------------------
Nem toda pergunta do §42 reprova. "O mando foi considerado?" e' verificacao de
COBERTURA: se a resposta for nao, o pick pode continuar (o metodo pode nao ter
mando relevante), mas a auditoria precisa poder mostrar quantos picks sairam sem
aquela camada. Item informativo que falha nao vira NO_PICK, vira contagem.
"""
from __future__ import annotations

from services.player_stats_engine import config as cfg
from services.player_stats_engine import contradiction, minutes_model


def _item(chave: str, pergunta: str, ok: bool, *, critico: bool,
          detalhe: str | None = None) -> dict:
    return {"chave": chave, "pergunta": pergunta, "ok": bool(ok),
            "critico": critico, "detalhe": detalhe}


def checklist(c: dict) -> list:
    """As vinte perguntas do §42, respondidas contra ESTE candidato."""
    a = c["analise"]
    metodo = c["metodo"]
    minutos = c.get("minutos") or {}
    disp = c.get("dispersao") or {}
    margem = c.get("margem") or {}
    qualidade = c.get("data_quality") or {}
    adversario = c.get("adversario_ajuste") or {}
    achados = c.get("contradicoes") or []

    prob = a.get("probability") or 0
    odd = a.get("odd") or 0
    esperados = minutos.get("esperados")

    itens = [
        _item("disponivel", "O jogador está disponível?",
              minutos.get("status") != minutes_model.DESCONHECIDO, critico=True,
              detalhe=minutos.get("status")),
        _item("titularidade", "É titular ou tem minutos previsíveis?",
              minutos.get("status") == minutes_model.PROVAVEL, critico=True,
              detalhe=f"status {minutos.get('status')}, "
                      f"risco {minutos.get('risco')}"),
        _item("funcao", "A função está correta?",
              minutos.get("risco_funcao") in ("LOW", "MEDIUM"), critico=True,
              detalhe=minutos.get("posicao")),
        _item("historico", "O mercado tem histórico suficiente?",
              (a.get("amostra") or 0) > 0, critico=True),
        _item("amostra", "A amostra é suficiente?",
              (a.get("amostra") or 0) >= metodo.min_atuacoes, critico=True,
              detalhe=f"{a.get('amostra')} de {metodo.min_atuacoes} exigidas"),
        _item("historico_especifico", "O histórico é do mercado específico?",
              True, critico=False, detalhe=f"coluna {metodo.coluna}"),
        _item("mando", "O mando foi considerado quando relevante?",
              (not metodo.mando_relevante) or (a.get("amostra_no_mando") or 0) > 0,
              critico=False,
              detalhe=f"{a.get('amostra_no_mando')} atuações no mando de hoje"),
        _item("adversario", "O adversário foi considerado?",
              bool(adversario.get("disponivel")) or not metodo.coluna_concedida,
              critico=False, detalhe=adversario.get("motivo")),
        _item("matchup", "O matchup foi considerado?",
              bool((c.get("matchup") or {}).get("disponivel")), critico=False,
              detalhe=(c.get("matchup") or {}).get("motivo")),
        _item("minutos", "Os minutos foram considerados?",
              esperados is not None and esperados >= minutes_model.MINUTOS_MINIMOS,
              critico=True, detalhe=f"{esperados} minutos esperados"),
        _item("direcao", "A projeção está do lado certo da linha?",
              margem.get("direcao") == "over", critico=True,
              detalhe=f"projeção {a.get('esperado')} contra linha {a.get('linha')}"),
        _item("margem", "A margem é suficiente?",
              (margem.get("relativa") or 0) >= cfg.MARGEM_RELATIVA_MINIMA,
              critico=True,
              detalhe=f"{(margem.get('relativa') or 0) * 100:.0f}% "
                      f"(mínimo {cfg.MARGEM_RELATIVA_MINIMA * 100:.0f}%)"),
        _item("calibrada", "A probabilidade é calibrada?",
              a.get("probability_calibrada") is not None, critico=True,
              detalhe=f"modelo {(a.get('probability_modelo') or 0) * 100:.1f}% → "
                      f"calibrada {prob * 100:.1f}%"),
        _item("odd", "A odd está correta?",
              odd >= cfg.ODD_MIN and (cfg.ODD_MAX is None or odd <= cfg.ODD_MAX),
              critico=True, detalhe=str(odd)),
        _item("edge", "O edge está correto?",
              _coerente(a.get("edge"), prob - (a.get("implied_probability") or 0)),
              critico=True, detalhe=f"{(a.get('edge') or 0) * 100:+.1f}%"),
        _item("ev", "O EV está correto?",
              _coerente(a.get("ev"), prob * (odd - 1) - (1 - prob)) if odd else False,
              critico=True, detalhe=f"{(a.get('ev') or 0) * 100:+.1f}%"),
        _item("variancia", "A variância foi considerada?",
              disp.get("cv") is not None, critico=False,
              detalhe=f"CV {disp.get('cv')} contra referência "
                      f"{metodo.cv_referencia or 'n/d'}"),
        _item("qualidade", "A qualidade dos dados é suficiente?",
              (qualidade.get("score") or 0) >= cfg.DATA_QUALITY_MINIMO,
              critico=True,
              detalhe=f"{qualidade.get('score')} "
                      f"(mínimo {cfg.DATA_QUALITY_MINIMO})"),
        _item("contradicao", "Existe alguma contradição?",
              not contradiction.criticas(achados), critico=True,
              detalhe="; ".join(x["texto"] for x in contradiction.criticas(achados))
                      or None),
        _item("confianca", "A confidence é compatível com a amostra?",
              not (prob >= 0.80 and (c.get("classe_amostra")
                                     in ("insuficiente", "muito limitada"))),
              critico=True,
              detalhe=f"probabilidade {prob * 100:.0f}% sobre amostra "
                      f"{c.get('classe_amostra')}"),
    ]
    return itens


#: Tolerancia da conferencia aritmetica do §26. Os campos sao arredondados em
#: quatro casas ao serem gravados, entao exigir igualdade exata reprovaria por
#: arredondamento -- e uma checagem que reprova o caso correto nao checa nada.
TOLERANCIA = 0.0015


def _coerente(gravado, recalculado) -> bool:
    if gravado is None or recalculado is None:
        return False
    return abs(float(gravado) - float(recalculado)) <= TOLERANCIA


def avaliar(c: dict) -> tuple:
    """(decisao, motivo, checklist). `decisao` e' "PICK" ou "NO_PICK" (§37).

    O NO_PICK aqui e' resultado NORMAL e nao falha -- e' a frase do §37, e este
    motor ja' vivia assim (dia sem pick e' o caso comum dele). O que muda e' que
    agora existe um lugar unico que responde POR QUE, com as vinte perguntas
    respondidas em vez de um corte solto.
    """
    itens = checklist(c)
    falhas_criticas = [i for i in itens if i["critico"] and not i["ok"]]
    if falhas_criticas:
        primeiro = falhas_criticas[0]
        motivo = primeiro["pergunta"].rstrip("?").lower()
        if primeiro.get("detalhe"):
            motivo = f"{motivo}: {primeiro['detalhe']}"
        return ("NO_PICK", motivo, itens)
    return ("PICK", None, itens)


def engine_debug(c: dict, decisao: str, motivo: str | None, itens: list) -> dict:
    """O §41 inteiro, com os nomes que o resto do projeto ja' usa.

    Nao e' o JSON do prompt letra por letra: `player`/`availability`/`history`
    virariam um segundo vocabulario dentro de um motor que ja' grava
    `jogador`/`minutos`/`amostra` em PT, e duas linguas no mesmo rastro e' como
    se perdem as traducoes (aconteceu com `familia_contexto` em 27/08). Os
    CAMPOS do §41 estao todos aqui, com os nomes da casa.
    """
    a = c["analise"]
    minutos = c.get("minutos") or {}
    return {
        "jogador": {
            "player_id": c["jogador"]["player_id"],
            "nome": c["jogador"]["player_name"],
            "time": c["jogador"].get("team_name"),
            "posicao": minutos.get("posicao") or c["jogador"].get("position"),
        },
        "disponibilidade": {
            "status": minutos.get("status"),
            "titular_confirmado": False,   # a API so' publica escalação oficial
            "taxa_titularidade": c["jogador"].get("taxa_titularidade"),
            "minutos_esperados": minutos.get("esperados"),
            "risco_de_minutos": minutos.get("risco"),
            "perfil": minutos.get("perfil"),
        },
        "funcao": {"posicao": minutos.get("posicao"),
                   "risco_de_funcao": minutos.get("risco_funcao")},
        "historico": {
            "valores": (c.get("serie") or [])[:10],
            "atuacoes_lidas": len(c.get("serie") or []),
            "no_mando": (c.get("serie_no_mando") or [])[:10],
            "dias_desde_a_ultima": c.get("dias_desde_ultima"),
            **(c.get("composicao") or {}),
        },
        "amostra": {"atuacoes": a.get("amostra"),
                    "classificacao": c.get("classe_amostra"),
                    "no_mando": a.get("amostra_no_mando"),
                    "peso_do_mando": a.get("peso_do_mando")},
        "dispersao": c.get("dispersao"),
        "outliers": c.get("outliers"),
        # DOIS CAMPOS E NAO UM, porque sao dois papeis. `adversario` e' o volume
        # que o adversario PRODUZ, e so' `saves` tem (e' o sinal forte dele);
        # `adversario_ajuste` e' o quanto o adversario CONCEDE, que desloca a
        # projecao dos outros metodos. Colapsar os dois num campo so' faria o
        # rastro de um pick de defesas mostrar "método sem ajuste de adversário"
        # justamente no metodo em que o adversario decide tudo.
        "adversario": c.get("adversario"),
        "adversario_ajuste": c.get("adversario_ajuste"),
        "matchup": c.get("matchup"),
        "projecao": {"esperado": a.get("esperado"),
                     "esperado_bruto": a.get("esperado_bruto"),
                     "esperado_no_mando": a.get("esperado_no_mando"),
                     "linha": a.get("linha"),
                     "margem": c.get("margem")},
        "probabilidade": {"modelo": a.get("probability_modelo"),
                          "calibrada": a.get("probability_calibrada"),
                          "abatimento": a.get("abatimento")},
        "mercado": {"odd": a.get("odd"), "fair_odd": a.get("fair_odd"),
                    "implied_probability": a.get("implied_probability"),
                    "edge": a.get("edge"), "ev": a.get("ev")},
        "penalidade_de_variancia": a.get("penalidade_variancia"),
        "qualidade_do_dado": c.get("data_quality"),
        "contradicoes": c.get("contradicoes"),
        "stake": c.get("stake_fator"),
        "selecao": c.get("selecao"),
        "auditoria_final": itens,
        "decisao": decisao,
        "motivo": motivo,
    }
