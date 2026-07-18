"""Pipelines de geracao de picks usando o motor deterministico
(services/pick_engine/) em vez de IA. Desde 2026-07-17 sao os UNICOS
geradores de picks_vip/free/multiplas/alavancagem em producao -- os
pipelines de IA em ai/*.py ficam no disco sem uso, so pra reverter rapido
se precisar (ver docstring de main.py::cmd_vip)."""
