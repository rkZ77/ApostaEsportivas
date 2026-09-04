"""Descobre o regulamento de mata-mata das competicoes que o motor avalia e
que nao estao cadastradas a mao.

QUANTO ISSO CUSTA, QUE E' A PERGUNTA QUE ORIGINOU O SCRIPT
----------------------------------------------------------
Uma chamada por competicao POR TEMPORADA, com um prompt de ~200 tokens e uma
resposta de ~80. Nao e' por partida, nao e' por pick, e nao roda dentro de
nenhum pipeline: o motor apenas LE a tabela que este script escreve (ver
services/pick_engine/competition_rules_store.py).

Na pratica: as sete competicoes que o motor mais avalia ja' estao cadastradas
a mao em competition_profile._REGRAS e nem chegam a ser perguntadas. O que
sobra e' a cauda -- estadual, liga estrangeira que apareceu uma vez, copa nova
-- e a cauda inteira cabe em poucas chamadas por ano.

O QUE ELE NAO FAZ
-----------------
Nao pergunta nada sobre a PARTIDA. Nao pede previsao, nao pede leitura de
contexto, nao pede opiniao sobre mercado. Pergunta so' regulamento, que e'
fato publicado e estavel. Contexto de partida sai de dado medido
(tie_effect.py) e nao volta a depender de modelo.

Nao sobrescreve o cadastro a mao: competition_profile._REGRAS ganha sempre.

USO
    python -m scripts.descobrir_regulamento              # so' lista o que falta
    python -m scripts.descobrir_regulamento --gravar     # pergunta e grava
    python -m scripts.descobrir_regulamento --liga 128   # uma competicao so'
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pick_engine import competition_profile as cp
from services.pick_engine import competition_rules_store as loja
from services.pick_engine import match_context_model as mcm
from utils.db_utils import get_connection

ESQUEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["two_legged_default", "fases_de_jogo_unico", "away_goals",
                 "prorrogacao", "penaltis", "confianca", "observacao"],
    "properties": {
        "two_legged_default": {
            "type": ["boolean", "null"],
            "description": "O mata-mata desta competicao e' disputado em dois jogos? null se nao souber.",
        },
        "fases_de_jogo_unico": {
            "type": "array",
            "items": {"type": "string", "enum": list(mcm._FASES_MATA_MATA)},
            "description": "Fases que fogem do padrao e sao em jogo unico (ex.: FINAL).",
        },
        "away_goals": {
            "type": ["boolean", "null"],
            "description": "Vale criterio de gol fora de casa NESTA temporada? null se nao souber.",
        },
        "prorrogacao": {"type": ["boolean", "null"]},
        "penaltis": {"type": ["boolean", "null"]},
        "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
        "observacao": {"type": "string"},
    },
}

PROMPT = (
    "Voce responde sobre REGULAMENTO de competicoes de futebol. Nao faz previsao, "
    "nao analisa partidas e nao opina sobre apostas. "
    "Responda apenas o que o regulamento publicado da competicao diz para a temporada informada. "
    "Se nao tiver certeza de um item, devolva null nele em vez de supor -- um regulamento "
    "errado e' pior que um regulamento ausente, porque o sistema que consome isto trata "
    "ausencia como 'nao sei' e trata resposta como fato. "
    "Atencao especial ao criterio de gol fora: UEFA aboliu a partir de 2021/22 e CONMEBOL "
    "a partir de 2024; nao assuma que vale."
)


def _perguntar(nome_liga: str, pais: str | None, season: int) -> dict:
    """Uma chamada, JSON validado por schema. Anthropic por padrao (mesmo
    provedor default do ai_review pros fluxos que nao exigem o modelo caro)."""
    from anthropic import Anthropic

    modelo = os.getenv("RULES_MODEL", "claude-sonnet-5")
    pergunta = (
        f"Competicao: {nome_liga}"
        + (f" ({pais})" if pais else "")
        + f"\nTemporada: {season}\n\n"
        "Como e' disputado o mata-mata dela nessa temporada?"
    )
    resposta = Anthropic().messages.create(
        model=modelo, max_tokens=600, system=PROMPT,
        output_config={"format": {"type": "json_schema", "schema": ESQUEMA}},
        messages=[{"role": "user", "content": pergunta}],
    )
    if resposta.stop_reason == "refusal":
        raise RuntimeError("provedor recusou responder")
    texto = next((b.text for b in resposta.content if b.type == "text"), "")
    return json.loads(texto or "{}"), modelo


def _competicoes_sem_regulamento(cur, liga_alvo: int | None) -> list:
    """Competicoes com fase de mata-mata na base e sem cadastro a mao.

    Sai de `match_statistics` (round ja' coletado) porque e' onde a evidencia
    de que a competicao TEM mata-mata realmente esta -- pedir regulamento de
    liga que so' joga pontos corridos seria gastar chamada a toa.
    """
    cur.execute("""
        SELECT ms.league_id, ms.season, COALESCE(max(l.name), ''), '',
               count(*)
          FROM match_statistics ms
          LEFT JOIN leagues l ON l.league_id = ms.league_id
         WHERE ms.round IS NOT NULL
           AND (ms.round ILIKE '%%round of%%' OR ms.round ILIKE '%%quarter%%'
                OR ms.round ILIKE '%%semi%%' OR ms.round ILIKE '%%final%%'
                OR ms.round ILIKE '%%play%%')
         GROUP BY 1, 2
         ORDER BY 5 DESC
    """)
    saida = []
    for league_id, season, nome, pais, jogos in cur.fetchall():
        if liga_alvo is not None and league_id != liga_alvo:
            continue
        if league_id in cp._REGRAS:
            continue          # cadastrado a mao: nunca pergunta
        saida.append((league_id, season, nome, pais, jogos))
    return saida


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gravar", action="store_true",
                   help="pergunta ao modelo e grava; sem isso, so' lista")
    p.add_argument("--liga", type=int, help="restringe a uma competicao")
    p.add_argument("--env", default=os.getenv("DB_ENV") or "dev")
    args = p.parse_args()

    conn = get_connection(args.env)
    cur = conn.cursor()
    loja.criar_tabela(cur)
    conn.commit()

    pendentes = _competicoes_sem_regulamento(cur, args.liga)
    ja_no_banco = loja.carregar(cur)

    if not pendentes:
        print("Nenhuma competicao de mata-mata fora do cadastro a mao.")
        return

    print(f"{len(pendentes)} competicao(oes) com mata-mata e sem cadastro a mao:\n")
    perguntadas = 0
    for league_id, season, nome, pais, jogos in pendentes:
        marca = "ja no banco" if league_id in ja_no_banco else "SEM REGULAMENTO"
        print(f"  liga {league_id:5} {season}  {nome or '(sem nome)':35} "
              f"{jogos:3} jogos  [{marca}]")
        if not args.gravar or league_id in ja_no_banco:
            continue
        if not nome:
            print("       -> sem nome em `leagues`, nao da' pra perguntar sem advinhar")
            continue
        try:
            dados, modelo = _perguntar(nome, pais, season)
        except Exception as e:
            print(f"       -> falhou: {e}")
            continue
        perguntadas += 1
        regras = cp.RegrasDeMataMata(
            two_legged_default=dados.get("two_legged_default"),
            fases_de_jogo_unico=frozenset(dados.get("fases_de_jogo_unico") or []),
            away_goals=dados.get("away_goals"),
            prorrogacao=dados.get("prorrogacao"),
            penaltis=dados.get("penaltis"),
        )
        # Confianca baixa nao entra: o motor trata o que esta na tabela como
        # fato, entao um "acho que sim" ali vira afirmacao no rastro do pick.
        if dados.get("confianca") == "baixa":
            print(f"       -> modelo respondeu com confianca baixa, descartado: "
                  f"{dados.get('observacao')}")
            continue
        loja.gravar(cur, league_id, season, regras, fonte=f"ia:{modelo}",
                    observacao=dados.get("observacao"))
        conn.commit()
        print(f"       -> gravado: duas_pernas={regras.two_legged_default} "
              f"gol_fora={regras.away_goals} prorrogacao={regras.prorrogacao} "
              f"penaltis={regras.penaltis} "
              f"jogo_unico_em={sorted(regras.fases_de_jogo_unico) or '-'}")

    if args.gravar:
        print(f"\n{perguntadas} chamada(s) ao modelo nesta execucao.")
    else:
        print("\nNada foi perguntado nem gravado. Use --gravar para preencher.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
