import os
import json
from anthropic import Anthropic
from utils.db_utils import get_connection
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# Quanto o parecer da liga pode ocupar. E' um texto curto e de formato fixo
# (ver LEAGUE_ANALYSIS_PROMPT), entao 1500 sobra -- e max_tokens no Anthropic e'
# obrigatorio, diferente do chat.completions que estava aqui antes.
MAX_TOKENS = 1500


class LeagueAnalysisService:

    def __init__(self):
        # Era OpenAI() recebendo AI_MODEL_NAME, que no .env vale
        # "claude-sonnet-4-6": a OpenAI nao conhece esse ID, entao TODA geracao
        # de perfil de liga estourava (atualizar_ligas.py e main.py::cmd). A
        # mesma variavel ja' alimentava clientes Anthropic no resto do projeto
        # (ai/dica_do_dia_pipeline.py, ai/multipla_pipeline.py) -- quem estava
        # fora do padrao era o cliente daqui, nao o valor da variavel.
        # Corrigido em 2026-08-07 trocando o cliente, nao o env.
        self.client = Anthropic()
        self.model = os.getenv("AI_MODEL_NAME")

        self.LEAGUE_ANALYSIS_PROMPT = """
Você é um analista profissional especializado em padrões estatísticos de competições.
Sua tarefa é produzir uma descrição objetiva do COMPORTAMENTO GERAL da liga na season, usando exclusivamente os dados fornecidos no JSON.

REGRAS:
- Não citar times, países, continentes ou qualquer identificação geográfica.
- Não recomendar apostas.
- Não usar linguagem imperativa.
- Não inventar dados.
- Produzir análise neutra baseada apenas nos indicadores.

INTERPRETAÇÃO:
Analise exclusivamente:
- médias de gols
- BTTS
- cartões
- escanteios
- volatilidade

FORMATO OBRIGATÓRIO:

• <NOME DA LIGA> (<QUANTIDADE DE JOGOS>) · Season <ANO>
  – Descrição geral.
  – Tendência de gols.
  – Tendência de BTTS.
  – Tendência de cartões.
  – Tendência de escanteios.
  – Caso aplicável, mencionar volatilidade.
"""

    # ---------------------------------------------------------
    # BUSCAR LIGA
    # ---------------------------------------------------------
    def get_league(self, league_id):

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT league_id, name, season
            FROM leagues
            WHERE league_id = %s
            LIMIT 1;
        """, (league_id,))

        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return None

        return {
            "league_id": row[0],
            "name": row[1],
            "season": row[2]
        }

    # ---------------------------------------------------------
    # BUSCAR JOGOS DA LIGA
    # ---------------------------------------------------------
    def get_games_from_league(self, league_id, season):

        season = str(season)

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT 
                fixture_id,
                match_date,
                home_goals,
                away_goals,
                total_corners,
                total_yellow_cards,
                total_red_cards
            FROM match_statistics
            WHERE league_id = %s AND season = %s
            ORDER BY match_date ASC;
        """, (league_id, season))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        games = []
        for r in rows:
            games.append({
                "fixture_id": r[0],
                "match_date": r[1].isoformat() if r[1] else None,
                "home_goals": r[2],
                "away_goals": r[3],
                "total_corners": r[4],
                "total_yellow_cards": r[5],
                "total_red_cards": r[6],
            })

        return games

    # ---------------------------------------------------------
    # BUSCAR MÉDIAS DA LIGA (CORRIGIDO)
    # ---------------------------------------------------------
    def get_team_averages(self, league_id, season):

        season = str(season)

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                avg_goals_for,
                avg_goals_against,
                avg_total_corners,
                avg_total_yellow,
                avg_total_red
            FROM team_statistics
            WHERE league_id = %s AND season = %s;
        """, (league_id, season))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return {}

        total = {
            "avg_goals_for": 0,
            "avg_goals_against": 0,
            "avg_total_corners": 0,
            "avg_total_yellow": 0,
            "avg_total_red": 0,
        }

        for r in rows:
            total["avg_goals_for"] += float(r[0] or 0)
            total["avg_goals_against"] += float(r[1] or 0)
            total["avg_total_corners"] += float(r[2] or 0)
            total["avg_total_yellow"] += float(r[3] or 0)
            total["avg_total_red"] += float(r[4] or 0)

        n = len(rows)

        return {
            "avg_goals_for": total["avg_goals_for"] / n,
            "avg_goals_against": total["avg_goals_against"] / n,
            "avg_total_corners": total["avg_total_corners"] / n,
            "avg_total_yellow": total["avg_total_yellow"] / n,
            "avg_total_red": total["avg_total_red"] / n,
        }

    # ---------------------------------------------------------
    # GERAR E SALVAR ANÁLISE
    # ---------------------------------------------------------
    def generate_and_save_analysis(self, league_id, league_name, season):

        season = str(season)

        games = self.get_games_from_league(league_id, season)
        averages = self.get_team_averages(league_id, season)

        payload = {
            "league_name": league_name,
            "season": season,
            "total_games": len(games),
            "games": games,
            "league_averages": averages
        }

        # As regras viram system (e' instrucao, nao conteudo do usuario) e o
        # JSON fica no turno do usuario -- mesmo formato do gate em
        # pick_engine/ai_review.py.
        response = self.client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=self.LEAGUE_ANALYSIS_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )

        # content pode comecar com bloco de thinking (adaptive vem ligado por
        # padrao no Sonnet 5 / Opus 5), entao nunca indexar content[0] direto.
        analysis_text = next((b.text for b in response.content if b.type == "text"), "")

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO league_analysis 
            (league_id, league_name, season, analysis_text)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (league_id, season)
            DO UPDATE SET 
                analysis_text = EXCLUDED.analysis_text,
                updated_at = NOW();
        """, (league_id, league_name, season, analysis_text))

        conn.commit()
        cur.close()
        conn.close()

        return analysis_text

    # Alias
    def generate_and_save(self, league_id, league_name, season):
        return self.generate_and_save_analysis(league_id, league_name, season)

    # ---------------------------------------------------------
    # BUSCAR ANÁLISE
    # ---------------------------------------------------------
    def get_league_analysis(self, league_id, season):

        season = str(season)

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT analysis_text
            FROM league_analysis
            WHERE league_id = %s AND season = %s
            LIMIT 1;
        """, (league_id, season))

        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return None

        return row[0]
