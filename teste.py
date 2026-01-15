from src.services.historical_stats_service import HistoricalStatsService
from src.services.value_analysis_service import ValueAnalysisService

hist_service = HistoricalStatsService()
value_service = ValueAnalysisService()

stats = hist_service.get_team_stats(7848)  # Manchester United
result = value_service.analyze_over_goals(stats, odd=1.95)
result = value_service.analyze_over_corners(stats, odd=1.85, line=5.5) 

print(result)
