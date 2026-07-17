"""
main.py · Orquestrador único do ApostaEsportivas (sem website).

Uso:
  python main.py dados            # Atualiza jogos, stats e classificação
  python main.py dados full       # Temporada completa (liga nova)
  python main.py odds             # Coleta odds pré-jogo
  python main.py vip              # Gera picks VIP do dia
  python main.py dica             # Gera pick free (Dica do Dia)
  python main.py multiplas        # Gera múltipla do dia
  python main.py alavancagem      # Gera pick de alavancagem
  python main.py resultados       # Atualiza resultados de todos os picks
  python main.py ligas            # Atualiza perfis de ligas (IA)
  python main.py tudo             # Pipeline completo: dados → odds → picks → resultados
  python main.py tudo full        # Pipeline completo com coleta total de stats
  python main.py setup            # Só roda as migrações do banco
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONUNBUFFERED", "1")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

from utils.db_utils import get_connection


# ─────────────────────────────────────────────────────────────
# MIGRAÇÕES
# ─────────────────────────────────────────────────────────────
def run_migrations():
    """Aplica ALTER TABLE seguros (IF NOT EXISTS) para colunas novas."""
    migrations = [
        "ALTER TABLE picks_vip   ADD COLUMN IF NOT EXISTS market_id INTEGER;",
        "ALTER TABLE picks_free  ADD COLUMN IF NOT EXISTS market_id INTEGER;",
        "ALTER TABLE picks_vip   ADD COLUMN IF NOT EXISTS stake_units INTEGER;",
        "ALTER TABLE picks_free  ADD COLUMN IF NOT EXISTS stake_pct NUMERIC;",
        "ALTER TABLE picks_free  ADD COLUMN IF NOT EXISTS stake_units INTEGER;",
    ]
    conn = get_connection()
    cur = conn.cursor()
    for sql in migrations:
        try:
            cur.execute(sql)
            print(f"[MIGRATE] OK: {sql.strip()}")
        except Exception as e:
            print(f"[MIGRATE] ERRO: {e}")
    conn.commit()
    cur.close()
    conn.close()
    print("[MIGRATE] Migrações concluídas.\n")


# ─────────────────────────────────────────────────────────────
# COMANDOS
# ─────────────────────────────────────────────────────────────
def cmd_dados(mode: str = "fast"):
    from atualizar_jogos import DataCollectorMain
    c = DataCollectorMain()
    if mode == "full":
        c.run_stage_0()
        c.run_stage_1()
        c.run_stage_2()
        c.run_stage_3()
        c.run_stage_4(mode="full", wc_mode="full")
        c.run_stage_5(mode="full")
    else:
        c.run_all()


def cmd_odds():
    from capturar_odds import OddsMain
    OddsMain().run()


def cmd_vip():
    # Motor deterministico (pick_engine) -- decisao explicita do usuario
    # (2026-07-17) de cortar a geracao de picks pra IA em produção tambem,
    # nao so em dev. Pipelines de IA (gerar_sugestao_vip.py) ficam no
    # disco, sem uso, pra reverter rapido se precisar -- ja aconteceu
    # antes (ver memoria de projeto).
    from engine_pipelines.vip_pipeline import run_vip_engine
    run_vip_engine()


def cmd_dica():
    from engine_pipelines.dica_pipeline import run_dica_engine
    run_dica_engine()


def cmd_multiplas():
    from engine_pipelines.multipla_pipeline import run_multipla_engine
    run_multipla_engine()


def cmd_alavancagem():
    from engine_pipelines.alavancagem_pipeline import run_alavancagem_engine
    run_alavancagem_engine()


def cmd_resultados():
    from atualizar_resultados_sugestoes import AIUpdateResultsMain
    AIUpdateResultsMain().update_all_results()


def cmd_shadow():
    """Modo sombra do motor de picks (Fase 3): roda pick_engine em paralelo
    aos picks já salvos pela IA hoje, só para registrar a comparação em
    logs/shadow_consensus.jsonl. Nunca escreve em tabela de produção."""
    from shadow_consensus import run_shadow_comparison
    run_shadow_comparison()


def cmd_ligas():
    from atualizar_ligas import AILeagueUpdateMain
    ai = AILeagueUpdateMain()
    ai.clear_league_analysis()
    ai.generate_league_profiles()


def cmd_tudo(mode: str = "fast"):
    """Pipeline completo diário na ordem correta."""
    t0 = time.perf_counter()
    print("\n" + "="*60)
    print("PIPELINE COMPLETO · ApostaEsportivas")
    print("="*60 + "\n")

    print("─── [1/7] DADOS ────────────────────────────────────────")
    cmd_dados(mode=mode)

    print("\n─── [2/7] ODDS ─────────────────────────────────────────")
    cmd_odds()

    print("\n─── [3/7] PICKS VIP ────────────────────────────────────")
    cmd_vip()

    print("\n─── [4/7] DICA DO DIA ──────────────────────────────────")
    cmd_dica()

    print("\n─── [5/7] MÚLTIPLA ─────────────────────────────────────")
    cmd_multiplas()

    print("\n─── [6/7] ALAVANCAGEM ──────────────────────────────────")
    cmd_alavancagem()

    print("\n─── [7/7] RESULTADOS ───────────────────────────────────")
    cmd_resultados()

    total = time.perf_counter() - t0
    print(f"\n{'='*60}")
    print(f"PIPELINE CONCLUÍDO em {total:.1f}s")
    print("="*60 + "\n")


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────
HELP = """
Comandos disponíveis:
  dados [full]     Atualiza jogos, stats, classificação
  odds             Coleta odds pré-jogo
  vip              Gera picks VIP do dia
  dica             Gera pick free (Dica do Dia)
  multiplas        Gera múltipla do dia
  alavancagem      Gera pick de alavancagem
  resultados       Atualiza resultados de todos os picks
  ligas            Atualiza perfis de ligas (IA)
  tudo [full]      Pipeline completo na ordem correta
  setup            Roda apenas as migrações do banco
  shadow           Motor de picks em modo sombra (só log, não afeta picks)
"""

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(HELP)
        sys.exit(0)

    cmd = args[0].lower()
    extra = args[1].lower() if len(args) > 1 else ""

    run_migrations()

    if cmd == "setup":
        pass  # migrações já rodaram acima

    elif cmd == "dados":
        cmd_dados(mode="full" if extra == "full" else "fast")

    elif cmd == "odds":
        cmd_odds()

    elif cmd == "vip":
        cmd_vip()

    elif cmd == "dica":
        cmd_dica()

    elif cmd == "multiplas":
        cmd_multiplas()

    elif cmd == "alavancagem":
        cmd_alavancagem()

    elif cmd == "resultados":
        cmd_resultados()

    elif cmd == "shadow":
        cmd_shadow()

    elif cmd == "ligas":
        cmd_ligas()

    elif cmd == "tudo":
        cmd_tudo(mode="full" if extra == "full" else "fast")

    else:
        print(f"Comando desconhecido: '{cmd}'\n{HELP}")
        sys.exit(1)
