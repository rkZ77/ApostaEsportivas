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

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "logs")
LOG_PATH = os.path.join(LOG_DIR, "engine_decisions.jsonl")


def _candidate_summary(c: dict) -> dict:
    return {
        "market_type": c.get("market_type"),
        "line": c.get("value_label"),
        "odd": c.get("odd"),
        "taxa_real": c.get("taxa_real"),
        "amostra": c.get("amostra"),
        "confidence": c.get("confidence"),
        "ev": c.get("ev"),
        "edge": c.get("edge"),
        "context_score": c.get("context_score"),
        "profile_score": c.get("profile_score"),
        "news_score": c.get("news_score"),
        "line_score": c.get("line_score"),
        "final_score": c.get("final_score"),
        "is_best_pick": c.get("is_best_pick", False),
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

        eligible_ids = {(p["market_type"], p.get("value_label")) for p in eligible_picks}
        candidates_summary = []
        for c in all_candidates:
            key = (c.get("market_type"), c.get("value_label"))
            matched = next((p for p in eligible_picks if (p["market_type"], p.get("value_label")) == key), None)
            candidates_summary.append(_candidate_summary(matched if matched else c))

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

        _print_summary(pipeline, fixture, candidates_summary)

    except Exception as e:
        print(f"[DECISION_LOG] Aviso: falha ao gravar log (não afeta o pick): {e}")


def _print_summary(pipeline: str, fixture: dict, candidates_summary: list) -> None:
    print(f"[DECISION_LOG] {pipeline} | {fixture.get('home_team')} x {fixture.get('away_team')} "
          f"(fixture {fixture.get('fixture_id')})")
    for c in sorted(candidates_summary, key=lambda x: x.get("final_score") or -1, reverse=True):
        marker = " <== ESCOLHIDO" if c["is_best_pick"] else ""
        if c["eligible"]:
            print(f"    [{c['market_type']:<12}] {c['line']:<14} taxa={c['taxa_real']*100:5.1f}% "
                  f"amostra={c['amostra']:<3} conf={c['confidence']*100:4.0f}% ev={c['ev']*100:+6.1f}% "
                  f"ctx={c['context_score']} perfil={c['profile_score']} line_score={c['line_score']} "
                  f"score_final={c['final_score']}{marker}")
        else:
            print(f"    [{c['market_type']:<12}] {c['line']:<14} REJEITADO (não passou nos critérios mínimos: "
                  f"taxa={c['taxa_real']*100:5.1f}% amostra={c['amostra']} conf={c['confidence']*100:4.0f}%)")
