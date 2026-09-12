"""Cliente unico da API-Football, do lado do MOTOR.

POR QUE ISSO EXISTE
-------------------
A API-Football recusa com HTTP 200. Cota estourada, parametro invalido e plano
sem acesso ao recurso voltam todos como 200 com um objeto `errors` preenchido e
`response` vazio:

    {"get": "odds", "errors": {"requests": "..."}, "response": []}

`raise_for_status()` passa limpo por isso, e o padrao que estava escrito em
nove coletores era:

    data = response.json().get("response", [])   # -> []

...ou seja, FALHA VIRAVA "NAO EXISTE DADO". A pipeline seguia inteira achando
que o dia tinha menos jogos, que a casa nao cotou aquele jogo, que o time nao
tem historico. Nenhuma dessas conclusoes era verdade, e nenhuma delas gerava
alerta: o log imprimia o total menor com a confianca de sempre.

Esse mesmo bug ja foi corrigido duas vezes pontualmente (`live_feed.py` em
09/09, `player_stats_collector_service.py` antes disso) e continuou vivo em
todo o resto porque cada coletor tem a propria chamada escrita a mao. Aqui ele
e' corrigido UMA vez, e quem quiser reintroduzi-lo precisa deixar de usar este
modulo de proposito.

A PAGINACAO E' O MESMO PROBLEMA DE OUTRA FORMA
----------------------------------------------
`/fixtures` e `/odds` paginam em 100 itens. Ler so' a pagina 1 devolve uma
resposta bem formada, com 200, sem `errors` -- e incompleta. Silenciosa do
mesmo jeito. `buscar()` le `paging.total` e busca o resto; quem nao quiser isso
passa `paginar=False` e recebe `ApiPaginada` se houver pagina sobrando, que e'
melhor que ignorar em silencio.

O CONTRATO
----------
Devolve a lista `response` ou LEVANTA. Nunca devolve `[]` por falha. Quem
chama decide o que fazer com a excecao, mas nao consegue mais confundir os dois
casos por acidente.

    from utils.api_client import buscar, ApiFootballError

    try:
        jogos = buscar("fixtures", {"date": "2026-09-11"}, origem="coletor_fixtures")
    except ApiFootballError as e:
        ...  # isto e' FALHA, nao "nao ha jogos"
"""
from __future__ import annotations

import os
import time

import requests
from dotenv import load_dotenv, find_dotenv

from services import api_quota

load_dotenv(find_dotenv())

BASE_URL = "https://v3.football.api-sports.io"

#: Teto de paginas por chamada. Uma consulta que precise de mais que isso quase
#: sempre e' filtro errado (ex.: `/odds` sem `fixture`, que devolve o mundo --
#: ver o episodio do `/odds/live` em 09/09). Estourar o teto levanta em vez de
#: gastar a cota do dia inteiro num laco.
MAX_PAGINAS = 20

_TIMEOUT_PADRAO = 20
_TENTATIVAS = 3
_ESPERA_BASE = 2.0

#: HTTP que vale a pena repetir: indisponibilidade momentanea e rate limit por
#: minuto. 4xx de parametro nao entra -- repetir um filtro errado so' gasta cota.
_STATUS_RETENTAVEIS = {429, 500, 502, 503, 504}


class ApiFootballError(RuntimeError):
    """Falha de comunicacao ou de contrato com a API-Football.

    Existe pra ser distinguivel de "a consulta foi bem sucedida e nao havia
    dado". Todo `except` que engolir esta excecao esta' reintroduzindo o bug
    que este modulo corrige.
    """


class ApiRecusou(ApiFootballError):
    """HTTP 200 com `errors` preenchido. Cota, plano ou parametro."""

    def __init__(self, recurso: str, erros):
        self.recurso = recurso
        self.erros = erros
        super().__init__(f"API recusou `{recurso}`: {erros}")


class ApiQuotaEsgotada(ApiRecusou):
    """Subclasse de `ApiRecusou` pro caso especifico da cota diaria.

    Merece nome proprio porque a reacao certa e' diferente: parar a rodada
    inteira, nao tentar o proximo item da lista. Insistir depois da cota acabar
    produz N recusas identicas e nenhuma delas coleta nada.
    """


class ApiPaginada(ApiFootballError):
    """Resposta tinha mais paginas e o chamador pediu pra nao paginar."""


class ApiIndisponivel(ApiFootballError):
    """Rede, timeout ou HTTP de erro depois de esgotadas as tentativas."""


class ApiRespostaInvalida(ApiFootballError):
    """Corpo que nao e' o JSON esperado da API-Football."""


def _e_quota(erros) -> bool:
    """A recusa e' por cota do dia?

    `errors` vem ora como dict (`{"requests": "..."}`), ora como lista, ora
    como string, dependendo do recurso. Normaliza pra texto e procura o que a
    API escreve nesses casos.
    """
    texto = str(erros).lower()
    return any(p in texto for p in ("requests", "quota", "rate limit", "limit reached"))


def _corpo(resposta, recurso: str) -> dict:
    try:
        corpo = resposta.json()
    except ValueError as e:
        raise ApiRespostaInvalida(f"`{recurso}` devolveu corpo nao-JSON: {e}") from e

    if not isinstance(corpo, dict):
        raise ApiRespostaInvalida(
            f"`{recurso}` devolveu {type(corpo).__name__}, esperava objeto.")

    # ESTE BLOCO E' A RAZAO DE SER DO MODULO INTEIRO.
    #
    # `errors` vem como LISTA VAZIA quando esta' tudo bem e como dict/lista
    # preenchida quando nao esta'. `if erros:` cobre os dois, `is not None` nao.
    erros = corpo.get("errors")
    if erros:
        if _e_quota(erros):
            raise ApiQuotaEsgotada(recurso, erros)
        raise ApiRecusou(recurso, erros)

    return corpo


def _uma_chamada(recurso: str, params: dict, origem: str, timeout: int) -> dict:
    """Uma requisicao, com retry em falha transitoria. Registra a cota sempre.

    O registro de cota acontece ANTES de qualquer validacao: a requisicao foi
    gasta mesmo quando a resposta nao serve, e o painel precisa enxergar isso.
    """
    chave = os.getenv("API_FOOTBALL_KEY")
    if not chave:
        raise ApiFootballError("API_FOOTBALL_KEY nao definida no ambiente.")

    url = f"{BASE_URL}/{recurso.lstrip('/')}"
    ultimo = None

    for tentativa in range(1, _TENTATIVAS + 1):
        try:
            resposta = requests.get(
                url,
                headers={"x-apisports-key": chave},
                params=params,
                timeout=timeout,
            )
        except requests.RequestException as e:
            ultimo = ApiIndisponivel(f"`{recurso}` falhou na rede: {e}")
        else:
            api_quota.registrar(getattr(resposta, "headers", None), origem)

            if resposta.status_code in _STATUS_RETENTAVEIS:
                ultimo = ApiIndisponivel(
                    f"`{recurso}` devolveu HTTP {resposta.status_code}.")
            elif not resposta.ok:
                # 4xx de parametro nao se resolve repetindo.
                raise ApiIndisponivel(
                    f"`{recurso}` devolveu HTTP {resposta.status_code}: "
                    f"{resposta.text[:200]}")
            else:
                return _corpo(resposta, recurso)

        # Cota esgotada nao entra aqui: `_corpo` levanta `ApiQuotaEsgotada`, que
        # sobe direto sem passar por retry. Repetir nao devolve cota.
        if tentativa < _TENTATIVAS:
            espera = _ESPERA_BASE * (2 ** (tentativa - 1))
            print(f"[API] `{recurso}` tentativa {tentativa}/{_TENTATIVAS} falhou "
                  f"({ultimo}); aguardando {espera:.0f}s.")
            time.sleep(espera)

    raise ultimo or ApiIndisponivel(f"`{recurso}` falhou sem causa registrada.")


def buscar(recurso: str, params: dict = None, origem: str = "motor",
           timeout: int = _TIMEOUT_PADRAO, paginar: bool = True) -> list:
    """A lista `response` do recurso, COMPLETA, ou levanta `ApiFootballError`.

    Nunca devolve `[]` por falha: lista vazia aqui significa, e so' significa,
    que a API respondeu com sucesso e nao havia dado.
    """
    params = dict(params or {})
    corpo = _uma_chamada(recurso, params, origem, timeout)

    itens = corpo.get("response")
    if itens is None:
        raise ApiRespostaInvalida(f"`{recurso}` respondeu sem a chave `response`.")
    if not isinstance(itens, list):
        raise ApiRespostaInvalida(
            f"`{recurso}` devolveu `response` como {type(itens).__name__}, "
            f"esperava lista.")

    paginas = int(((corpo.get("paging") or {}).get("total")) or 1)
    if paginas <= 1:
        return itens

    if not paginar:
        raise ApiPaginada(
            f"`{recurso}` tem {paginas} paginas e a chamada pediu pagina unica.")

    if paginas > MAX_PAGINAS:
        raise ApiPaginada(
            f"`{recurso}` tem {paginas} paginas (teto {MAX_PAGINAS}). "
            f"Filtro provavelmente amplo demais: {params}")

    for pagina in range(2, paginas + 1):
        seguinte = _uma_chamada(recurso, {**params, "page": pagina}, origem, timeout)
        extras = seguinte.get("response")
        if not isinstance(extras, list):
            raise ApiRespostaInvalida(
                f"`{recurso}` pagina {pagina} devolveu `response` invalido.")
        itens.extend(extras)

    return itens
