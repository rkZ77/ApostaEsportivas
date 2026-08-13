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

# Menu e dispatch saem do registro COMANDOS de main.py -- ver o comentario
# grande la, que lista o que cada copia dessa lista tinha esquecido enquanto
# elas eram mantidas a mao. Aqui sobra escolher o ambiente ("prod") e cuidar
# das migracoes. Ficam de fora os comandos que nao declaram "prod": `live`
# (recusa rodar sem DB_ENV=dev) e `shadow` (compara motor vs IA numa base de
# homologacao) -- oferecer no menu de prod seria um botao que so sabe recusar.
COMANDOS = [c for c in main_module.COMANDOS if "prod" in c.ambientes]
OPCOES = {str(i): c for i, c in enumerate(COMANDOS, start=1)}


def menu():
    print("\n========================================")
    print("         APOSTA ESPORTIVAS · PROD       ")
    print("========================================")
    for k, comando in OPCOES.items():
        print(f"  [{k}] {comando.label}")
    print("  [0] Sair")
    print("----------------------------------------")
    return input("Escolha: ").strip()


def run(cmd: str, *extra_args):
    comando = main_module.COMANDOS_POR_NOME.get(cmd)
    if comando is None or "prod" not in comando.ambientes:
        print(f"Comando desconhecido em prod: '{cmd}'")
        return

    # main.py so' roda as migracoes dentro do proprio __main__, e este wrapper
    # importa main como modulo -- ou seja, rodar por aqui nunca as aplicava.
    # Ja' quebrou o motor em prod em silencio depois de um merge que adicionou
    # coluna nova (engine_debug, 2026-07-23): a coluna nao existia e todo
    # INSERT de pick falhava. Sao ALTER/CREATE ... IF NOT EXISTS, idempotentes
    # e baratos, entao rodar sempre e' seguro.
    if comando.migrar:
        main_module.run_migrations()

    comando.executar(*extra_args)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None

    if arg:
        # "dados full" / "tudo full" / "player_stats 80" -- os mesmos extras que
        # main.py aceita, repassados crus pro adaptador do comando.
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
