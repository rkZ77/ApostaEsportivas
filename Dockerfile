# ── Stage 1: Build React frontend ─────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /frontend
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
COPY --from=frontend /frontend/dist ./dist
EXPOSE 8000
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
