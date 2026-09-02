"""Consumo da cota da API-Football, do lado do MOTOR.

Gemeo de `website/backend/api_quota.py`, e a duplicacao e' deliberada: motor e
site sao processos separados, com `get_connection` proprio cada um, e o motor
nunca importou nada de `website/`. Criar um pacote compartilhado so' por estas
80 linhas acoplaria as duas bases por causa de instrumentacao -- caro demais
pro que resolve.

O que NAO pode divergir e' a TABELA (`api_quota_daily`) e a regra do minimo. As
duas escrevem na mesma linha do mesmo dia, e o `LEAST` do UPSERT resolve a
corrida: o menor vence, nao o ultimo a gravar.

Ver o modulo do site pro raciocinio completo -- por que o minimo e nao o
ultimo, e por que `consumidas` e' derivado em vez de contado por nos.

NADA AQUI PODE DERRUBAR O MOTOR. E' instrumentacao: toda falha e' engolida e a
coleta/analise segue. Cota mal medida e' um numero errado no painel; excecao
aqui seria pick que nao sai.
"""
from __future__ import annotations

import re
import threading
from datetime import date

_H_LIMITE = "x-ratelimit-requests-limit"
_H_RESTANTE = "x-ratelimit-requests-remaining"

_MILHAR = re.compile(r"^\d{1,3}(\.\d{3})+$")

_lock = threading.Lock()
_estado: dict = {"dia": None, "limite": None, "restante_min": None, "origem": None}


def _inteiro(valor) -> int | None:
    if valor is None:
        return None
    if isinstance(valor, int):
        return valor
    texto = str(valor).strip()
    if not texto:
        return None
    if _MILHAR.match(texto):
        texto = texto.replace(".", "")
    texto = texto.replace(",", "")
    try:
        return int(float(texto))
    except (TypeError, ValueError):
        return None


def ler_headers(headers) -> tuple[int | None, int | None]:
    if not headers:
        return (None, None)
    try:
        itens = {str(k).lower(): v for k, v in dict(headers).items()}
    except Exception:
        return (None, None)
    return (_inteiro(itens.get(_H_LIMITE)), _inteiro(itens.get(_H_RESTANTE)))


def registrar(headers, origem: str = "motor") -> None:
    """Registra o consumo a partir dos headers de uma resposta da API-Football.

    `origem` diz QUAL parte do motor gastou -- 'motor_live', 'coletor_odds',
    'coletor_fixtures'. E' o que permite responder "o ao vivo esta' comendo a
    cota?" sem cruzar log.
    """
    try:
        limite, restante = ler_headers(headers)
        if restante is None:
            return
        hoje = date.today()
        with _lock:
            if _estado["dia"] != hoje:
                _estado.update({"dia": hoje, "limite": limite,
                                "restante_min": restante, "origem": origem})
                _gravar(hoje, limite, restante, origem)
                return
            if limite is not None:
                _estado["limite"] = limite
            anterior = _estado["restante_min"]
            if anterior is not None and restante >= anterior:
                return
            _estado["restante_min"] = restante
            _estado["origem"] = origem
            _gravar(hoje, _estado["limite"], restante, origem)
    except Exception:
        pass


def _gravar(dia: date, limite: int | None, restante: int, origem: str) -> None:
    """UPSERT do minimo do dia, na MESMA tabela que o site escreve.

    Conexao propria e commit proprio: isto e' chamado de dentro de coletor e de
    pipeline, e nenhum dos dois pode ter a transacao mexida por instrumentacao
    -- foi exatamente esse tipo de acoplamento que deixou o Pick Boost em
    FAILED por dias (ver pick_boost_pipeline, rollback no laco).
    """
    try:
        from utils.db_utils import get_connection
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO api_quota_daily (dia, limite, restante_min, origem_min, atualizado_em)
                     VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (dia) DO UPDATE
                        SET limite = COALESCE(EXCLUDED.limite, api_quota_daily.limite),
                            origem_min = CASE
                                WHEN EXCLUDED.restante_min < api_quota_daily.restante_min
                                THEN EXCLUDED.origem_min ELSE api_quota_daily.origem_min END,
                            restante_min = LEAST(api_quota_daily.restante_min,
                                                 EXCLUDED.restante_min),
                            atualizado_em = NOW()
            """, (dia, limite, restante, origem))
            conn.commit()
        finally:
            cur.close()
            conn.close()
    except Exception:
        pass


def estado_atual() -> dict:
    with _lock:
        d = dict(_estado)
    if d["limite"] and d["restante_min"] is not None:
        d["consumidas"] = d["limite"] - d["restante_min"]
        d["pct_usado"] = round(100.0 * d["consumidas"] / d["limite"], 1)
    return d
