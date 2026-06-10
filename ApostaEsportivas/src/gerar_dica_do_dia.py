import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from ai.dica_do_dia_pipeline import run_dica_pipeline

if __name__ == "__main__":
    result = run_dica_pipeline()
    if result is None:
        print("[MAIN] Nenhuma dica gerada hoje.")
    else:
        print(f"[MAIN] Dica do dia: {result.get('home_team')} x {result.get('away_team')} | {result.get('market')} {result.get('line')} | odd {result.get('odd')}")
