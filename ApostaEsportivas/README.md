# ApostaEsportivas – Sistema Inteligente de Análise de Futebol
Projeto completo de coleta, análise estatística, scraping de odds da Betano e geração de sugestões de aposta com motor de IA + modelo matemático.

O objetivo é rodar um pipeline completo que:

1. Busca fixtures via API Football  
2. Sincroniza times, estatísticas históricas e estatísticas por jogo  
3. Faz scraping REAL das odds da Betano  
4. Analisa estatísticas + probabilidades matemáticas  
5. Aplica regras de IA  
6. Gera sugestões de aposta  
7. Avalia green/red pós-jogo  
8. Consolida métricas  

---

# 1. Arquitetura Geral do Projeto

```
src/
  collectors/
      api_football_collector.py
      betano_league_scraper_service.py
      betano_match_scraper_service.py
      betano_scraper_service.py
      fixture_collector_service.py

  services/
      ai_analysis_service.py
      ai_decision_service.py
      historical_stats_service.py
      match_statistics_sync_service.py
      metrics_service.py
      odds_event_sync_service.py
      post_game_evaluation_service.py
      pre_game_suggestion_service.py
      probability_model_service.py
      save_odds_service.py
      team_statistics_sync_service.py
      team_sync_service.py
      value_analysis_service.py

  data_collector_main.py
  analytics_main.py

database/
models/
```

---

# 2. Fontes de Dados

### **API Football**
Usada para:
- Fixtures
- Times
- Estatísticas de jogos
- Tendências históricas

### **Betano Scraping**
Usada para:
- Odds reais por jogo
- Mercados:
  - Resultado (1x2)
  - Gols (bt=3)
  - Escanteios (bt=5)
  - Cartões (bt=6)
  - Linhas de mais/menos (bt=1)

---

# 3. Ligas Suportadas

| ID | Liga |
|----|------------------------|
| 39 | Premier League |
| 71 | Brasileirão Série A |
| 128 | Paulistão A1 |
| 140 | La Liga |
| 78 | Bundesliga |
| 2 | Champions League |

---

# 4. Pipeline do Sistema

## **4.1 Pipeline de Coleta – data_collector_main.py**

Executa:

1. Buscar fixtures hoje + amanhã  
2. Salvar fixtures  
3. Sincronizar times das ligas  
4. Sincronizar estatísticas por time  
5. Sincronizar estatísticas por jogo  
6. Atualizar histórico  
7. Scraping de odds por liga  
8. Scraping de odds por jogo  
9. Salvar odds no banco  

Esse pipeline prepara completamente o banco para análise.

---

## **4.2 Pipeline de Análise – analytics_main.py**

Executa:

1. Carregar fixtures do dia  
2. Carregar estatísticas  
3. Carregar odds salvas  
4. IA calcula probabilidades reais  
5. Modelo matemático calcula expected value  
6. Combina IA + Matemática  
7. Gera sugestões  
8. Salva no banco  
9. Avalia green/red pós-jogo  
10. Gera métricas  

---

# 5. Tabelas Essenciais (Banco de Dados)

## fixtures
- fixture_id  
- league_id  
- home_team  
- away_team  
- match_datetime  
- status  
- last_updated  

## betano_odds
- id  
- fixture_id  
- market  
- line  
- side  
- odd  
- bookmaker  
- scraped_at  

## bet_recommendations
- id  
- fixture_id  
- market  
- side  
- line  
- odd  
- probability  
- expected_value  
- status  
- created_at  

---

# 6. Como Rodar

### Instalar dependências:
```
pip install -r requirements.txt
```

---

### Rodar pipeline de coleta:
```
python -m src.data_collector_main
```

---

### Rodar pipeline de análise:
```
python -m src.analytics_main
```

---

# 7. Scraping da Betano (Mercados)

Mercados suportados (via ?bt=X):

| bt | Mercado |
|----|---------|
| 1 | Linhas Over/Under |
| 3 | Gols |
| 5 | Escanteios |
| 6 | Cartões |

O scraper salva tudo estruturado no banco.

---

# 8. IA do Sistema

### ai_analysis_service.py
Gera probabilidades ajustadas via:
- ofensividade  
- defensividade  
- forma  
- média de escanteios  
- tendência histórica  

### ai_decision_service.py
Aplica regras:
- valor matemático  
- confiança  
- risco ponderado  

---

# 9. Sistema de Seleções para Copa do Mundo 🏆

### **NOVO: Prompts Personalizados por Seleção**

Sistema completo implementado para Copa do Mundo 2026 que gera prompts personalizados para cada seleção nacional.

**Funcionalidades:**
- ✅ Análise automática de últimos 15 jogos (banco + API)
- ✅ Perfil tático detalhado de cada seleção
- ✅ Identificação de pontos fortes e fracos
- ✅ Análise de confrontos diretos
- ✅ Cache inteligente para otimização
- ✅ Funciona para todas as 48 seleções da Copa 2026

**Componentes:**
- `NationalTeamProfileService` - Busca e analisa dados das seleções
- `TeamPromptBuilder` - Gera prompts personalizados
- `AITipsterOrchestrator` - Detecta Copa e usa sistema de seleções

**Documentação completa:** [`SISTEMA_SELECOES_COPA.md`](SISTEMA_SELECOES_COPA.md)

**Como usar:**
```bash
# 1. Atualizar jogos (Stage 4 coleta amistosos automaticamente se houver fixtures da Copa)
python -m src.atualizar_jogos

# 2. Gerar sugestões (detecta Copa automaticamente)
python -m src.gerar_sugestao_vip
```

**Guia completo**: [`COMO_USAR_COPA_DO_MUNDO.md`](COMO_USAR_COPA_DO_MUNDO.md)

---

# 10. Próximas Melhorias

- Aprimorar regras cruzadas estatísticas
- Criar modelo ML para prever gols
- Criar dashboard
- Criar API REST
- Fechar ciclo completo de automação
- Adicionar mais métricas ao perfil de seleções (lesões, clima)

---

# 11. Autor

Projeto construído por
**Henrique Pereira**
Especialista em automação, análise e IA aplicada ao futebol.







HISTÓRICO TOTAL MANDANTE:
{total_h_json}

HISTÓRICO TOTAL VISITANTE:
{total_a_json}