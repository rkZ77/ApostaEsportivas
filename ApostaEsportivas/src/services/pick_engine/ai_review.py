"""Revisao contextual por IA para picks ja aprovados pelo motor."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Callable

from utils.db_utils import get_connection


# Provider padrao por pipeline (2026-07-31, pedido do usuario): Claude nos
# fluxos gratuitos/alavancagem, OpenAI no VIP e na multipla. Sempre pode ser
# sobrescrito por env -- ver a cascata em AIReviewSettings.from_env.
DEFAULT_PROVIDERS = {
    "dica": "anthropic",
    "alavancagem": "anthropic",
    "vip": "openai",
    "multipla": "openai",
    "goleiros": "openai",
    # Faltas fica no Claude junto com os outros fluxos de volume: o pick sai
    # de tabela empirica medida, nao de score composto, entao o parecer da IA
    # aqui e' checagem de contexto (classico, decisao ja definida, elenco
    # reserva) -- nao precisa do modelo mais caro pra isso.
    "faltas": "anthropic",
}

# Nao existe default de modelo pra OpenAI: o ID tem que vir do env. Chutar um
# ID errado faz a chamada falhar e o gate aprovar em silencio -- exatamente o
# bug que o claude-3-5-haiku-latest (aposentado em 19/02/2026) causava aqui.
#
# Anthropic saiu do claude-opus-5 pro claude-sonnet-5 em 2026-08-07: o parecer
# aqui e' classificacao binaria com schema fechado ("vete so' com contradicao
# objetiva no JSON", ver _system_prompt) -- nao e' trabalho de modelo de
# fronteira. Sonnet 5 custa 3/15 por milhao de tokens contra 5/25 do Opus 5,
# aceita effort igual e nao muda uma linha de codigo. Pra cortar mais, o
# claude-haiku-4-5 (1/5) ja' e' seguro desde que _aceita_effort exista.
DEFAULT_MODELS = {"anthropic": "claude-sonnet-5", "openai": ""}

# `output_config.effort` nao existe na linha inteira: Haiku 4.5 e Sonnet 4.5
# devolvem 400 quando o campo vem junto. Como este gate FALHA ABERTO, esse 400
# nao apareceria como erro no produto -- viraria status "unavailable" e decision
# "approve", ou seja: baixar o modelo pra economizar desligaria a revisao em
# silencio. Mesmo modo de falha do comentario acima.
#
# A lista e' de quem ACEITA effort, nunca de quem rejeita: modelo novo que nao
# esteja aqui entra sem o campo, que e' o lado seguro (perde o controle de
# profundidade, nao a revisao inteira).
_MODELOS_COM_EFFORT = (
    "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
    "claude-opus-4-5", "claude-sonnet-5", "claude-sonnet-4-6",
    "claude-fable-5", "claude-mythos-5",
)


def aceita_effort(model: str) -> bool:
    return model.startswith(_MODELOS_COM_EFFORT)

# Formato do parecer. No Anthropic vira structured output (o modelo nao
# consegue devolver fora do schema); no OpenAI o json_object nao valida
# schema, entao normalize_review continua sendo a rede de seguranca.
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["approve", "reject"]},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "evidence_gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decision", "risk_level", "reasons", "evidence_gaps"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class AIReviewSettings:
    mode: str = "off"
    provider: str = "anthropic"
    model: str = "claude-sonnet-5"
    cache_hours: int = 24
    # No Opus 5 o thinking vem ligado por padrao e max_tokens limita thinking
    # + resposta juntos: 350 truncava o JSON antes de fechar.
    max_tokens: int = 2000
    daily_limit: int = 15
    effort: str = "low"

    @classmethod
    def from_env(cls, pipeline: str = "") -> "AIReviewSettings":
        environment = os.getenv("AI_REVIEW_ENV", os.getenv("DB_ENV", "prod")).strip().upper()
        scope = (pipeline or "").strip().upper()

        def value(name: str, default: str) -> str:
            # Do mais especifico pro mais generico: _VIP_PROD, _VIP, _PROD, base.
            keys = ([f"{name}_{scope}_{environment}", f"{name}_{scope}"] if scope else [])
            for key in keys + [f"{name}_{environment}", name]:
                raw = os.getenv(key)
                if raw is not None and raw.strip():
                    return raw.strip()
            return default

        mode = value("AI_REVIEW_MODE", "off").lower()
        provider = value("AI_REVIEW_PROVIDER", DEFAULT_PROVIDERS.get(pipeline, "anthropic")).lower()
        if mode not in {"off", "shadow", "enforce"}:
            raise ValueError("AI_REVIEW_MODE deve ser off, shadow ou enforce")
        if provider not in {"anthropic", "openai"}:
            raise ValueError("AI_REVIEW_PROVIDER deve ser anthropic ou openai")

        model = value("AI_REVIEW_MODEL", DEFAULT_MODELS[provider])
        if mode != "off" and not model:
            # Desliga o gate em vez de deixar toda revisao falhar e "aprovar".
            # Sem modelo, zero evento no painel -- silencio visivel, nao falso ok.
            print(f"[AI_REVIEW] {pipeline or 'global'}: provider {provider} sem modelo definido. "
                  f"Defina AI_REVIEW_MODEL_{scope or environment}. Gate desligado.")
            mode = "off"

        return cls(
            mode=mode,
            provider=provider,
            model=model,
            cache_hours=max(1, int(value("AI_REVIEW_CACHE_HOURS", "24"))),
            max_tokens=max(500, int(value("AI_REVIEW_MAX_TOKENS", "2000"))),
            daily_limit=max(0, int(value("AI_REVIEW_DAILY_LIMIT", "15"))),
            effort=value("AI_REVIEW_EFFORT", "low").lower(),
        )


def build_review_payload(picks: list[dict], pipeline: str, fixture: dict | None = None) -> dict:
    fixture = fixture or {}
    return {
        "pipeline": pipeline,
        "fixture": {
            "id": fixture.get("fixture_id"), "home": fixture.get("home_team"),
            "away": fixture.get("away_team"), "league_id": fixture.get("league_id"),
            "round": fixture.get("round"), "kickoff": str(fixture.get("match_datetime") or ""),
        },
        "picks": [{
            "market": pick.get("market_name"), "market_type": pick.get("market_type"),
            "selection": pick.get("value_label"), "odd": pick.get("odd"),
            "probability": pick.get("taxa_real"), "confidence": pick.get("confidence"),
            "edge": pick.get("edge"), "ev": pick.get("ev"), "risk": pick.get("risco"),
            "data_quality": pick.get("data_quality_score"),
            "variance_penalty": pick.get("variance_penalty"),
            "model_probability": pick.get("poisson_probability"),
            "model_fit_difference": pick.get("model_fit_diff"),
            "market_sample": pick.get("market_sample"),
            "referee_signal": pick.get("referee_signal"),
            "game_intensity": pick.get("game_intensity"),
            "context": pick.get("context_raw"), "news": pick.get("news_raw"),
            "matchup": pick.get("matchup_raw"),
            # Contexto de eliminatoria e rivalidade (2026-08-06). O motor ja'
            # decide sozinho com isto -- context_gate barra o que contradiz a
            # partida antes de chegar aqui. Vai no payload pra a IA poder
            # VETAR com a mesma informacao, nunca pra ela ser a unica a
            # aplicar a regra: este gate falha aberto e tem teto diario, entao
            # uma regra que so' morasse aqui sumiria em silencio justamente
            # nos jogos decisivos.
            "match_context": pick.get("match_context"),
            "context_gate": pick.get("context_gate"),
        } for pick in picks],
    }


def cache_key_for_payload(payload: dict, settings: AIReviewSettings) -> str:
    serialized = json.dumps(
        {"provider": settings.provider, "model": settings.model, "payload": payload},
        sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def normalize_review(raw: object) -> dict:
    if isinstance(raw, str):
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            raw = json.loads(cleaned)
        except json.JSONDecodeError:
            raw = None
    if not isinstance(raw, dict):
        return {"status": "invalid_response", "decision": "approve", "risk_level": "unknown", "reasons": []}
    decision = str(raw.get("decision", "")).lower()
    risk_level = str(raw.get("risk_level", "")).lower()
    if decision not in {"approve", "reject"} or risk_level not in {"low", "medium", "high"}:
        return {"status": "invalid_response", "decision": "approve", "risk_level": "unknown", "reasons": []}
    return {
        "status": "ok", "decision": decision, "risk_level": risk_level,
        "reasons": [str(item)[:240] for item in (raw.get("reasons") or [])[:3]],
        "evidence_gaps": [str(item)[:160] for item in (raw.get("evidence_gaps") or [])[:3]],
    }


class AIReviewGate:
    """Cacheia pareceres e falha aberta para nunca travar o motor."""

    def __init__(self, settings: AIReviewSettings | None = None,
                 call_model: Callable[[str, str], object] | None = None,
                 pipeline: str = ""):
        self.pipeline = pipeline
        self.settings = settings or AIReviewSettings.from_env(pipeline)
        self._call_model_override = call_model
        self._cache_ready = False

    def _stamp(self, review: dict, cached: bool) -> dict:
        """Carimba QUEM deu o parecer. Sem isto o parecer fica salvo no pick
        (engine_debug.ai_review) sem dizer qual modelo o emitiu, e o painel de
        desempenho nao consegue separar Claude de OpenAI olhando o resultado --
        so' da' pra inferir por pipeline+dia, que erra no dia em que o modelo
        muda. Carimbar aqui e' seguro inclusive no cache: cache_key_for_payload
        inclui provider e model, entao um HIT so' acontece pro mesmo par."""
        return {**review, "mode": self.settings.mode, "cached": cached,
                "provider": self.settings.provider, "model": self.settings.model}

    def review(self, picks: list[dict], pipeline: str, fixture: dict | None = None) -> dict:
        # Sem carimbo de provider/model nos dois early-returns abaixo de
        # proposito: nenhum modelo olhou o pick nesses casos, e um carimbo aqui
        # faria o painel creditar (ou culpar) uma IA por um pick que ela nunca
        # viu.
        if self.settings.mode == "off":
            return {"status": "disabled", "decision": "approve", "mode": "off", "cached": False}
        payload = build_review_payload(picks, pipeline, fixture)
        key = cache_key_for_payload(payload, self.settings)
        cached = self._load_cache(key)
        if cached:
            review = self._stamp(cached, cached=True)
            self._record_event(key, pipeline, review)
            return review
        if self._daily_limit_reached():
            print(f"[AI_REVIEW] Limite diario de {self.settings.daily_limit} chamadas atingido.")
            return {"status": "daily_limit_reached", "decision": "approve", "mode": self.settings.mode, "cached": False}
        try:
            review = normalize_review(self._call_model(json.dumps(payload, ensure_ascii=False, default=str)))
        except Exception as error:
            print(f"[AI_REVIEW] Falha no provedor; mantendo pick do motor: {error}")
            review = {"status": "unavailable", "decision": "approve", "risk_level": "unknown", "reasons": []}
        review = self._stamp(review, cached=False)
        self._store_cache(key, pipeline, review)
        self._record_event(key, pipeline, review)
        return review

    def apply(self, picks: list[dict], pipeline: str, fixture: dict | None = None) -> list[dict]:
        if not picks:
            return []
        review = self.review(picks, pipeline, fixture)
        reviewed = [{**pick, "ai_review": review} for pick in picks]
        if self.settings.mode == "enforce" and review["decision"] == "reject":
            print(f"[AI_REVIEW] {pipeline}: selecao vetada ({'; '.join(review.get('reasons', []))})")
            return []
        return reviewed

    def _call_model(self, payload: str) -> object:
        if self._call_model_override:
            return self._call_model_override(self._system_prompt(), payload)
        if self.settings.provider == "anthropic":
            from anthropic import Anthropic
            # Sem temperature: removido do Opus 4.7 em diante, retorna 400.
            # output_config.format garante JSON valido pelo schema; effort=low
            # mantem o thinking curto num parecer que e so um veredito -- mas so
            # entra pra modelo que aceita o campo (ver _MODELOS_COM_EFFORT).
            output_config = {"format": {"type": "json_schema", "schema": REVIEW_SCHEMA}}
            if aceita_effort(self.settings.model):
                output_config["effort"] = self.settings.effort
            response = Anthropic().messages.create(
                model=self.settings.model, max_tokens=self.settings.max_tokens,
                system=self._system_prompt(),
                output_config=output_config,
                messages=[{"role": "user", "content": payload}],
            )
            if response.stop_reason == "refusal":
                raise RuntimeError("provedor recusou a revisao por politica de conteudo")
            # Com thinking ligado, content[0] pode ser um bloco de thinking --
            # nunca indexar direto, procurar o bloco de texto.
            return next((b.text for b in response.content if b.type == "text"), "")
        from openai import OpenAI
        # Sem temperature: a familia gpt-5 de raciocinio rejeita valor != 1.
        # json_schema + strict garante o formato, igual ao lado Anthropic; o
        # json_object antigo so prometia "algum JSON", nao o schema certo.
        response = OpenAI().chat.completions.create(
            model=self.settings.model,
            response_format={"type": "json_schema", "json_schema": {
                "name": "pick_review", "strict": True, "schema": REVIEW_SCHEMA}},
            messages=[{"role": "system", "content": self._system_prompt()}, {"role": "user", "content": payload}],
        )
        return response.choices[0].message.content or "{}"

    @staticmethod
    def _system_prompt() -> str:
        return (
            "Voce revisa apostas esportivas ja aprovadas por um motor estatistico. "
            "Nao calcule odds, nao invente fatos, nao sugira mercados e nao altere probabilidade, confidence ou stake. "
            "Voce nao tem acesso a noticias, internet ou dados fora do JSON recebido. "
            "Vete somente com contradicao ou risco objetivo nos dados. Sem evidencia objetiva, aprove. "
            "Considere qualidade da amostra, variancia, ajuste do modelo e sinais de arbitragem quando existirem. "
            "Responda somente JSON com decision (approve|reject), risk_level (low|medium|high), reasons e evidence_gaps."
        )

    def _load_cache(self, key: str) -> dict | None:
        try:
            self._ensure_cache_table()
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT review FROM ai_pick_reviews WHERE cache_key = %s AND expires_at > NOW()", (key,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            return row[0] if row else None
        except Exception as error:
            print(f"[AI_REVIEW] Cache indisponivel: {error}")
            return None

    def _store_cache(self, key: str, pipeline: str, review: dict) -> None:
        try:
            self._ensure_cache_table()
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO ai_pick_reviews (cache_key, pipeline, provider, model, review, expires_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, NOW() + (%s * INTERVAL '1 hour'))
                ON CONFLICT (cache_key) DO UPDATE SET review = EXCLUDED.review, expires_at = EXCLUDED.expires_at, created_at = NOW()""",
                (key, pipeline, self.settings.provider, self.settings.model,
                 json.dumps(review, ensure_ascii=False), self.settings.cache_hours),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as error:
            print(f"[AI_REVIEW] Nao foi possivel gravar cache: {error}")

    def _ensure_cache_table(self) -> None:
        if self._cache_ready:
            return
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS ai_pick_reviews (
            cache_key TEXT PRIMARY KEY, pipeline TEXT NOT NULL, provider TEXT NOT NULL,
            model TEXT NOT NULL, review JSONB NOT NULL, expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_pick_reviews_expiry ON ai_pick_reviews (expires_at)")
        cur.execute("""CREATE TABLE IF NOT EXISTS ai_pick_review_events (
            id BIGSERIAL PRIMARY KEY, cache_key TEXT NOT NULL, pipeline TEXT NOT NULL,
            mode TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
            status TEXT NOT NULL, decision TEXT NOT NULL, risk_level TEXT,
            cached BOOLEAN NOT NULL DEFAULT FALSE, review JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_pick_review_events_created ON ai_pick_review_events (created_at DESC)")
        conn.commit()
        cur.close()
        conn.close()
        self._cache_ready = True

    def _record_event(self, key: str, pipeline: str, review: dict) -> None:
        try:
            self._ensure_cache_table()
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO ai_pick_review_events
                (cache_key, pipeline, mode, provider, model, status, decision, risk_level, cached, review)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)""",
                (key, pipeline, review.get("mode", self.settings.mode), self.settings.provider,
                 self.settings.model, review.get("status", "unknown"), review.get("decision", "approve"),
                 review.get("risk_level"), bool(review.get("cached")), json.dumps(review, ensure_ascii=False)),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as error:
            print(f"[AI_REVIEW] Nao foi possivel registrar evento: {error}")

    def _daily_limit_reached(self) -> bool:
        if self.settings.daily_limit == 0:
            return False
        try:
            self._ensure_cache_table()
            conn = get_connection()
            cur = conn.cursor()
            # Teto por pipeline, nao global: com providers diferentes por fluxo
            # (Claude no free/alavancagem, OpenAI no VIP/multipla), um contador
            # unico faria o gasto de um provider silenciar o outro.
            if self.pipeline:
                cur.execute("SELECT COUNT(*) FROM ai_pick_reviews "
                            "WHERE created_at >= CURRENT_DATE AND pipeline = %s", (self.pipeline,))
            else:
                cur.execute("SELECT COUNT(*) FROM ai_pick_reviews WHERE created_at >= CURRENT_DATE")
            count = int(cur.fetchone()[0])
            cur.close()
            conn.close()
            return count >= self.settings.daily_limit
        except Exception as error:
            print(f"[AI_REVIEW] Nao foi possivel consultar limite diario: {error}")
            return False


_GATES: dict[str, AIReviewGate] = {}


def review_gate(pipeline: str) -> AIReviewGate:
    """Gate do pipeline, criado no primeiro uso -- nunca no import.

    Antes cada pipeline fazia `_AI_REVIEW = AIReviewGate()` no topo do modulo,
    entao from_env() rodava no import: um AI_REVIEW_MODE digitado errado no
    Railway derrubava o import do pipeline inteiro, antes de ler qualquer jogo.
    """
    if pipeline not in _GATES:
        _GATES[pipeline] = AIReviewGate(pipeline=pipeline)
    return _GATES[pipeline]
