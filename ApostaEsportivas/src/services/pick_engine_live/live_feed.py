"""Cliente da API-Football com ORCAMENTO RIGIDO de requisicoes por rodada.

O PROBLEMA QUE ISTO RESOLVE
---------------------------
O scheduler do projeto foi deletado em 2026-08-01 porque a coleta de amistosos
das selecoes queimava ~768 requisicoes/dia e derrubava a coleta de odds das
ligas ativas -- o motor ficava sem insumo do produto real. Um motor ao vivo
e', por natureza, o tipo de coisa que repete esse acidente: dez jogos
acompanhados a cada 60s por 90 minutos sao 1800 requisicoes.

Por isso o contador nao e' telemetria, e' FREIO. `_get` verifica o orcamento
ANTES de sair pela rede e levanta `OrcamentoEsgotado` quando a proxima chamada
passaria do teto. Quem chama trata isso como fim de rodada, nao como erro.

Nao ha retry e nao ha cache entre rodadas de proposito:
  - retry esconde consumo (uma chamada que falha e' repetida e conta duas
    vezes contra a cota real da conta, mas uma so' contra o orcamento local);
  - cache entre rodadas nao faz sentido num motor manual, onde cada execucao
    e' um instante diferente do jogo. O cache que existe e' DENTRO da rodada
    (`_memoria`), pra o mesmo fixture consultado duas vezes na mesma passada
    nao custar duas requisicoes.

Este modulo nao decide nada. Ele so' busca, conta e para.
"""
from __future__ import annotations

import os
import time

import requests

from utils.stat_sheet import ler_folha
from services import api_quota

API_BASE = "https://v3.football.api-sports.io"

#: Status que a API-Football usa pra jogo em andamento. Mesmo conjunto de
#: website/backend/routers/live.py -- duas listas divergentes de "o que e' um
#: jogo ao vivo" seria a mesma classe de bug que a auditoria encontrou entre
#: o job em lote e o caminho ao vivo do settlement.
STATUS_AO_VIVO = {"1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT"}
STATUS_ENCERRADO = {"FT", "AET", "PEN"}

#: Intervalo (HT) e paralisacao nao tem minuto util pra estimar ritmo, mas o
#: jogo continua. Sao tratados na selecao, nao aqui.
STATUS_SEM_RELOGIO = {"HT", "BT", "SUSP", "INT", "P"}


class OrcamentoEsgotado(RuntimeError):
    """O teto de requisicoes da rodada foi atingido. Nao e' erro: e' o freio
    funcionando. Quem chama encerra a rodada e reporta o que ja conseguiu."""


class LiveFeed:
    """Uma instancia por rodada. O orcamento vive no objeto, entao esquecer de
    zerar entre rodadas e' impossivel -- a rodada seguinte cria outro."""

    def __init__(self, limite_requisicoes: int, timeout: int = 12):
        self.limite = int(limite_requisicoes)
        self.usadas = 0
        self.timeout = timeout
        self._memoria: dict[tuple, object] = {}
        self._trilha: list[dict] = []
        self._paginas: dict[str, int] = {}
        #: fixture_id -> lista de mercados ao vivo, da chamada global.
        #: `None` enquanto ela nao foi feita -- e' o que separa "ainda nao
        #: perguntei" de "perguntei e nao ha' nada", que era exatamente a
        #: confusao que derrubou o dia 05/09.
        self._odds_do_mundo: dict | None = None

    # ── Contabilidade ────────────────────────────────────────────────────
    @property
    def restantes(self) -> int:
        return max(0, self.limite - self.usadas)

    def tem_orcamento(self, quantas: int = 1) -> bool:
        return self.usadas + quantas <= self.limite

    def trilha(self) -> list[dict]:
        """O que foi chamado, em ordem. Vai pro log da rodada -- sem isso
        'gastei 12 requisicoes' nao diz onde elas foram."""
        return list(self._trilha)

    def ultimo_erro(self, endpoint: str) -> str | None:
        """A falha da chamada mais recente a este endpoint, se houve.

        EXISTE PORQUE `_get` DEVOLVE `[]` EM QUALQUER FALHA (rede, HTTP, JSON)
        e a lista vazia e' indistinguivel de "a API respondeu, nao ha nada".
        Nos outros endpoints isso e' aceitavel; em `odds/live` nao e': o log
        imprimia "0 linha(s) ativa(s)" e o descarte ia pro banco como
        LIVE_SEM_LINHA -- "o provedor nao cotou" -- tanto num 429 de cota
        estourada quanto numa casa que realmente nao abriu o mercado. Sao dois
        diagnosticos com acoes opostas, e o unico descarte do motor que gasta
        requisicao.
        """
        for registro in reversed(self._trilha):
            if registro.get("endpoint") == endpoint:
                return registro.get("erro")
        return None

    # ── Transporte ───────────────────────────────────────────────────────
    def _headers(self) -> dict:
        chave = os.getenv("API_FOOTBALL_KEY", "")
        if not chave:
            raise RuntimeError("API_FOOTBALL_KEY nao definida no ambiente.")
        return {"x-apisports-key": chave}

    def _get(self, endpoint: str, params: dict) -> list:
        chave_cache = (endpoint, tuple(sorted(params.items())))
        if chave_cache in self._memoria:
            return self._memoria[chave_cache]  # type: ignore[return-value]

        if not self.tem_orcamento():
            raise OrcamentoEsgotado(
                f"Teto de {self.limite} requisicoes atingido antes de chamar "
                f"{endpoint} {params}."
            )

        inicio = time.perf_counter()
        # Conta ANTES de sair pela rede: uma chamada que estoura timeout
        # consumiu cota da conta do mesmo jeito, e contar so' no sucesso
        # deixaria o orcamento local mentir justo no dia ruim.
        self.usadas += 1
        erro = None
        dados: list = []
        try:
            resposta = requests.get(
                f"{API_BASE}/{endpoint}", headers=self._headers(),
                params=params, timeout=self.timeout,
            )
            api_quota.registrar(getattr(resposta, "headers", None), "motor_live")
            resposta.raise_for_status()
            corpo = resposta.json() or {}
            dados = corpo.get("response", []) or []
            # A API-FOOTBALL RECUSA COM HTTP 200. Cota do dia estourada, plano
            # sem o endpoint, chave invalida: nada disso vira status de erro --
            # vem 200 com `response: []` e o motivo dentro de `errors`.
            #
            # Ate' 2026-09-05 esse campo era descartado, e a recusa chegava no
            # motor como "a casa nao cotou este jogo". Foi assim que 211
            # descartes seguidos em PROD, com ZERO candidatos avaliados no dia
            # inteiro, ficaram sem causa: `erro` nulo (nao houve excecao) e
            # zero mercados no retorno diziam exatamente a mesma coisa que um
            # mercado realmente fechado.
            #
            # `errors` vem como dict quando ha' recusa e como lista vazia
            # quando esta tudo bem -- os dois formatos sao da propria API.
            recusa = corpo.get("errors")
            if isinstance(recusa, dict) and recusa:
                erro = "API recusou com HTTP 200: " + "; ".join(
                    f"{k}: {v}" for k, v in recusa.items())
            # Paginacao. So' importa na chamada global de odd ao vivo, que e' a
            # unica deste motor capaz de passar de uma pagina -- as outras sao
            # por fixture. Guardada aqui pra o chamador nao precisar do corpo.
            paginacao = (corpo.get("paging") or {})
            self._paginas[endpoint] = int(paginacao.get("total") or 1)
        except Exception as e:  # rede, HTTP, JSON -- todos terminam igual aqui
            erro = str(e)

        self._trilha.append({
            "endpoint": endpoint,
            "params": params,
            "ms": round((time.perf_counter() - inicio) * 1000),
            "itens": len(dados),
            "erro": erro,
        })
        self._memoria[chave_cache] = dados
        return dados

    # ── Endpoints ────────────────────────────────────────────────────────
    def partidas_ao_vivo(self) -> list:
        """UMA chamada pra o mundo inteiro. E' o endpoint mais barato que
        existe pro Live: devolve todos os jogos em andamento do planeta, e a
        filtragem por liga acontece aqui, de graca, em memoria."""
        return self._get("fixtures", {"live": "all"})

    def partida(self, fixture_id: int) -> dict | None:
        """Um fixture especifico. Usado no modo dirigido (--fixture), pra
        testar uma partida sem varrer o mundo."""
        itens = self._get("fixtures", {"id": fixture_id})
        return itens[0] if itens else None

    def estatisticas(self, fixture_id: int) -> list:
        return self._get("fixtures/statistics", {"fixture": fixture_id})

    def eventos(self, fixture_id: int) -> list:
        """Gol, cartao, penalti e substituicao COM O MINUTO de cada um.

        E' a unica fonte de "quando" no feed: /fixtures/statistics so' sabe
        somar. Sem isto o motor sabe que houve uma expulsao e nao sabe se foi
        aos 12' ou aos 80' -- que sao partidas completamente diferentes pro
        que ainda vai acontecer.
        """
        return self._get("fixtures/events", {"fixture": fixture_id})

    def odds_ao_vivo_do_mundo(self, max_paginas: int = 3) -> dict:
        """Todas as partidas com odd ao vivo AGORA, indexadas por fixture.

        MESMA IDEIA DE `partidas_ao_vivo`, e pelo mesmo motivo: `/odds/live`
        sem `fixture` devolve o mundo inteiro, e filtrar em memoria e' de
        graca. Uma requisicao no lugar de uma por partida.

        O QUE ISSO CONSERTA, alem da cota. Ate' 2026-09-05 cada partida perguntava
        pela propria odd e recebia lista vazia, e lista vazia por partida nao
        distingue "esta partida nao tem mercado" de "o provedor nao esta'
        servindo odd ao vivo pra ninguem". Em PROD isso custou 211 requisicoes
        num dia inteiro sem UM candidato avaliado, sem que o log conseguisse
        dizer qual dos dois estava acontecendo. Com a chamada global a
        pergunta se responde sozinha: se o mundo volta vazio, o problema e' o
        provedor ou o plano; se o mundo volta cheio e a nossa partida nao esta'
        nele, e' cobertura daquela partida.

        Nao levanta e nao decide nada: devolve `{}` quando nao ha' nada, e quem
        pergunta o motivo e' `ultimo_erro("odds/live")`.
        """
        por_fixture: dict[int, list] = {}
        pagina = 1
        while pagina <= max_paginas and self.tem_orcamento():
            params = {"page": pagina} if pagina > 1 else {}
            for item in self._get("odds/live", params) or []:
                fid = (item.get("fixture") or {}).get("id")
                if fid is not None:
                    por_fixture[int(fid)] = item.get("odds") or []
            if pagina >= self._paginas.get("odds/live", 1):
                break
            pagina += 1
        return por_fixture

    def odds_ao_vivo(self, fixture_id: int) -> list:
        """Os mercados ao vivo desta partida.

        A PRIMEIRA chamada busca o mundo inteiro e as seguintes leem da
        memoria -- entao a economia central do desenho continua de pe' (partida
        sem sinal nao dispara nada), e a rodada inteira custa UMA requisicao de
        odd em vez de uma por partida triada.
        """
        if self._odds_do_mundo is None:
            self._odds_do_mundo = self.odds_ao_vivo_do_mundo()
        return self._odds_do_mundo.get(int(fixture_id), [])

    def cobertura_de_odd_ao_vivo(self) -> dict | None:
        """Quantas partidas o provedor esta' servindo com odd ao vivo agora.

        Espelha `resumo_das_casas()` do coletor de pre-jogo: la' a pergunta e'
        "quais casas responderam e quais vieram vazias", aqui e' "o provedor
        esta' servindo alguma coisa". Sem isto, um dia inteiro sem odd nao tem
        como ser distinguido de um dia inteiro sem oportunidade.

        `None` quando a chamada global ainda nao aconteceu -- nenhuma partida
        chegou a pedir preco, e afirmar cobertura zero ai seria inventar.
        """
        if self._odds_do_mundo is None:
            return None
        return {
            "partidas_com_odd": len(self._odds_do_mundo),
            "erro": self.ultimo_erro("odds/live"),
        }


# ── Leitura do que a API devolve ─────────────────────────────────────────
#: Nomes que a folha de /fixtures/statistics usa. Iguais aos de
#: routers/live.py::_stat_for_market -- mesmo motivo do STATUS_AO_VIVO acima.
CHAVES_ESTATISTICA = {
    "corners": ("Corner Kicks",),
    "shots": ("Total Shots",),
    "shots_on_target": ("Shots on Goal",),
    "cards": ("Yellow Cards", "Red Cards"),
    "fouls": ("Fouls",),
    "possession": ("Ball Possession",),
    "red_cards": ("Red Cards",),
}


def _numero(valor) -> int | None:
    """Contador da folha, ou None se o provedor ainda nao publicou.

    AUSENCIA NUNCA VIRA ZERO. E' a invariante 1 de services/settlement.py, e a
    razao pela qual ela existe vale ainda mais aqui: no caminho ao vivo um
    zero fabricado nao produz so' um resultado errado, produz um PICK errado.
    'Zero escanteios aos 40 minutos' e' um sinal fortissimo de Under -- e
    completamente falso quando o que aconteceu foi a folha nao ter chegado.

    O que NAO e' ausencia: campo vazio dentro de folha publicada. Isso e' zero,
    e quem decide e' `ler_folha` -- ver utils/stat_sheet. Aqui a funcao so'
    converte, e continua existindo porque routers/live.py tambem a usa.
    """
    if valor is None:
        return None
    if isinstance(valor, str):
        valor = valor.replace("%", "").strip()
        if not valor:
            return None
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def ler_estatisticas(bruto: list, home_id: int | None, away_id: int | None) -> tuple[dict, dict]:
    """(stats casa, stats fora). O lado sai do team.id, nunca da posicao na
    lista -- a API nao garante que o indice 0 seja o mandante, e assumir isso
    liquidaria mercado de um lado com o numero do adversario."""
    lidos: list[dict] = []
    ids: list = []
    for time_ in bruto or []:
        # `ler_folha` classifica a folha antes de ler campo: folha ausente ou
        # so' de nulls devolve {} (tudo desconhecido), folha publicada com
        # campo vazio devolve 0. Antes desta troca "Red Cards": null -- o jeito
        # como a API escreve "ninguem foi expulso" -- caia fora do dicionario,
        # e com isso o motor ao vivo nao tinha total de cartao em ~90% das
        # partidas.
        #
        # `jogo_encerrado=False` (2026-08-28): a regra da folha robusta trata
        # contador ausente como ZERO, e isso vale pro jogo que ACABOU -- ali a
        # API nao omite evento que aconteceu. Aqui o jogo esta' rolando, e
        # contador ausente quer dizer "o provedor ainda nao publicou".
        #
        # Sem este `False`, "zero escanteios aos 60'" viraria dado real: o
        # motor decidiria um Over em cima de numero que nao existe, e a
        # deteccao de dado atrasado (live_state.DELAYED) pararia de disparar --
        # porque ela percebe justamente pelo contador que falta.
        d = {chave: int(valor) for chave, valor in ler_folha(
            time_.get("statistics") or [], jogo_encerrado=False).items()}
        lidos.append(d)
        ids.append((time_.get("team") or {}).get("id"))

    if not lidos:
        return {}, {}
    if home_id is not None and away_id is not None:
        por_id = {tid: d for tid, d in zip(ids, lidos) if tid is not None}
        if home_id in por_id and away_id in por_id:
            return por_id[home_id], por_id[away_id]
    return (lidos[0] if lidos else {}), (lidos[1] if len(lidos) > 1 else {})


#: Cartao vermelho vale 2 pontos. MESMA convencao de
#: services/pick_engine/stats_model._cards_points, do checker em lote e de
#: routers/live.py::_STAT_WEIGHTS. Contar de um jeito e liquidar de outro
#: deixaria a probabilidade do pick sem relacao com o que decide o resultado.
PESOS_ESTATISTICA = {"Red Cards": 2}


def total_da_familia(home_stats: dict, away_stats: dict, familia: str) -> int | None:
    """Total do jogo pra uma familia, ou None se qualquer lado faltar."""
    chaves = CHAVES_ESTATISTICA.get(familia)
    if not chaves:
        return None
    total = 0
    for lado in (home_stats, away_stats):
        for chave in chaves:
            valor = lado.get(chave)
            if valor is None:
                return None
            total += valor * PESOS_ESTATISTICA.get(chave, 1)
    return total


# `estado_da_partida` saiu daqui em 2026-08-11 e virou
# live_state.montar_estado(): o retrato da partida passou a incluir pressao,
# eventos, xG e freshness, e isso e' leitura de ESTADO, nao transporte. Este
# modulo ficou so' com o que fala com a rede e conta requisicao.
