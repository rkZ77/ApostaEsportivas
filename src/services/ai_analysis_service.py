import os
import requests


class AIAnalysisService:
    """
    Serviço que usa um modelo LLM para validar se a aposta tem valor real.
    A lógica final combina estatísticas + odds + análise qualitativa da IA.
    """

    def __init__(self):
        self.model = os.getenv("AI_MODEL_NAME", "gpt-4o-mini")
        self.api_key = os.getenv("OPENAI_API_KEY")

    def analyze_pick(self, home, away, market, side, line, odd, probability, stats_home, stats_away):
        """
        Envia para a IA uma análise objetiva comparando:
        - estatísticas reais
        - probabilidade calculada
        - mercado e linha
        - preço da odd
        """

        if not self.api_key:
            # Caso não exista chave, aprova apenas pelo EV simples
            return {"approve": True, "reason": "AI not configured; auto-approve."}

        prompt = f"""
Você é um analista profissional de apostas esportivas.

Jogo: {home} x {away}
Mercado: {market}
Lado: {side}
Linha: {line}
Odd: {odd}
Probabilidade estimada: {probability:.3f}

Estatísticas do time da casa:
{stats_home}

Estatísticas do time visitante:
{stats_away}

Considere fatores:
- tendência de gols/escanteios/cartões
- desempenho recente
- confronto direto
- força ofensiva e defensiva
- se a odd está precificada de forma justa ou desajustada

Pergunta final:
A aposta tem valor real? Responda apenas em JSON:

{{
    "approve": true/false,
    "confidence": 0.00-1.00,
    "reason": "explicação objetiva de até 3 linhas"
}}
"""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            },
            timeout=30
        )

        result = response.json()["choices"][0]["message"]["content"]

        try:
            import json
            return json.loads(result)
        except Exception:
            return {
                "approve": False,
                "confidence": 0,
                "reason": "Invalid AI output"
            }
