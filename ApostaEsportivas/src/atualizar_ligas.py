"""Perfis de liga · NAO GERA MAIS NADA (15/10/2026, pedido do usuario).

Este script chamava a IA (Sonnet, com todos os jogos da temporada no prompt)
pra escrever o perfil de cada liga em `league_analysis`, que o gate de IA le'
(services/pick_engine/league_profile_store). O site passou a ter a Leitura da
liga na aba Ligas, gerada 1x por liga por dia com modelo barato, e o usuario
pediu UMA geracao so': "fazer 1 coisa so' pra nao ficar duas e gastar errado".

Quem escreve `league_analysis` agora e' website/backend/liga_ia.py, com o
texto da liga sem citar time, na mesma tabela e chave. Este script so' garante
que a tabela existe e mostra o que ha' nela · e NAO a limpa mais: o TRUNCATE
apagaria os perfis que o site gravou.
"""
from services.league_analysis_service import criar_tabela
from utils.db_utils import get_connection


class AILeagueUpdateMain:

    def clear_league_analysis(self):
        """Mantida pro `main.py ligas`; so' cria a tabela, nao limpa."""
        conn = get_connection()
        cur = conn.cursor()
        criar_tabela(cur)
        conn.commit()
        cur.close()
        conn.close()

    def generate_league_profiles(self):
        print("[AI_LEAGUE_MAIN] O perfil de liga agora vem da Leitura da liga do site "
              "(aba Ligas, 1x por liga por dia). Nada a gerar aqui.")
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT league_name, season, updated_at FROM league_analysis
             ORDER BY updated_at DESC NULLS LAST
        """)
        for nome, season, quando in cur.fetchall():
            print(f"[AI_LEAGUE_MAIN] {nome} ({season}) · atualizado em {quando}")
        cur.close()
        conn.close()


if __name__ == "__main__":
    ai = AILeagueUpdateMain()
    ai.clear_league_analysis()
    ai.generate_league_profiles()
