# Sistema de Análise de Valor em Apostas Esportivas

## Objetivo
Automatizar a coleta de dados de partidas de futebol, estatísticas históricas e odds, realizando análise estatística objetiva para identificar apostas de valor.

## Estrutura
- `src/collectors/`: Coleta dados do SofaScore e odds da Betano
- `src/models/`: Modelos de dados
- `src/analytics/`: Modelos estatísticos para mercados suportados
- `src/services/`: Serviço de análise de valor esperado
- `src/main.py`: Exemplo de uso

## Execução
1. Instale dependências:
   ```bash
   pip install -r requirements.txt
   pip install playwright
   playwright install
   ```
2. Execute:
   ```bash
   python src/main.py
   ```

## Saída
Lista JSON estruturada com análise de valor para cada mercado suportado.
