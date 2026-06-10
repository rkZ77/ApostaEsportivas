"""
Entry point: gera o pick de alavancagem do dia.
Uso: python gerar_alavancagem.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

from ai.alavancagem_pipeline import run_alavancagem_pipeline

if __name__ == "__main__":
    result = run_alavancagem_pipeline()
    if result:
        print("✅ Pick de alavancagem gerado com sucesso.")
    else:
        print("⚠️  Nenhum pick gerado (no_bet, já existe ou sem jogos).")
