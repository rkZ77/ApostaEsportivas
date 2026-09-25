"""limpar_reasoning_com_amostra.py · tira o dicionario de dentro do texto que o
assinante le'.

SEM `--aplicar` NAO ESCREVE NADA: o padrao e' ensaio, com amostra do antes e do
depois.

Uso:
  DB_ENV=prod python src/scripts/limpar_reasoning_com_amostra.py
  DB_ENV=prod python src/scripts/limpar_reasoning_com_amostra.py --aplicar

O QUE ACONTECEU
---------------
De 27/08 a 24/09/2026, cinco pipelines montaram o pick como
`{**candidato, "amostra": amostra.build(...)}` -- trocando o CONTADOR de jogos
pelo BLOCO da amostra (services/engine_audit/amostra.py). `explanation.py`
escrevia a primeira frase da analise com esse valor:

    Taxa real ponderada de 60.1% em {'max_exibidos': 10, 'mandante': {...}} jogos (RICO)

Sao 8 mil caracteres de JSON num campo que o assinante le' na tela. Ninguem viu
porque nada compara texto de reasoning -- o defeito so' apareceu quando a
ressalva de amostra passou a COMPARAR o valor com um numero e o pipeline da Free
morreu com TypeError em producao.

O CODIGO JA' ESTA' CORRIGIDO (o bloco mora em `amostra_exibida`, e a explicacao
nunca publica o que nao e' numero). Isto aqui e' a limpeza do que ja' foi
gravado.

POR QUE A CONTAGEM NAO E' RESTAURADA
------------------------------------
O numero verdadeiro de jogos daquele candidato nao existe em lugar nenhum: o
texto foi escrito a partir do bloco, e o retrato do candidato so' passou a
guardar `amostra` hoje. `jogos_lidos` do bloco e' OUTRA contagem (historico lido
por time, antes do filtro de mando e do descarte por familia), entao usa-lo aqui
seria inventar um numero com cara de medido -- exatamente o que a explicacao
existe pra nao fazer.

Entao a frase perde o trecho "em N jogos" e fica:

    Taxa real ponderada de 60.1% (RICO)

Mais pobre e verdadeira, que e' o mesmo caminho que o codigo novo segue quando
nao tem numero.
"""
import argparse
import os
import sys

# O `src/` do motor NUNCA na frente do sys.path (2026-09-04).
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db_utils import get_connection  # noqa: E402

#: Onde o reasoning e' gravado com a frase da explicacao generica.
TABELAS = ("picks_vip", "picks_free", "picks_bingo", "picks_faltas", "picks_boost",
           "picks_multiplas", "picks_alavancagem")

MARCA = " em {"
FIM = "} jogos"


def limpar(texto: str) -> str | None:
    """O texto sem NENHUM trecho "em {dicionario} jogos", ou None se nao ha' o
    que limpar.

    TODAS as ocorrencias, nao a primeira: o reasoning de um BILHETE tem uma
    frase por perna, entao bingo e multipla carregam o bloco tres ou quatro
    vezes. Limpar so' a primeira deixava 10 mil caracteres de JSON no lugar de
    17 mil -- pego no ensaio contra PROD, no bingo 9.
    """
    limpo = texto
    while True:
        passo = _limpar_uma(limpo)
        if passo is None:
            break
        limpo = passo
    return None if limpo == texto else limpo


def _limpar_uma(texto: str) -> str | None:
    """A primeira ocorrencia, ou None.

    Acha a chave de fechamento CONTANDO chaves, e nao pelo primeiro `}`: o bloco
    tem dicionarios dentro de dicionarios, e um `.replace` por regex guloso
    comeria o resto da frase.
    """
    inicio = texto.find(MARCA)
    if inicio == -1:
        return None
    nivel = 0
    i = inicio + len(MARCA) - 1  # no `{`
    while i < len(texto):
        if texto[i] == "{":
            nivel += 1
        elif texto[i] == "}":
            nivel -= 1
            if nivel == 0:
                break
        i += 1
    else:
        return None
    if not texto.startswith(FIM, i):
        # Fechou as chaves mas nao vem " jogos" depois: nao e' esta frase, e
        # mexer as cegas num texto que o usuario le' e' pior que nao mexer.
        return None
    return texto[:inicio] + texto[i + len(FIM):]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true", help="grava (UPDATE)")
    args = ap.parse_args()

    conn = get_connection()
    try:
        cur = conn.cursor()
        total_afetados = 0
        for tabela in TABELAS:
            # A coluna, e nao so' a tabela: `picks_alavancagem` existe e nao
            # tem `reasoning` (o caminho dela guarda a explicacao por perna).
            cur.execute("""SELECT COUNT(*) FROM information_schema.columns
                            WHERE table_schema = 'public' AND table_name = %s
                              AND column_name = 'reasoning'""", (tabela,))
            if not cur.fetchone()[0]:
                continue
            cur.execute(f"""SELECT id, reasoning FROM {tabela}
                             WHERE reasoning LIKE %s""", ("%" + MARCA + "%",))
            linhas = cur.fetchall()
            alvos = []
            for pid, texto in linhas:
                limpo = limpar(texto or "")
                if limpo is not None and limpo != texto:
                    alvos.append((pid, texto, limpo))
            if not alvos:
                continue
            total_afetados += len(alvos)
            print(f"\n== {tabela}: {len(alvos)} pick(s) ==")
            pid, antes, depois = alvos[0]
            print(f"  exemplo (id {pid}), {len(antes)} -> {len(depois)} caracteres")
            i = max(0, antes.find("Taxa real"))
            print(f"    ANTES : {antes[i:i + 110]}...")
            j = max(0, depois.find("Taxa real"))
            print(f"    DEPOIS: {depois[j:j + 110]}")
            if args.aplicar:
                for pid, _antes, depois in alvos:
                    cur.execute(f"UPDATE {tabela} SET reasoning = %s WHERE id = %s",
                                (depois, pid))
                conn.commit()
                print(f"  {len(alvos)} linha(s) gravada(s).")

        if not total_afetados:
            print("Nenhum reasoning com dicionario dentro. Nada a fazer.")
        elif not args.aplicar:
            print(f"\n{total_afetados} pick(s) no total. Ensaio apenas -- rode com "
                  f"--aplicar pra gravar.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
