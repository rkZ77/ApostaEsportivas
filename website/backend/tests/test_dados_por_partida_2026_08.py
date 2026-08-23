"""Historico da aba Dados: por PARTIDA, com todas as estatisticas e as medias.

A aba mostrava um agregado por liga ("N partidas com estatistica"), que nao
responde a pergunta que se faz olhando pra ela: o motor enxergou o jogo de
ontem, e enxergou INTEIRO? Liga com 3.000 jogos e liga com 4 apareciam iguais,
uma linha cada, e nenhuma das duas dizia QUAL jogo entrou nem o que faltou
dentro dele.

O que os testes daqui travam nao e' o visual, sao as tres coisas que erram
calado:

  · o teto de 40 corta no SQL, ANTES do OFFSET -- senao a pagina 4 fica mais
    cara que a 1 e a rota envelhece junto com `match_statistics`
  · o nome do time sai por LATERAL, porque `teams` tem uma linha POR
    TEMPORADA e um JOIN direto multiplicaria a partida
  · cobertura e media sao contas DIFERENTES e as duas precisam existir:
    cobertura nao ve' jogo coletado zerado (zero nao e' NULL) e media nao diz
    se saiu de 40 partidas ou de 2

Nada toca banco: o cursor e' dublê e guarda o SQL que recebeu.
"""

import os
import sys
from decimal import Decimal

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

import routers.admin as admin  # noqa: E402


def _resumo_cru(**kw):
    """A linha unica que a consulta de resumo devolve: dois campos por familia."""
    bruto = {}
    for chave, _rot, _casa, _fora, _modo in admin.STATS_DA_PARTIDA:
        bruto[f"{chave}_n"] = 40
        bruto[f"{chave}_m"] = Decimal("9.40")
    bruto["zeradas"] = 0
    return {**bruto, **kw}


def _partida(**kw):
    """Linha crua da consulta de partidas: colunas de banco, nao pares."""
    linha = {
        "fixture_id": 1, "data": "2026-08-22", "status": "FT",
        "referee": "Anderson Daronco", "coletada_em": "2026-08-22T23:10:00",
        "liga": "Brasileirao A", "mandante": "Flamengo", "visitante": "Palmeiras",
        "zerada": False,
    }
    for i, (_k, _r, casa, fora, _m) in enumerate(admin.STATS_DA_PARTIDA):
        linha[casa] = i + 1
        linha[fora] = i
    return {**linha, **kw}


class _FakeCursor:
    """Responde por trecho do SQL, nao por ordem: a rota pode reordenar as
    consultas sem quebrar o teste."""

    def __init__(self, total=40, linhas=None, resumo=None, explode=False):
        self._total = total
        self._linhas = linhas if linhas is not None else []
        self._resumo = resumo if resumo is not None else _resumo_cru()
        self._explode = explode
        self._rows = []
        self.sqls: list[str] = []
        self.params: list[tuple] = []

    def execute(self, sql, params=None):
        if self._explode:
            raise RuntimeError("banco fora do ar")
        self.sqls.append(sql)
        self.params.append(params)
        if "SELECT 1 FROM match_statistics" in sql:
            self._rows = [{"n": self._total}]
        elif "AS zeradas" in sql:
            self._rows = [self._resumo]
        else:
            self._rows = list(self._linhas)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, *_a, **_kw):
        return self._cursor

    def rollback(self):
        pass

    def close(self):
        pass


def _rodar(monkeypatch, pagina=0, por_pagina=10, total=40,
           linhas=None, resumo=None, explode=False):
    cur = _FakeCursor(total=total, linhas=linhas, resumo=resumo, explode=explode)
    monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
    saida = admin.partidas_coletadas(
        pagina=pagina, por_pagina=por_pagina,
        current_user={"id": 1, "plan": "admin"},
    )
    return saida, cur


def _sql_das_partidas(cur):
    for sql in cur.sqls:
        if "match_statistics ms" in sql:
            return sql
    raise AssertionError("a consulta de partidas nao rodou")


def _sql_do_resumo(cur):
    for sql in cur.sqls:
        if "AS zeradas" in sql:
            return sql
    raise AssertionError("a consulta de resumo nao rodou")


class TestOTetoEDoBanco:
    def test_a_contagem_para_no_quadragesimo(self, monkeypatch):
        """COUNT na tabela inteira seria varredura completa a cada troca de
        pagina pra devolver, no maximo, 40."""
        _, cur = _rodar(monkeypatch, linhas=[_partida()])
        contagem = next(s for s in cur.sqls if "SELECT 1 FROM match_statistics" in s)
        assert "LIMIT 40" in contagem

    def test_ultima_pagina_encolhe_em_vez_de_passar_do_teto(self, monkeypatch):
        """Pagina 3 de 15 comecaria no item 45. O LIMIT tem que virar 10, nao
        15, senao o "ultimas 40" mostra 45."""
        _, cur = _rodar(monkeypatch, pagina=2, por_pagina=15, linhas=[_partida()])
        limite, offset = cur.params[-1]
        assert (limite, offset) == (10, 30)

    def test_pagina_alem_do_teto_nao_consulta_partida_nenhuma(self, monkeypatch):
        """Nao e' so' devolver lista vazia: a consulta cara nao pode rodar."""
        saida, cur = _rodar(monkeypatch, pagina=4, por_pagina=10)
        assert saida["partidas"] == []
        assert not any("match_statistics ms" in s for s in cur.sqls)

    def test_resumo_sai_das_mesmas_40_que_a_lista(self, monkeypatch):
        """Media de um recorte e lista de outro seria comparar coisa diferente
        na mesma tela."""
        sql = _sql_do_resumo(_rodar(monkeypatch, linhas=[_partida()])[1])
        assert "LIMIT 40" in sql
        assert "ORDER BY match_date DESC, fixture_id DESC" in sql

    def test_total_nunca_passa_do_teto(self, monkeypatch):
        saida, _ = _rodar(monkeypatch, total=40, linhas=[_partida()])
        assert saida["total"] == 40
        assert saida["teto"] == 40


class TestEntradaDaQueryString:
    @pytest.mark.parametrize("pedido,esperado", [(999, 20), (0, 1), (-5, 1)])
    def test_por_pagina_fica_dentro_da_faixa(self, monkeypatch, pedido, esperado):
        """`por_pagina` vem da URL. Sem teto, `?por_pagina=100000` transforma a
        rota do painel numa varredura de tabela."""
        saida, _ = _rodar(monkeypatch, por_pagina=pedido, linhas=[_partida()])
        assert saida["por_pagina"] == esperado

    def test_pagina_negativa_vira_a_primeira(self, monkeypatch):
        """OFFSET negativo e' erro de SQL, nao pagina anterior."""
        saida, cur = _rodar(monkeypatch, pagina=-3, linhas=[_partida()])
        assert saida["pagina"] == 0
        assert cur.params[-1][1] == 0


class TestAConsulta:
    def test_nome_do_time_sai_por_lateral(self, monkeypatch):
        """`teams` tem UMA LINHA POR TEMPORADA por time. Um `JOIN teams ON
        team_id = ...` multiplica a partida por quantas temporadas o time
        tiver, e a pagina de 10 volta com 34 linhas."""
        _, cur = _rodar(monkeypatch, linhas=[_partida()])
        sql = _sql_das_partidas(cur)
        assert sql.count("LATERAL") == 2
        assert "ORDER BY season DESC LIMIT 1" in sql

    def test_ordem_desempata_pelo_fixture(self, monkeypatch):
        """`match_date` e' DATE pura: uma rodada inteira empata no mesmo dia. Sem
        desempate a paginacao repete e pula partida entre uma pagina e outra."""
        sql = _sql_das_partidas(_rodar(monkeypatch, linhas=[_partida()])[1])
        assert "ORDER BY ms.match_date DESC, ms.fixture_id DESC" in sql

    def test_nao_filtra_status(self, monkeypatch):
        """"Coletada" aqui e' ter linha na tabela. Jogo interrompido com
        estatistica gravada conta nas medias do motor igual aos outros ·
        esconder justo a linha esquisita e' esconder o problema."""
        sql = _sql_das_partidas(_rodar(monkeypatch, linhas=[_partida()])[1])
        assert "status IN" not in sql
        assert "ms.status" in sql, "o status precisa VIR, so' nao filtra"

    def test_toda_familia_do_catalogo_entra_no_select(self, monkeypatch):
        """A tela promete "todas as estatisticas que o banco tem". Familia nova
        em STATS_DA_PARTIDA que nao chegasse ao SELECT viraria coluna vazia na
        tela, que le como "o provedor nao mandou"."""
        sql = _sql_das_partidas(_rodar(monkeypatch, linhas=[_partida()])[1])
        for _k, _r, casa, fora, _m in admin.STATS_DA_PARTIDA:
            assert f"ms.{casa}" in sql
            assert f"ms.{fora}" in sql


class TestOQueVoltaPorPartida:
    def test_colunas_cruas_viram_par_casa_fora(self, monkeypatch):
        """A tela desenha "casa | fora" e nao deve conhecer nome de coluna."""
        saida, _ = _rodar(monkeypatch, linhas=[_partida(home_corners=7, away_corners=3)])
        p = saida["partidas"][0]
        assert p["stats"]["escanteios"] == [7, 3]
        assert "home_corners" not in p, "coluna crua nao pode vazar junto"

    def test_uma_entrada_por_familia(self, monkeypatch):
        saida, _ = _rodar(monkeypatch, linhas=[_partida()])
        assert len(saida["partidas"][0]["stats"]) == len(admin.STATS_DA_PARTIDA)
        assert saida["familias"] == len(admin.STATS_DA_PARTIDA)

    def test_completas_exige_os_dois_lados(self, monkeypatch):
        """Escanteio so' do mandante nao e' estatistica de partida: a media do
        jogo sairia pela metade. Meio preenchido conta como faltando."""
        saida, _ = _rodar(monkeypatch, linhas=[_partida(away_corners=None)])
        p = saida["partidas"][0]
        assert p["stats"]["escanteios"][1] is None
        assert p["completas"] == len(admin.STATS_DA_PARTIDA) - 1

    def test_arbitro_e_data_da_coleta_vem_junto(self, monkeypatch):
        """O arbitro alimenta baseline proprio no motor, e a data da coleta
        separa "o jogo e' velho" de "a leitura e' velha"."""
        sql = _sql_das_partidas(_rodar(monkeypatch, linhas=[_partida()])[1])
        assert "ms.referee" in sql
        assert "ms.last_updated" in sql


class TestMediasECobertura:
    def test_uma_entrada_por_familia_com_media_e_amostra(self, monkeypatch):
        """Media sem o n do lado nao serve: defesa de goleiro aparece em menos
        de 1% dos jogos, e media alta com n=2 e' amostra, nao tendencia."""
        saida, _ = _rodar(monkeypatch, linhas=[_partida()])
        assert len(saida["resumo"]) == len(admin.STATS_DA_PARTIDA)
        for f in saida["resumo"]:
            assert f["rotulo"]
            assert f["com_dado"] == 40
            assert f["media"] == pytest.approx(9.40)
            assert isinstance(f["media"], float), "Decimal nao serializa em JSON"

    def test_media_ausente_nao_vira_zero(self, monkeypatch):
        """AVG de coluna vazia volta NULL. Virar 0.0 diria "coletado e deu
        zero", que e' o oposto de "nunca foi coletado"."""
        saida, _ = _rodar(monkeypatch, linhas=[_partida()],
                          resumo=_resumo_cru(defesas_m=None, defesas_n=0))
        defesas = next(f for f in saida["resumo"] if f["chave"] == "defesas")
        assert defesas["media"] is None
        assert defesas["com_dado"] == 0

    def test_contagem_soma_os_dois_lados(self, monkeypatch):
        """O numero da PARTIDA e' casa + fora. Media so' do mandante seria
        metade do escanteio do jogo, com cara de numero certo."""
        sql = _sql_do_resumo(_rodar(monkeypatch, linhas=[_partida()])[1])
        assert "(home_corners + away_corners)" in sql

    def test_percentual_e_media_por_lado(self, monkeypatch):
        """Posse somada da' 100% em todo jogo, o que nao afere nada. Por lado
        ela vira instrumento: longe de 50 e' coleta torta, nao jogo estranho."""
        sql = _sql_do_resumo(_rodar(monkeypatch, linhas=[_partida()])[1])
        assert "((home_possession + away_possession) / 2.0)" in sql
        assert "((home_passes_accuracy + away_passes_accuracy) / 2.0)" in sql


class TestJogoColetadoVazio:
    def test_a_contagem_de_zeradas_sobe_pra_tela(self, monkeypatch):
        """99 partidas assim ja' existem no banco, 94 delas COM GOL: veio de
        `extract_stat` devolver 0 pra ausencia. Zero nao e' NULL, entao
        nenhuma metrica de cobertura acusa essas linhas."""
        saida, _ = _rodar(monkeypatch, linhas=[_partida()], resumo=_resumo_cru(zeradas=3))
        assert saida["zeradas"] == 3

    def test_a_marca_vem_por_partida_tambem(self, monkeypatch):
        """Saber que existem 3 nao ajuda se a lista nao diz QUAIS."""
        sql = _sql_das_partidas(_rodar(monkeypatch, linhas=[_partida()])[1])
        assert "AS zerada" in sql
        saida, _ = _rodar(monkeypatch, linhas=[_partida(zerada=True)])
        assert saida["partidas"][0]["zerada"] is True

    def test_a_regra_olha_escanteio_chute_e_falta(self, monkeypatch):
        """Uma so' das tres nao basta: jogo real termina com zero escanteio de
        vez em quando, mas nao com zero falta E zero chute junto."""
        for coluna in ("home_corners", "home_total_shots", "home_fouls"):
            assert coluna in admin._SQL_SUSPEITA


class TestFalha:
    def test_banco_fora_do_ar_nao_derruba_a_aba(self, monkeypatch):
        """A aba serve justamente pra quando alguma coisa esta errada."""
        saida, _ = _rodar(monkeypatch, explode=True)
        assert saida["partidas"] == []
        assert saida["resumo"] == []
        assert saida["total"] == 0
        assert "erro" in saida


def test_dados_nao_devolve_mais_agregado_por_liga(monkeypatch):
    """O bloco por liga saiu da tela; a consulta que o alimentava tambem.
    Agregar `match_statistics` por liga varria a tabela inteira a cada
    abertura da aba pra desenhar uma lista que ninguem acionava."""
    cur = _FakeCursor(linhas=[])
    monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
    saida = admin.dados_do_banco(current_user={"id": 1, "plan": "admin"})
    assert "por_liga" not in saida
    assert not any("GROUP BY l.league_id" in s for s in cur.sqls)


def test_dados_diz_quando_a_media_foi_recalculada(monkeypatch):
    """Sao dois relogios: `match_statistics` pode estar em dia e
    `team_statistics` parada em semana passada. O motor le' a segunda, entao a
    media fica velha sem nenhum sintoma na tela."""
    cur = _FakeCursor(linhas=[])
    monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
    admin.dados_do_banco(current_user={"id": 1, "plan": "admin"})
    assert any("FROM team_statistics" in s for s in cur.sqls)
