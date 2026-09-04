"""Cache em memoria das rotas publicas, com TTL curto.

POR QUE ISTO EXISTE
-------------------
A Home abre seis chamadas publicas ao mesmo tempo (dica do dia, fila de jogos,
indicadores, curva, ligas, planos). Medidas UMA A UMA em producao elas custam
de 0,4 s a 1,9 s. Medidas como o navegador realmente faz -- as seis juntas --
o PageSpeed de 04/09 anotou 4,6 s a 6,3 s cada: com WEB_CONCURRENCY=1, elas
disputam o mesmo processo e a fila e' o proprio tempo de resposta.

O conteudo dessas seis e' o MESMO para todo mundo que abre o site no mesmo
minuto: sao numeros publicos, nao dado de conta. Recalcular por visitante e'
trabalho repetido -- e trabalho que o visitante paga esperando.

O QUE ELE NAO E'
----------------
Nao e' cache de dado de usuario. Cada rota escolhe uma chave; se a resposta
mudar conforme quem pergunta, ou a chave carrega isso, ou a rota cacheia so' a
parte publica e aplica o recorte depois (e' o que /free-pick-today faz com o
`locked`). Rota que grava, nunca.

O TTL E' O ATRASO MAXIMO ACEITO PRA CADA DADO, e esta escrito na chamada, nao
aqui: ligas mudam por temporada, a curva de lucro fecha ontem, o resultado de
um pick muda quando o jogo acaba. Ver os valores em routers/public.py.

UMA CONSULTA POR CHAVE, NAO UMA POR VISITA (single-flight)
----------------------------------------------------------
Sem isto, o cache resolveria o caso comum e falharia justamente no pico: as
seis visitas que chegam no instante em que a entrada vence encontram o cache
frio e disparam SEIS consultas identicas -- exatamente o engarrafamento que
motivou o arquivo. Com o lock por chave, a primeira calcula e as outras cinco
esperam por ela.

O cache e' por PROCESSO. Com WEB_CONCURRENCY=1 isso e' o servidor inteiro; se
um dia subirem os workers, cada um tera' o seu, o que aumenta o trabalho no
pior caso mas nao muda o comportamento visto de fora.
"""
import functools
import inspect
import logging
import threading
import time

logger = logging.getLogger(__name__)

#: chave -> (instante_monotonico, valor)
_dados: dict[str, tuple[float, object]] = {}
#: chave -> lock, criado sob demanda (ver single-flight na docstring)
_locks: dict[str, threading.Lock] = {}
_mestre = threading.Lock()


def _lock_de(chave: str) -> threading.Lock:
    with _mestre:
        return _locks.setdefault(chave, threading.Lock())


def obter(chave: str, ttl: float, produzir):
    """Valor de `chave`, calculado por `produzir()` no maximo a cada `ttl` s."""
    agora = time.monotonic()
    entrada = _dados.get(chave)
    if entrada and agora - entrada[0] < ttl:
        return entrada[1]

    with _lock_de(chave):
        # Reconferido dentro do lock: quem esperou aqui provavelmente esperou
        # justamente por quem acabou de preencher.
        entrada = _dados.get(chave)
        if entrada and time.monotonic() - entrada[0] < ttl:
            return entrada[1]

        valor = produzir()
        _dados[chave] = (time.monotonic(), valor)
        return valor


def invalidar(prefixo: str = "") -> int:
    """Descarta as entradas que comecam com `prefixo` (vazio = todas).

    Serve pro caso em que a espera do TTL seria visivel demais: publicar um
    pick novo pelo /admin e a Home continuar mostrando o anterior por um
    minuto, por exemplo.
    """
    alvo = [k for k in list(_dados) if k.startswith(prefixo)]
    for k in alvo:
        _dados.pop(k, None)
    return len(alvo)


def estado() -> list[dict]:
    """Idade de cada entrada, pro /admin poder olhar sem adivinhar."""
    agora = time.monotonic()
    return sorted(
        ({"chave": k, "idade_s": round(agora - t, 1)} for k, (t, _) in _dados.items()),
        key=lambda e: e["chave"],
    )


def rota(ttl: float, ignorar: tuple[str, ...] = ()):
    """Decorator: cacheia a rota por `ttl` segundos, com chave nos argumentos.

    `ignorar` tira da chave os parametros que o FastAPI injeta e que nao mudam
    a resposta (`request`, `background`). Rota cujo conteudo dependa de QUEM
    pergunta nao deve usar este decorator direto -- ver a docstring do modulo.

    O `functools.wraps` nao e' enfeite: o FastAPI le a assinatura da funcao pra
    saber quais query params existem, e `inspect.signature` segue o
    `__wrapped__` que o wraps deixa. Sem ele a rota perderia todos os
    parametros e passaria a aceitar qualquer coisa.
    """
    def decorar(fn):
        assinatura = inspect.signature(fn)

        @functools.wraps(fn)
        def dentro(*args, **kwargs):
            ligados = assinatura.bind(*args, **kwargs)
            ligados.apply_defaults()
            partes = [f"{k}={v!r}" for k, v in sorted(ligados.arguments.items())
                      if k not in ignorar]
            chave = f"{fn.__module__}.{fn.__name__}(" + ",".join(partes) + ")"
            return obter(chave, ttl, lambda: fn(*args, **kwargs))

        return dentro
    return decorar
