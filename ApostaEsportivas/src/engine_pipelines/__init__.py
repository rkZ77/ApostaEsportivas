"""Pipelines de geracao de picks usando o motor deterministico
(services/pick_engine/) em vez de IA. Rodam SOMENTE quando DB_ENV=dev
(cada modulo tem seu proprio guard) -- em producao os pipelines de IA
em ai/*.py continuam intocados e sao os unicos usados."""
