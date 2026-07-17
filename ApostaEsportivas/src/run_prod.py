"""
Wrapper prod: mapeia DB_HOST_PROD -> DB_HOST etc. e oferece menu interativo.
Uso: python run_prod.py [comando]
     python run_prod.py          <- menu interativo
"""
import os
import sys
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# Mapeia sufixo _PROD -> sem sufixo (para collectors legados)
for key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASS", "DB_SSLMODE"):
    prod_val = os.getenv(f"{key}_PROD")
    if prod_val:
        os.environ[key] = prod_val

os.environ["DB_ENV"] = "prod"

OPCOES = {
    "1": ("Atualizar jogos (completo)",       "atualizar_jogos"),
    "2": ("Capturar odds",                    "capturar_odds"),
    "3": ("Gerar picks VIP",                  "gerar_vip"),
    "4": ("Gerar pick Free (Dica do Dia)",    "gerar_free"),
    "5": ("Gerar múltipla",                   "gerar_multipla"),
    "6": ("Gerar alavancagem",                "gerar_alavancagem"),
    "7": ("Atualizar resultados (VIP+Free+Mult+Alav)", "atualizar_resultados"),
    "8": ("Tudo: jogos + odds + picks",       "tudo"),
}


def menu():
    print("\n========================================")
    print("         APOSTA ESPORTIVAS · PROD       ")
    print("========================================")
    for k, (label, _) in OPCOES.items():
        print(f"  [{k}] {label}")
    print("  [0] Sair")
    print("----------------------------------------")
    return input("Escolha: ").strip()


def run(script, args=None):
    args = args or []

    if script == "atualizar_jogos":
        from atualizar_jogos import DataCollectorMain
        collector = DataCollectorMain()
        if not args:
            collector.run_all()
        else:
            sys.argv = ["atualizar_jogos.py"] + args
            import importlib.util, pathlib
            spec = importlib.util.spec_from_file_location(
                "atualizar_jogos",
                pathlib.Path(__file__).parent / "atualizar_jogos.py"
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

    elif script == "capturar_odds":
        from capturar_odds import OddsMain
        OddsMain().run()

    elif script == "gerar_vip":
        from gerar_sugestao_vip import AIVipSuggestionsMain
        AIVipSuggestionsMain().generate_vip_suggestions()

    elif script == "gerar_free":
        from ai.dica_do_dia_pipeline import run_dica_pipeline
        result = run_dica_pipeline()
        if result is None:
            print("[MAIN] Nenhuma dica gerada hoje.")
        else:
            print(f"[MAIN] Dica: {result.get('home_team')} x {result.get('away_team')} | {result.get('market')} {result.get('line')} | odd {result.get('odd')}")

    elif script == "gerar_multipla":
        from gerar_sugestao_multiplas import MultiplaMain
        MultiplaMain().run()

    elif script == "gerar_alavancagem":
        from ai.alavancagem_pipeline import run_alavancagem_pipeline
        result = run_alavancagem_pipeline()
        if result:
            print("✅ Pick de alavancagem gerado com sucesso.")

    elif script == "atualizar_resultados":
        from atualizar_resultados_sugestoes import AIUpdateResultsMain
        AIUpdateResultsMain().update_all_results()

    elif script == "tudo":
        print("\n>>> Atualizando jogos...")
        run("atualizar_jogos")
        print("\n>>> Capturando odds...")
        run("capturar_odds")
        print("\n>>> Gerando picks VIP...")
        run("gerar_vip")
        print("\n>>> Gerando pick Free...")
        run("gerar_free")
        print("\n>>> Gerando múltipla...")
        run("gerar_multipla")
        print("\n>>> Gerando alavancagem...")
        run("gerar_alavancagem")
        print("\n✅ Pipeline completo finalizado!")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else None
    extra = sys.argv[2:]

    if cmd:
        run(cmd, extra)
    else:
        while True:
            escolha = menu()
            if escolha == "0":
                print("Saindo...")
                break
            elif escolha in OPCOES:
                _, script_name = OPCOES[escolha]
                print(f"\n>>> Rodando: {OPCOES[escolha][0]}...\n")
                run(script_name)
                input("\nPressione Enter para voltar ao menu...")
            else:
                print("Opção inválida.")
