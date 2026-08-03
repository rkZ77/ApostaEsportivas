"""
Wrapper dev: mapeia DB_HOST_DEV -> DB_HOST etc. e oferece menu interativo
(espelha run_prod.py). Com DB_ENV=dev, main.py::cmd_vip/cmd_dica/
cmd_multiplas/cmd_alavancagem já roteiam sozinhos pro motor determinístico
(services/pick_engine/) em vez de IA -- este wrapper só delega pra lá,
sem duplicar lógica de dispatch.

Uso: python run_dev.py [comando]
     python run_dev.py          <- menu interativo
"""
import os
import sys
from dotenv import load_dotenv, find_dotenv

_dotenv_path = find_dotenv()
load_dotenv(_dotenv_path)
_env_dir = os.path.dirname(_dotenv_path) if _dotenv_path else "."
load_dotenv(os.path.join(_env_dir, ".env.dev"), override=False)
load_dotenv(os.path.join(_env_dir, ".env.prod"), override=False)

# Mapeia sufixo _DEV -> sem sufixo (paridade com run_prod.py, mesmo que
# hoje pareça redundante -- get_connection() já lê DB_ENV diretamente)
for key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASS", "DB_SSLMODE"):
    dev_val = os.getenv(f"{key}_DEV")
    if dev_val:
        os.environ[key] = dev_val

os.environ["DB_ENV"] = "dev"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main as main_module  # noqa: E402  (import após setar DB_ENV)

OPCOES = {
    "1":  ("Atualizar jogos (completo)",       "dados"),
    "2":  ("Capturar odds",                    "odds"),
    "3":  ("Gerar picks VIP (motor)",          "vip"),
    "4":  ("Gerar pick Free (motor)",          "dica"),
    "5":  ("Gerar múltipla (motor)",           "multiplas"),
    "6":  ("Gerar alavancagem (motor)",        "alavancagem"),
    # Paridade com run_prod.py: faltas/goleiros rodavam so' dentro de "tudo".
    "7":  ("Gerar picks de faltas (motor)",    "faltas"),
    "8":  ("Gerar defesas de goleiro (motor)", "goleiros"),
    "9":  ("Atualizar resultados",             "resultados"),
    "10": ("Tudo: jogos + odds + picks",       "tudo"),
    "11": ("Modo sombra (log IA vs motor)",    "shadow"),
    "12": ("Estatistica de jogador (API)",     "player_stats"),
}


def menu():
    print("\n========================================")
    print("         APOSTA ESPORTIVAS · DEV        ")
    print("========================================")
    for k, (label, _) in OPCOES.items():
        print(f"  [{k}] {label}")
    print("  [0] Sair")
    print("----------------------------------------")
    return input("Escolha: ").strip()


def run(cmd: str):
    # Mesma correcao de run_prod.py: main.py so' migra dentro do __main__ dele,
    # e aqui ele entra como modulo importado. Idempotente (IF NOT EXISTS).
    main_module.run_migrations()

    if cmd == "dados":
        main_module.cmd_dados()
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
    elif cmd == "faltas":
        main_module.cmd_faltas()
    elif cmd == "goleiros":
        main_module.cmd_goleiros()
    elif cmd == "resultados":
        main_module.cmd_resultados()
    elif cmd == "shadow":
        main_module.cmd_shadow()
    elif cmd == "tudo":
        main_module.cmd_tudo()
    elif cmd == "player_stats":
        main_module.cmd_player_stats()
    else:
        print(f"Comando desconhecido: '{cmd}'")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None

    if arg:
        run(arg)
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
