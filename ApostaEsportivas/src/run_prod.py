"""
Wrapper prod: mapeia DB_HOST_PROD -> DB_HOST etc. e oferece menu interativo
(espelha run_dev.py). Com DB_ENV=prod, main.py::cmd_vip/cmd_dica/
cmd_multiplas/cmd_alavancagem já roteiam sozinhos pro motor determinístico
(engine_pipelines/ + services/pick_engine/) -- este wrapper só delega pra lá,
sem duplicar lógica de dispatch.

Até 2026-07-29 este arquivo tinha o próprio mapa de comandos, e ele ficou
para trás no corte de IA em produção (2026-07-17): as opções "Gerar picks
VIP", "Free", "múltipla" e "alavancagem" ainda importavam
gerar_sugestao_vip.py / ai/*.py, ou seja, chamavam a Anthropic de verdade
(custo real) em vez do motor. Mesmo bug que já tinha sido corrigido em
routers/admin.py::_PIPELINE_SCRIPTS. Delegar pro main.py evita que aconteça
uma terceira vez.

Uso: python run_prod.py [comando]
     python run_prod.py          <- menu interativo
"""
import os
import sys
from dotenv import load_dotenv, find_dotenv

_dotenv_path = find_dotenv()
load_dotenv(_dotenv_path)
_env_dir = os.path.dirname(_dotenv_path) if _dotenv_path else "."
load_dotenv(os.path.join(_env_dir, ".env.dev"), override=False)
load_dotenv(os.path.join(_env_dir, ".env.prod"), override=False)

# Mapeia sufixo _PROD -> sem sufixo (para collectors legados)
for key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASS", "DB_SSLMODE"):
    prod_val = os.getenv(f"{key}_PROD")
    if prod_val:
        os.environ[key] = prod_val

os.environ["DB_ENV"] = "prod"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main as main_module  # noqa: E402  (import após setar DB_ENV)

OPCOES = {
    "1": ("Atualizar jogos (completo)",       "dados"),
    "2": ("Capturar odds",                    "odds"),
    "3": ("Gerar picks VIP (motor)",          "vip"),
    "4": ("Gerar pick Free (motor)",          "dica"),
    "5": ("Gerar múltipla (motor)",           "multiplas"),
    "6": ("Gerar alavancagem (motor)",        "alavancagem"),
    "7": ("Atualizar resultados (VIP+Free+Mult+Alav)", "resultados"),
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


def run(cmd: str, mode: str = "fast"):
    if cmd == "dados":
        main_module.cmd_dados(mode=mode)
    elif cmd == "odds":
        main_module.cmd_odds()
    elif cmd == "vip":
        main_module.cmd_vip()
    elif cmd == "dica":
        main_module.cmd_dica()
    elif cmd == "multiplas":
        main_module.cmd_multiplas()
    elif cmd == "alavancagem":
        main_module.cmd_alavancagem()
    elif cmd == "resultados":
        main_module.cmd_resultados()
    elif cmd == "tudo":
        main_module.cmd_tudo(mode=mode)
    else:
        print(f"Comando desconhecido: '{cmd}'")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    # "dados full" / "tudo full" -- mesmo extra que main.py aceita
    extra = sys.argv[2].lower() if len(sys.argv) > 2 else ""

    if arg:
        run(arg, mode="full" if extra == "full" else "fast")
    else:
        while True:
            escolha = menu()
            if escolha == "0":
                print("Saindo...")
                break
            elif escolha in OPCOES:
                _, cmd_name = OPCOES[escolha]
                print(f"\n>>> Rodando: {OPCOES[escolha][0]}...\n")
                run(cmd_name)
                input("\nPressione Enter para voltar ao menu...")
            else:
                print("Opção inválida.")
