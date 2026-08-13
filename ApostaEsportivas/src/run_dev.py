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

# Menu e dispatch saem do registro COMANDOS de main.py -- ver o comentario
# grande la. Este wrapper so' escolhe o ambiente ("dev") e cuida das
# migracoes; a lista de comandos nao e' mais mantida aqui.
COMANDOS = [c for c in main_module.COMANDOS if "dev" in c.ambientes]
OPCOES = {str(i): c for i, c in enumerate(COMANDOS, start=1)}


def menu():
    print("\n========================================")
    print("         APOSTA ESPORTIVAS · DEV        ")
    print("========================================")
    for k, comando in OPCOES.items():
        print(f"  [{k}] {comando.label}")
    print("  [0] Sair")
    print("----------------------------------------")
    return input("Escolha: ").strip()


def run(cmd: str, *extra_args):
    comando = main_module.COMANDOS_POR_NOME.get(cmd)
    if comando is None or "dev" not in comando.ambientes:
        print(f"Comando desconhecido em dev: '{cmd}'")
        return

    # Mesma correcao de run_prod.py: main.py so' migra dentro do __main__ dele,
    # e aqui ele entra como modulo importado. Idempotente (IF NOT EXISTS).
    # `live` declara migrar=False e provisiona o proprio esquema.
    if comando.migrar:
        main_module.run_migrations()

    comando.executar(*extra_args)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None

    if arg:
        # Extras crus: "dados full", "live fixture 123456", "player_stats 80".
        run(arg, *sys.argv[2:])
    else:
        while True:
            escolha = menu()
            if escolha == "0":
                print("Saindo...")
                break
            elif escolha in OPCOES:
                comando = OPCOES[escolha]
                print(f"\n>>> Rodando: {comando.label}...\n")
                run(comando.nome)
                input("\nPressione Enter para voltar ao menu...")
            else:
                print("Opção inválida.")
