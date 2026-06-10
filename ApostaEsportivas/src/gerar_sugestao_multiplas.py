import sys
sys.stdout.reconfigure(encoding="utf-8")

from ai.multipla_pipeline import run_multipla_pipeline
import json

print("INICIANDO GERACAO DE MULTIPLAS (IA)")


class MultiplaMain:

    def __init__(self):
        print("🤖 IA de múltiplas inicializada...")

    def run(self):
        print("\n=====================================")
        print("🔍 Gerando múltiplas com IA...")
        print("=====================================\n")

        resultado = run_multipla_pipeline()

        if resultado is None:
            print("⚠️ Nenhuma múltipla criada hoje pela IA.")
        else:
            print("✅ Múltiplas criadas com sucesso!")
            print(json.dumps(resultado, indent=2, ensure_ascii=False))

        print("\n🏁 Processo finalizado.")


if __name__ == "__main__":
    MultiplaMain().run()
