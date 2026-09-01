# ── Stage 1: Build React frontend ─────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /frontend
# Vite so consegue ler VITE_* de process.env durante o "npm run build" --
# variaveis do Railway sao injetadas em tempo de execucao, nao chegam
# sozinhas dentro de um estagio isolado de build do Dockerfile. Precisa
# declarar cada uma como ARG aqui pra ela virar ENV disponivel pro build.
ARG VITE_TURNSTILE_SITE_KEY
ENV VITE_TURNSTILE_SITE_KEY=$VITE_TURNSTILE_SITE_KEY
ARG VITE_CONTACT_URL
ENV VITE_CONTACT_URL=$VITE_CONTACT_URL
COPY website/frontend/package*.json ./
RUN npm ci --ignore-scripts
COPY website/frontend/ .
RUN npm run build && npm run build:comprimir

# ── Stage 2: Python API + frontend buildado ────────────────────
FROM python:3.12-slim
WORKDIR /app
COPY website/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY website/backend/ .
COPY ApostaEsportivas/src/ ./pipeline/
COPY --from=frontend /frontend/dist ./dist
ENV PIPELINE_SRC_PATH=/app/pipeline
# pipeline incluido em /app/pipeline
EXPOSE 8000
# WEB_CONCURRENCY controla quantos processos servem o site. Fica em 1 por padrao
# (o comportamento de sempre) porque subir isto multiplica a memoria E as
# conexoes com o Supabase: cada worker tem o SEU pool de DB_POOL_MAX. Antes de
# passar pra 2, conferir o limite de conexoes do plano e dividir DB_POOL_MAX
# pelo numero de workers.
# --app-dir /app NAO e enfeite: dentro da imagem existem DOIS main.py, o do
# site em /app e o do motor em /app/pipeline. Com um worker so o uvicorn
# importa a partir do diretorio atual e acerta; com --workers 2 ele respawna
# o processo e o /app deixa de ganhar a disputa, entao `main` casa com o do
# motor -- que nao tem `app`. O sintoma e um 502 permanente com
# "Attribute app not found in module main" em loop, vivido em 01/09/2026.
# Com a flag, /app entra na frente do sys.path em qualquer numero de workers.
CMD uvicorn main:app --app-dir /app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-1} --proxy-headers --forwarded-allow-ips=*
