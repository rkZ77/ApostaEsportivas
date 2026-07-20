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
RUN npm run build

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
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=*
