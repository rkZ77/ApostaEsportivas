"""
homologation_dashboard.py -- Le os logs de homologacao (secoes 1-6, ver
services/pick_engine/homologation.py) dos 4 tipos de pick e calcula as
estatisticas agregadas (secao 7 do plano de validacao antes de promover o
motor pra producao): mercados avaliados, descartados por motivo,
distribuicao de score, distribuicao de mercados/linhas escolhidos,
distribuicao por competicao. Gera um dashboard HTML autocontido (dados
embutidos, sem chamada externa) pronto pra publicar como Artifact.

So leitura de arquivo -- sem conexao de banco, roda sobre o que os 4
scripts de homologacao (ai/vip_engine_shadow.py, ai/dica_homologation.py,
ai/multipla_homologation.py, ai/alavancagem_homologation.py) ja
gravaram em logs/*.jsonl. Reexecutavel a qualquer momento pra refletir o
estado acumulado ate agora -- nao e um backfill unico.

Uso:
  python src/scripts/homologation_dashboard.py [--out CAMINHO.html]
"""
import os
import sys
import json
import argparse
from collections import Counter
from datetime import datetime

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SRC_DIR)

from utils.paths import LOGS_DIR as _LOGS_DIR  # noqa: E402  (import após ajustar sys.path)

_LOG_FILES = {
    "VIP": "vip_engine_shadow.jsonl",
    "Free": "dica_homologation.jsonl",
    "Multipla": "multipla_homologation.jsonl",
    "Alavancagem": "alavancagem_homologation.jsonl",
}

# Nomes so pra exibicao no dashboard -- os logs guardam league_id, nao o
# nome (evita depender de conexao de banco so pra rotular o grafico).
_LEAGUE_NAMES = {
    "1": "Copa do Mundo", "2": "Champions League", "3": "Europa League",
    "39": "Premier League", "71": "Brasileirão Série A", "72": "Brasileirão Série B",
    "140": "La Liga", "135": "Serie A (Itália)", "78": "Bundesliga", "61": "Ligue 1",
}


def _read_jsonl(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _load_all_records() -> dict:
    """So os registros no schema de homologacao atual (record_type presente
    -- ver services/pick_engine/homologation.py::build_homologation_record).
    vip_engine_shadow.jsonl acumulou registros de formatos ANTERIORES
    (rodados antes desta fase, quando o script ainda era so um shadow
    simples motor-vs-IA sem as 6 secoes) -- misturar contaria fixtures
    "processados" sem nenhum dado real de mercados/descarte/score, inflando
    o total silenciosamente."""
    out = {}
    for pick_type, fname in _LOG_FILES.items():
        records = _read_jsonl(os.path.join(_LOGS_DIR, fname))
        out[pick_type] = [r for r in records if "record_type" in r]
    return out


def aggregate(records_by_type: dict) -> dict:
    fixture_records = []
    combo_records = []
    for pick_type, records in records_by_type.items():
        for r in records:
            if r.get("record_type") == "combo":
                combo_records.append(r)
            else:
                fixture_records.append(r)

    total_mercados_avaliados = sum(len(r.get("mercados_avaliados", [])) for r in fixture_records)
    descarte_por_camada = Counter()
    descarte_por_motivo = Counter()
    for r in fixture_records:
        for d in r.get("mercados_descartados", []):
            descarte_por_camada[d.get("camada", "desconhecida")] += 1
            for motivo in d.get("motivo", []):
                # normaliza motivos com numero embutido (ex "amostra insuficiente (3 < 5)")
                base = motivo.split(" (")[0] if motivo else motivo
                descarte_por_motivo[base] += 1

    market_counter = Counter()
    league_counter = Counter()
    score_final_values = []
    confidence_values = []
    fallback_picks = []
    picks_total = 0
    for r in fixture_records:
        league_id = r.get("league_id")
        for p in r.get("picks_aprovados", []):
            picks_total += 1
            market_counter[p.get("market_type", "?")] += 1
            league_counter[str(league_id)] += 1
            if p.get("score_final") is not None:
                score_final_values.append(p["score_final"])
            if p.get("confidence") is not None:
                confidence_values.append(p["confidence"])
            if p.get("chosen_via_fallback"):
                fallback_picks.append({
                    "pick_type": r.get("pick_type"), "fixture_id": r.get("fixture_id"),
                    "home_team": r.get("home_team"), "away_team": r.get("away_team"),
                    "market_type": p.get("market_type"), "value_label": p.get("value_label"),
                    "odd": p.get("odd"), "score_final": p.get("score_final"),
                })

    comparacao_status = Counter()
    mesmo_mercado_count = 0
    comparado_count = 0
    comparisons_detail = []
    for r in fixture_records:
        comp = r.get("comparacao_ia") or {}
        status = comp.get("status", "desconhecido")
        comparacao_status[status] += 1
        if status == "comparado":
            comparado_count += 1
            if comp.get("mesmo_mercado"):
                mesmo_mercado_count += 1
        comparisons_detail.append({
            "pick_type": r.get("pick_type"),
            "fixture_id": r.get("fixture_id"),
            "home_team": r.get("home_team"),
            "away_team": r.get("away_team"),
            "status": status,
            "mesmo_mercado": comp.get("mesmo_mercado"),
            "motor": comp.get("motor"),
            "ia": comp.get("ia"),
        })

    combo_detail = []
    for r in combo_records:
        comp = r.get("comparacao_ia") or {}
        combo_detail.append({
            "pick_type": r.get("pick_type"),
            "combo_encontrado": r.get("combo_encontrado"),
            "pernas": r.get("pernas", []),
            "pernas_em_comum": comp.get("pernas_em_comum"),
            "so_na_ia_count": len(comp.get("so_na_ia", [])),
        })

    por_tipo = {
        pick_type: {
            "fixtures_processados": sum(1 for r in fixture_records if r.get("pick_type") == pick_type),
            "picks_aprovados": sum(len(r.get("picks_aprovados", [])) for r in fixture_records if r.get("pick_type") == pick_type),
        }
        for pick_type in _LOG_FILES
    }

    return {
        "gerado_em": datetime.now().isoformat(),
        "total_fixtures_processados": len(fixture_records),
        "total_mercados_avaliados": total_mercados_avaliados,
        "total_picks_aprovados": picks_total,
        "fallback_picks": fallback_picks,
        "por_tipo": por_tipo,
        "descarte_por_camada": dict(descarte_por_camada),
        "descarte_por_motivo": dict(descarte_por_motivo.most_common(12)),
        "mercados_escolhidos": dict(market_counter.most_common()),
        "distribuicao_liga": {
            _LEAGUE_NAMES.get(lid, f"Liga {lid}"): count for lid, count in league_counter.most_common()
        },
        "score_final_values": score_final_values,
        "confidence_values": confidence_values,
        "comparacao_status": dict(comparacao_status),
        "comparado_count": comparado_count,
        "mesmo_mercado_count": mesmo_mercado_count,
        "comparisons_detail": comparisons_detail,
        "combo_detail": combo_detail,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None, help="Caminho do HTML gerado")
    args = parser.parse_args()

    records = _load_all_records()
    for pick_type, recs in records.items():
        print(f"[HOMOLOG_DASHBOARD] {pick_type}: {len(recs)} registro(s) em {_LOG_FILES[pick_type]}")

    data = aggregate(records)
    print(f"[HOMOLOG_DASHBOARD] {data['total_fixtures_processados']} fixture(s), "
          f"{data['total_mercados_avaliados']} mercado(s) avaliados, "
          f"{data['total_picks_aprovados']} pick(s) aprovados.")

    out_path = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "homologation_dashboard_data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f"[HOMOLOG_DASHBOARD] dados agregados gravados em {os.path.abspath(out_path)}")


if __name__ == "__main__":
    main()
