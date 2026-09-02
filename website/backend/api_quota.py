"""Consumo da cota da API-Football, lido de graça do próprio response.

O QUE ISTO RESOLVE
------------------
O projeto tinha tetos de requisição em vários lugares (`max_requisicoes` do
motor ao vivo, TTL de cache em cada router) e NENHUMA medição: ninguém sabia
quantas das 7.500 chamadas diárias do plano Pro estavam sendo usadas de fato.
"Está controlado" era uma afirmação sobre o código, não sobre o consumo.

A API-Football já responde isso em todo request, e a informação estava sendo
descartada:

    x-ratelimit-requests-limit:     7500
    x-ratelimit-requests-remaining: 6812

Este módulo lê esses dois headers e guarda o MENOR `remaining` visto no dia.
Custo: zero requisição -- é dado que já chega.

POR QUE O MENOR, E NÃO O ÚLTIMO
-------------------------------
O contador da API reseta em algum ponto do dia (fuso deles). Guardar o último
valor faria o consumo "desaparecer" logo após o reset, justamente no dia em que
tivesse sido alto. O menor valor do dia é o pico real de uso, que é a pergunta:
"chegamos perto do teto hoje?".

`consumidas` é derivado (`limite - restante_min`) em vez de contado por nós:
contar de dentro erra sempre que alguém chama a API por fora (script na mão,
teste, coletor rodando em outra máquina). O número da própria API não erra.

NADA AQUI PODE DERRUBAR UMA REQUISIÇÃO
--------------------------------------
É instrumentação. Toda falha é engolida com log e a chamada original segue --
uma tabela ausente, um header em formato novo ou o banco fora do ar não podem
transformar "o usuário não vê o placar" em consequência de medir cota.
"""
from __future__ import annotations

import logging
import re
import threading
from datetime import date

logger = logging.getLogger(__name__)

#: Nomes dos headers, minúsculos. `requests` e `httpx` fazem lookup
#: case-insensitive, mas o dict cru de um mock não faz -- por isso a busca
#: abaixo normaliza em vez de confiar no tipo que chegou.
_H_LIMITE = "x-ratelimit-requests-limit"
_H_RESTANTE = "x-ratelimit-requests-remaining"

#: Escrever no banco a cada chamada seria uma escrita por request de API. O
#: estado do dia fica em memória e só desce quando o mínimo PIORA, que é a
#: única vez em que o valor gravado mudaria.
_lock = threading.Lock()
_estado: dict = {"dia": None, "limite": None, "restante_min": None, "origem": None}


#: "6.812" (ponto de milhar) contra "6812.0" (float). A diferença é o que vem
#: DEPOIS do último ponto: três dígitos é milhar, o resto é decimal. Sem esta
#: distinção um "6.812" viraria 6 e o painel mostraria cota estourada.
_MILHAR = re.compile(r"^\d{1,3}(\.\d{3})+$")


def _inteiro(valor) -> int | None:
    """Aceita 6812, "6812", "6812.0", "6,812" e "6.812"."""
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
    """(limite, restante) de um objeto de headers, ou (None, None).

    Funciona com `requests`, `httpx` e dict cru -- normaliza a chave em vez de
    depender do lookup case-insensitive das duas primeiras.
    """
    if not headers:
        return (None, None)
    try:
        itens = {str(k).lower(): v for k, v in dict(headers).items()}
    except Exception:
        return (None, None)
    return (_inteiro(itens.get(_H_LIMITE)), _inteiro(itens.get(_H_RESTANTE)))


def registrar(headers, origem: str = "site") -> None:
    """Registra o consumo a partir dos headers de uma resposta da API-Football.

    `origem` diz QUEM gastou -- 'live', 'fixtures', 'explorar', 'motor'. Fica
    guardado junto do mínimo do dia, então o painel responde não só "quanto
    sobrou" mas "quem estava consumindo quando ficou baixo".
    """
    try:
        limite, restante = ler_headers(headers)
        if restante is None:
            return
        hoje = date.today()
        # A contagem por origem vale pra TODA chamada, nao so' pras que baixam o
        # minimo -- e' um contador, nao uma marca d'agua.
        _contar(hoje, origem)
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
                return          # não piorou: nada a gravar
            _estado["restante_min"] = restante
            _estado["origem"] = origem
            _gravar(hoje, _estado["limite"], restante, origem)
    except Exception:
        logger.debug("[API_QUOTA] falha ao registrar (ignorado)", exc_info=True)


def _gravar(dia: date, limite: int | None, restante: int, origem: str) -> None:
    """UPSERT do mínimo do dia. `LEAST` no update porque dois processos (site e
    motor) escrevem na mesma linha e o menor tem que vencer, não o último."""
    try:
        from database import get_connection
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
        logger.debug("[API_QUOTA] falha ao gravar (ignorado)", exc_info=True)


def _contar(dia: date, origem: str) -> None:
    """Uma chamada a mais nesta origem, hoje.

    Por que contar por fora, se o header da API já dá o total: o header não
    REPARTE. Ele diz que sobraram 6.812 de 7.500, não que o motor ao vivo gastou
    300 e o Explorar gastou 40. "O ao vivo está comendo a cota?" só se responde
    repartindo, e essa é a pergunta que se faz.

    Os dois números convivem e medem coisas diferentes de propósito: o header é
    a verdade sobre o TOTAL (inclusive do que roda fora daqui -- script na mão,
    outra máquina), e este contador é a verdade sobre a REPARTIÇÃO do que passou
    por este código. Divergir é esperado; se o total do header for bem maior que
    a soma daqui, a diferença é consumo de fora, o que também é informação.
    """
    try:
        from database import get_connection
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO api_quota_calls (dia, origem, chamadas, atualizado_em)
                     VALUES (%s, %s, 1, NOW())
                ON CONFLICT (dia, origem) DO UPDATE
                        SET chamadas = api_quota_calls.chamadas + 1,
                            atualizado_em = NOW()
            """, (dia, origem))
            conn.commit()
        finally:
            cur.close()
            conn.close()
    except Exception:
        logger.debug("[API_QUOTA] falha ao contar (ignorado)", exc_info=True)

def estado_atual() -> dict:
    """O que está em memória neste processo. Leitura barata, sem banco."""
    with _lock:
        d = dict(_estado)
    if d["limite"] and d["restante_min"] is not None:
        d["consumidas"] = d["limite"] - d["restante_min"]
        d["pct_usado"] = round(100.0 * d["consumidas"] / d["limite"], 1)
    return d
