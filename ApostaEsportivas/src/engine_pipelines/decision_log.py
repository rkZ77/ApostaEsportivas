"""Log de decisao do motor deterministico -- registra, pra cada fixture
processado por qualquer engine_pipelines/*.py, TODOS os candidatos
avaliados (nao so o escolhido) com seus scores completos. Objetivo:
dar visibilidade real do "por que" um mercado venceu outro, sem precisar
reproduzir manualmente toda vez que algo parecer estranho (ex: motor
"só escolhendo cartão" -- com esse log da pra ver na hora se e sinal
real ou algum termo do Score Final dominando os outros).

Grava em logs/engine_decisions.jsonl (uma linha por fixture) e imprime um
resumo legivel no console. Nunca derruba o pipeline -- qualquer falha de
log e engolida e so avisada."""
import os
import json
from datetime import datetime

from utils.paths import LOGS_DIR as LOG_DIR, log_path

LOG_PATH = log_path("engine_decisions.jsonl")


def _candidate_summary(c: dict) -> dict:
    # faltas/goleiros nao passam pelo caminho generico do motor: os candidatos
    # deles vem de fouls_model/goalkeeper_model, com outro formato (`line` e
    # `probability` no lugar de `value_label` e `taxa_real`, sem `final_score`
    # nem os scores parciais). Sem esses fallbacks o resumo quebrava em toda
    # chamada desses dois pipelines -- o log em disco ate' era gravado, mas a
    # excecao no _print_summary caia no except de log_decision e imprimia
    # "falha ao gravar log", mensagem que apontava pro lugar errado.
    return {
        "market_type": c.get("market_type") or c.get("modelo"),
        "line": c.get("value_label") or c.get("line"),
        "odd": c.get("odd"),
        "taxa_real": c.get("taxa_real", c.get("probability")),
        "amostra": c.get("amostra", c.get("faixa_amostra")),
        "confidence": c.get("confidence", c.get("probability")),
        "ev": c.get("ev"),
        "edge": c.get("edge"),
        "context_score": c.get("context_score"),
        "profile_score": c.get("profile_score"),
        "news_score": c.get("news_score"),
        "line_score": c.get("line_score"),
        "final_score": c.get("final_score"),
        "is_best_pick": c.get("is_best_pick", False),
        # Sobrescrito em log_decision() com a presenca real em eligible_picks.
        "eligible": c.get("final_score") is not None,
    }


def log_decision(pipeline: str, fixture: dict, all_candidates: list,
                  eligible_picks: list, matchup: dict | None = None,
                  context_data: dict | None = None) -> None:
    """Chamar logo depois de analyze_fixture_markets()+rank_market_candidates()
    pra cada fixture. `all_candidates` = saida de analyze_fixture_markets
    (todos os mercados, mesmo os que nao passaram no filtro minimo -- esses
    nao tem 'final_score' calculado, aparecem com eligible=False).
    `eligible_picks` = saida de rank_market_candidates (so os aprovados)."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)

        candidates_summary = []
        for c in all_candidates:
            key = (c.get("market_type"), c.get("value_label"))
            matched = next((p for p in eligible_picks
                            if (p.get("market_type"), p.get("value_label")) == key), None)
            summary = _candidate_summary(matched if matched else c)
            # Aprovado e' quem saiu em eligible_picks, nao quem tem
            # final_score. Faltas/goleiros nao calculam final_score (modelo
            # proprio, ver _candidate_summary), entao pelo criterio antigo o
            # pick ESCOLHIDO aparecia no log como "REJEITADO".
            summary["eligible"] = matched is not None
            candidates_summary.append(summary)

        entry = {
            "logged_at": datetime.now().isoformat(),
            "pipeline": pipeline,
            "fixture_id": fixture.get("fixture_id"),
            "home_team": fixture.get("home_team"),
            "away_team": fixture.get("away_team"),
            "matchup": matchup,
            "context": context_data,
            "candidates": candidates_summary,
        }

        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        print(f"[DECISION_LOG] Aviso: falha ao gravar log (não afeta o pick): {e}")
        return

    # Fora do try do arquivo de proposito: falha ao IMPRIMIR nao e' falha ao
    # GRAVAR, e a mensagem generica acima ja' mandou investigar o lugar errado
    # uma vez (ver _candidate_summary).
    try:
        _print_summary(pipeline, fixture, candidates_summary)
    except Exception as e:
        print(f"[DECISION_LOG] Aviso: log gravado, falha só ao imprimir o resumo: {e}")


def _pct(v) -> str:
    """Campo ausente vira '  n/d' em vez de estourar o format (candidatos de
    faltas/goleiros nao tem todos os campos do caminho generico)."""
    return f"{v * 100:5.1f}%" if isinstance(v, (int, float)) else "  n/d"


def _print_summary(pipeline: str, fixture: dict, candidates_summary: list) -> None:
    print(f"[DECISION_LOG] {pipeline} | {fixture.get('home_team')} x {fixture.get('away_team')} "
          f"(fixture {fixture.get('fixture_id')})")
    for c in sorted(candidates_summary, key=lambda x: x.get("final_score") or -1, reverse=True):
        marker = " <== ESCOLHIDO" if c["is_best_pick"] else ""
        mt   = str(c.get("market_type") or "?")
        line = str(c.get("line") or "?")
        if c["eligible"]:
            print(f"    [{mt:<12}] {line:<14} taxa={_pct(c['taxa_real'])} "
                  f"amostra={str(c['amostra'] or '-'):<3} conf={_pct(c['confidence'])} ev={_pct(c['ev'])} "
                  f"ctx={c['context_score']} perfil={c['profile_score']} line_score={c['line_score']} "
                  f"score_final={c['final_score']}{marker}")
        else:
            print(f"    [{mt:<12}] {line:<14} REJEITADO (não passou nos critérios mínimos: "
                  f"taxa={_pct(c['taxa_real'])} amostra={c['amostra']} conf={_pct(c['confidence'])})")
