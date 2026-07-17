"""Helpers compartilhados pelos scripts de homologacao (ai/vip_engine_shadow.py,
ai/dica_homologation.py, ai/multipla_homologation.py, ai/alavancagem_homologation.py
-- ver plano de validacao antes de promover o motor pra producao).

Cada script roda com DB_ENV=dev como ambiente principal (fixtures/odds/
historico/execucao do motor, tudo em DEV -- mesmo padrao de
engine_pipelines/*.py). As funcoes aqui abrem uma conexao PROD SEPARADA e
SO-LEITURA, sob demanda, so pra buscar o pick real que a IA ja salvou --
nunca escreve em PROD, nunca gera pick novo (custaria orcamento de API que
o usuario esta evitando agora)."""
import os
import json
import psycopg2.extras
from utils.db_utils import get_connection
from services import pick_legs_extractor as legs

_TABLE_FETCHERS = {
    "picks_vip": lambda cur: legs.fetch_vip_free_legs(cur, "picks_vip"),
    "picks_free": lambda cur: legs.fetch_vip_free_legs(cur, "picks_free"),
    "picks_multiplas": legs.fetch_multiplas_legs,
    "picks_alavancagem": legs.fetch_alavancagem_legs,
}


def append_jsonl(path: str, record: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def fetch_ai_legs(table: str) -> list:
    """Todas as pernas ja salvas pela IA na tabela indicada, achatadas via
    services/pick_legs_extractor.py (mesmo parsing ja testado por
    scripts/backtest_pick_engine.py e services/picks_ledger_sync_service.py
    -- nao duplica o achatamento de JSON/colunas _1.._3 aqui). Abre e fecha
    uma conexao PROD SO-LEITURA -- nunca escreve."""
    fetcher = _TABLE_FETCHERS.get(table)
    if fetcher is None:
        raise ValueError(f"tabela desconhecida: {table}")
    conn = get_connection("prod")
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return fetcher(cur)
    finally:
        conn.close()


def fetch_ai_pick_for_fixture(fixture_id: int, table: str) -> dict | None:
    """Pick real que a IA salvou pro fixture_id, na tabela indicada -- None
    se nao houver (caso normal pra fixtures novos ainda sem pick, nao uma
    excecao). Quando o mesmo fixture aparece em mais de uma perna salva
    (raro), devolve a mais recente."""
    matches = [leg for leg in fetch_ai_legs(table) if leg.get("fixture_id") == fixture_id]
    if not matches:
        return None
    matches.sort(key=lambda leg: leg.get("created_at") or "", reverse=True)
    return matches[0]
