"""
checar_mercado_tiros_de_meta.py · o mercado de TIRO DE META existe pra nos?

SOMENTE LEITURA.

Uso:
  DB_ENV=prod python src/scripts/checar_mercado_tiros_de_meta.py

POR QUE ESTE CHECK VEM ANTES DE QUALQUER MODELO
-----------------------------------------------
Um mercado novo so' e' viavel quando TRES coisas existem, e as tres foram
verificadas nesta ordem quando faltas e defesas nasceram (2026-08-01):

    1. a casa OFERECE a odd            <- este script responde
    2. existe HISTORICO pra estimar    <- ver o aviso no fim da saida
    3. existe contagem pra LIQUIDAR    <- idem

Tiro de meta ja' falha o item 3 na leitura do codigo: a folha de
/fixtures/statistics da API-Football nao tem esse contador. As linhas que ela
entrega estao explicitas em collectors/match_statistics_sync_service._save_stats
(escanteios, cartoes, chutes, defesas, faltas, impedimentos, posse, passes), e
nenhuma delas e' tiro de meta. Sem coluna em match_statistics nao ha' media
historica pra prever nem numero pra liquidar -- o pick ficaria com result NULL
pra sempre, que e' exatamente o problema que faltas teve antes de 08/08.

Este script existe pra responder o item 1 com DADO em vez de suposicao, e pra
que a resposta fique registrada: se as casas nem oferecem, a conversa acaba sem
custo nenhum. Se oferecem, o bloqueio passa a ser achar fonte de contagem, e ai'
a decisao e' de produto, nao de codigo.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYTHONUNBUFFERED", "1")

from utils.db_utils import get_connection

# "Goal Kicks" e' como a API-Football nomearia; "tiro de meta" cobre o campo em
# portugues de bet_markets_map. Padrao amplo de proposito: e' melhor olhar
# algumas linhas irrelevantes do que concluir "nao existe" por causa de grafia.
PADROES = ("%goal kick%", "%goalkick%", "%tiro de meta%")


def _consultar(cur, titulo, sql, explicacao):
    print("\n" + "-" * 74)
    print(titulo)
    print("-" * 74)
    try:
        cur.execute(sql, (list(PADROES),))
    except Exception as e:
        print(f"[indisponivel] {e}")
        cur.connection.rollback()
        return None
    linhas = cur.fetchall()
    if not linhas:
        print("nenhuma ocorrencia.")
    else:
        for linha in linhas:
            print("  " + " | ".join("" if c is None else str(c) for c in linha))
    print(f"\n({explicacao})")
    return linhas


def run():
    conn = get_connection()
    cur = conn.cursor()
    try:
        catalogo = _consultar(
            cur,
            "1. CATALOGO DA API (bet_markets_map)",
            # Os dois nomes concatenados num campo so' pra o filtro caber num
            # unico parametro -- procurar em ingles OU portugues sem duplicar a
            # lista de padroes.
            """
            SELECT bet_id, market_en, market_pt
            FROM bet_markets_map
            WHERE (COALESCE(market_en, '') || ' ' || COALESCE(market_pt, ''))
                  ILIKE ANY(%s)
            ORDER BY bet_id
            """,
            "prova que o mercado EXISTE no catalogo da API, nao que alguma casa"
            " brasileira o oferece nas ligas que cobrimos",
        )

        ofertado = _consultar(
            cur,
            "2. O QUE AS CASAS REALMENTE PUBLICARAM (odds_markets)",
            """
            SELECT bet_id, bet_name, COUNT(DISTINCT fixture_id) AS jogos
            FROM odds_markets
            WHERE bet_name ILIKE ANY(%s)
            GROUP BY bet_id, bet_name
            ORDER BY jogos DESC
            """,
            "esta e' a evidencia FORTE: e' o que Bet365/Betano mandaram de fato"
            " nos jogos ja' coletados",
        )

        _consultar(
            cur,
            "3. MERCADOS VISTOS E AINDA NAO CLASSIFICADOS (pick_engine_unclassified_markets)",
            """
            SELECT bet_name, times_seen, last_seen
            FROM pick_engine_unclassified_markets
            WHERE bet_name ILIKE ANY(%s)
            ORDER BY times_seen DESC
            """,
            "foi por aqui que 'Fouls' e 'Goalkeeper Saves' foram descobertos em"
            " 2026-08-01",
        )

        print("\n" + "=" * 74)
        print("VEREDITO")
        print("=" * 74)
        if not ofertado:
            print("Nenhuma casa publicou mercado de tiro de meta nos jogos coletados.")
            print("Sem oferta, nao ha' o que modelar. Fim da linha, custo zero.")
            if catalogo:
                print("\nO catalogo da API conhece o mercado (secao 1), mas catalogo"
                      "\nnao e' oferta -- mesma distincao que ficou registrada em"
                      "\n2026-08-01 pros mercados de falta e defesa.")
        else:
            print("HA' OFERTA. O bloqueio passa a ser o item 3: nao existe contagem"
                  "\nde tiro de meta em match_statistics, porque a API-Football nao"
                  "\nentrega esse numero na folha de estatistica.")
            print("\nSem uma fonte de contagem, um pick desse mercado nao pode ser"
                  "\nliquidado -- ficaria com result NULL pra sempre. Antes de"
                  "\nescrever modelo, a pergunta e' de onde viria o numero final.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
