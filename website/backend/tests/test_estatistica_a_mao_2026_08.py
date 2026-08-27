"""A aba Dados deixou de ser so' vitrine: o buraco agora tem botao.

Ate' 2026-08-26 a tela contava "N partidas encerradas sem estatistica" e parava
ai'. Alarme sem botao: a saida era esperar a varredura automatica -- que so'
enxerga 3 dias e so' roda em producao -- ou rodar o pipeline inteiro por causa
de uma partida.

Sao tres saidas e elas tem ordem: RODAR (repergunta pra API), LINHA OCA (a API
nao tem folha e nao vai ter) e A MAO (digitar olhando a sumula). O que os
testes daqui travam nao e' a tela, sao as coisas que erram calado:

  · numero digitado a mao TEM que ficar marcado em `manual_stats` -- depois que
    entra na coluna ele e' indistinguivel do coletado, e o motor le' os dois
    igual
  · o total da familia e' refeito junto, e vira NULL se faltar um lado: parcela
    desconhecida, total desconhecido (mesma regra do `_sum_stats` do coletor)
  · linha oca nao pode ser criada sozinha -- a varredura procura jogo ENCERRADO
    SEM LINHA, entao a linha vazia esconderia a partida dela pra sempre
  · o backfill do vermelho e' de predicado ESTREITO, importado do script, nunca
    copiado pra ca'

Nada toca banco: o cursor e' duble e guarda o SQL que recebeu.
"""

import asyncio
import json
import os
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

import routers.admin as admin  # noqa: E402


ADMIN = {"id": 1, "plan": "admin", "email": "dono@site.com"}


class _FakeCursor:
    def __init__(self, linha=None, rowcount=0):
        self._linha = linha
        self.rowcount = rowcount
        self.sqls: list[str] = []
        self.params: list = []
        self._rows: list = []

    def execute(self, sql, params=None):
        self.sqls.append(sql)
        self.params.append(params)
        if "SELECT home_team_id" in sql or "SELECT fixture_id" in sql:
            self._rows = [self._linha] if self._linha else []
        elif "COUNT(*)" in sql:
            self._rows = [{"n": 7}]
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, *_a, **_kw):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def _editar(monkeypatch, valores, linha=None):
    """Roda a edicao manual com banco duble e sem recalculo de media."""
    if linha is None:
        linha = {"home_team_id": 10, "away_team_id": 20, "league_id": 71, "season": 2026}
    cur = _FakeCursor(linha=linha)
    conn = _FakeConn(cur)
    monkeypatch.setattr(admin, "get_connection", lambda: conn)
    monkeypatch.setattr(admin, "_recalcular_medias", lambda *a, **k: True)
    monkeypatch.setattr(admin, "_linha_da_partida", lambda _f: {"fixture_id": 999})
    saida = admin.editar_estatistica_manual(
        999, admin.EstatisticaManualBody(valores=valores), current_user=ADMIN)
    return saida, cur, conn


def _update(cur) -> tuple[str, tuple]:
    for sql, params in zip(cur.sqls, cur.params):
        if sql.strip().startswith("UPDATE match_statistics"):
            return sql, params
    raise AssertionError("o UPDATE nao rodou")


class TestOQueOCorpoAceita:
    def test_familia_desconhecida_e_recusada(self):
        """A chave vira NOME DE COLUNA no SQL. Aceitar chave livre aqui e'
        injecao com outro nome."""
        with pytest.raises(ValueError):
            admin.EstatisticaManualBody(valores={"vitorias_do_juiz": [1, 2]})

    def test_par_tem_que_ter_dois_lados(self):
        with pytest.raises(ValueError):
            admin.EstatisticaManualBody(valores={"escanteios": [5]})

    def test_negativo_nao_passa(self):
        with pytest.raises(ValueError):
            admin.EstatisticaManualBody(valores={"faltas": [-1, 3]})

    def test_digito_trocado_esbarra_no_teto(self):
        """55 escanteios num jogo e' tecla presa, e numero torto no banco nao
        para na partida: vira baseline torto da liga inteira."""
        with pytest.raises(ValueError):
            admin.EstatisticaManualBody(valores={"escanteios": [550, 4]})

    def test_posse_nao_passa_de_cem(self):
        with pytest.raises(ValueError):
            admin.EstatisticaManualBody(valores={"posse": [140, 60]})

    def test_vazio_nao_e_edicao(self):
        with pytest.raises(ValueError):
            admin.EstatisticaManualBody(valores={})

    def test_nulo_e_permitido_porque_e_o_desfazer(self):
        """Campo em branco apaga o numero de volta pra ausencia · e' como se
        desfaz um valor digitado errado sem inventar zero no lugar."""
        corpo = admin.EstatisticaManualBody(valores={"escanteios": [None, None]})
        assert corpo.valores["escanteios"] == [None, None]


class TestOQueVaiPraColuna:
    def test_grava_os_dois_lados_da_familia(self, monkeypatch):
        _, cur, _ = _editar(monkeypatch, {"escanteios": [7, 4]})
        sql, params = _update(cur)
        assert "home_corners = %s" in sql and "away_corners = %s" in sql
        assert 7 in params and 4 in params

    def test_total_da_familia_e_refeito(self, monkeypatch):
        """O motor le' as duas: o pool de cartoes sai de `total_yellow_cards`,
        a media de escanteio da liga sai de `total_corners`. Gravar o lado sem
        refazer o total deixa a linha incoerente consigo mesma."""
        _, cur, _ = _editar(monkeypatch, {"escanteios": [7, 4]})
        sql, params = _update(cur)
        assert "total_corners = %s" in sql
        assert 11 in params

    def test_total_vira_nulo_quando_falta_um_lado(self, monkeypatch):
        """Parcela desconhecida, total desconhecido · mesma regra do
        `_sum_stats` do coletor. Somar tratando o None como zero fabricaria um
        total, e zero fabricado vira pick errado."""
        _, cur, _ = _editar(monkeypatch, {"amarelos": [3, None]})
        sql, params = _update(cur)
        alvo = sql.index("total_yellow_cards = %s")
        # a posicao do %s do total na lista de parametros
        indice = sql[:alvo].count("%s")
        assert params[indice] is None

    def test_familia_sem_total_nao_inventa_coluna(self, monkeypatch):
        """Falta nao tem coluna de total no banco. Um `total_fouls = %s` aqui
        derruba a rota inteira com erro de coluna inexistente."""
        _, cur, _ = _editar(monkeypatch, {"faltas": [12, 15]})
        sql, _ = _update(cur)
        assert "total_" not in sql.split("manual_stats")[0]

    def test_totais_declarados_existem_em_stats_da_partida(self):
        """Guarda contra digitacao: _TOTAL_DA_FAMILIA aponta pra chave de
        familia, e chave errada la' vira coluna que nunca e' atualizada."""
        chaves = {c for c, _r, _ca, _f, _m in admin.STATS_DA_PARTIDA}
        assert set(admin._TOTAL_DA_FAMILIA) <= chaves


class TestAMarcaDeQueFoiAMao:
    def test_registra_valor_autor_e_data(self, monkeypatch):
        _, cur, _ = _editar(monkeypatch, {"escanteios": [7, 4]})
        sql, params = _update(cur)
        assert "manual_stats" in sql
        marca = json.loads(next(p for p in params if isinstance(p, str) and "escanteios" in p))
        assert marca["escanteios"]["casa"] == 7
        assert marca["escanteios"]["fora"] == 4
        assert marca["escanteios"]["por"] == "dono@site.com"
        assert marca["escanteios"]["em"]

    def test_soma_a_marca_em_vez_de_trocar(self, monkeypatch):
        """`=` no lugar de `||` apagaria a marca da edicao anterior: a segunda
        estatistica preenchida a mao faria a primeira parecer coletada."""
        _, cur, _ = _editar(monkeypatch, {"escanteios": [7, 4]})
        sql, _ = _update(cur)
        assert "COALESCE(manual_stats, '{}'::jsonb) || %s::jsonb" in sql

    def test_last_updated_sobe_junto(self, monkeypatch):
        """E' o que faz o coletor parar de voltar nesta partida (predicado de
        "estabilizado" em _load_fixtures) · folha completada a mao nao gasta
        requisicao na proxima coleta em lote."""
        _, cur, _ = _editar(monkeypatch, {"escanteios": [7, 4]})
        sql, _ = _update(cur)
        assert "last_updated = NOW()" in sql

    def test_recalcula_a_media_dos_dois_times(self, monkeypatch):
        """Escrever em `match_statistics` e nao refazer a media deixa o motor
        lendo a media de ontem sobre um historico de hoje -- o pior dos dois
        mundos, porque parece atualizado."""
        chamadas = []
        cur = _FakeCursor(linha={"home_team_id": 10, "away_team_id": 20,
                                 "league_id": 71, "season": 2026})
        monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
        monkeypatch.setattr(admin, "_linha_da_partida", lambda _f: None)
        monkeypatch.setattr(admin, "_recalcular_medias",
                            lambda *a: chamadas.append(a) or True)
        admin.editar_estatistica_manual(
            999, admin.EstatisticaManualBody(valores={"faltas": [12, 15]}),
            current_user=ADMIN)
        assert chamadas == [(10, 20, 71, 2026)]


class TestPartidaQueNaoTemLinha:
    def test_recusa_com_recado_de_rodar_primeiro(self, monkeypatch):
        """Criar a linha a mao nasceria com placar inventado, e placar
        inventado liquida pick. Quem cria a linha e' o botao Rodar, com o
        placar vindo de /fixtures."""
        from fastapi import HTTPException
        cur = _FakeCursor(linha=None)
        monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
        with pytest.raises(HTTPException) as e:
            admin.editar_estatistica_manual(
                999, admin.EstatisticaManualBody(valores={"faltas": [1, 2]}),
                current_user=ADMIN)
        assert e.value.status_code == 404
        assert not any(s.strip().startswith("UPDATE") for s in cur.sqls)


class _ServicoFalso:
    ultima: dict = {}

    def sync_one_fixture(self, fixture_id, criar_sem_folha=False):
        _ServicoFalso.ultima = {"fixture_id": fixture_id, "criar_sem_folha": criar_sem_folha}
        return {"fixture_id": fixture_id, "situacao": _ServicoFalso.situacao}


def _coletar(monkeypatch, situacao, **kw):
    _ServicoFalso.situacao = situacao
    monkeypatch.setattr(admin, "_no_path", lambda: None)
    monkeypatch.setattr(admin, "_linha_da_partida", lambda _f: {
        "fixture_id": 1, "home_team_id": 10, "away_team_id": 20,
        "league_id": 71, "season": 2026, "completas": 16})
    monkeypatch.setattr(admin, "_recalcular_medias", lambda *a: True)

    import types
    modulo = types.ModuleType("collectors.match_statistics_sync_service")
    modulo.MatchStatisticsSyncService = _ServicoFalso
    pacote = types.ModuleType("collectors")
    monkeypatch.setitem(sys.modules, "collectors", pacote)
    monkeypatch.setitem(sys.modules, "collectors.match_statistics_sync_service", modulo)

    return asyncio.run(admin.coletar_partida(1, current_user=ADMIN, **kw))


class TestBotaoRodar:
    def test_folha_coletada_recalcula_a_media(self, monkeypatch):
        saida = _coletar(monkeypatch, "gravada")
        assert saida["ok"] is True
        assert saida["medias_recalculadas"] is True
        assert saida["partida"]["completas"] == 16

    def test_sem_folha_nao_e_sucesso_e_diz_por_que(self, monkeypatch):
        saida = _coletar(monkeypatch, "sem_folha")
        assert saida["ok"] is False
        assert "folha" in saida["mensagem"].lower()
        assert saida["partida"] is None

    def test_linha_oca_so_com_o_pedido_explicito(self, monkeypatch):
        """A varredura procura jogo ENCERRADO SEM LINHA. Linha oca criada
        sozinha esconderia a partida dela pra sempre."""
        _coletar(monkeypatch, "gravada")
        assert _ServicoFalso.ultima["criar_sem_folha"] is False
        _coletar(monkeypatch, "linha_sem_folha", criar_sem_folha=True)
        assert _ServicoFalso.ultima["criar_sem_folha"] is True

    def test_jogo_em_andamento_nao_vira_erro_de_sistema(self, monkeypatch):
        """Nao ha' nada a coletar, e isso e' uma resposta · nao um 500."""
        saida = _coletar(monkeypatch, "nao_finalizada")
        assert saida["ok"] is False
        assert "terminou" in saida["mensagem"]


class TestListaDeBuracos:
    def _rodar(self, monkeypatch, limite=30):
        cur = _FakeCursor()
        monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
        saida = admin.buracos_de_estatistica(limite=limite, current_user=ADMIN)
        return saida, cur

    def test_nome_do_time_sai_da_propria_fixture(self, monkeypatch):
        """A partida orfa e' justamente a que pode ter time nao cadastrado · um
        JOIN com `teams` devolveria "Time ?" bem no caso que interessa."""
        _, cur = self._rodar(monkeypatch)
        sql = cur.sqls[0]
        assert "f.home_team" in sql and "f.away_team" in sql
        assert "JOIN teams" not in sql

    def test_so_encerrada_e_sem_linha(self, monkeypatch):
        _, cur = self._rodar(monkeypatch)
        sql = cur.sqls[0]
        assert "f.status IN ('FT','AET','PEN')" in sql
        assert "ms.fixture_id IS NULL" in sql

    @pytest.mark.parametrize("pedido,esperado", [(9999, 100), (0, 1), (-5, 1)])
    def test_limite_fica_dentro_da_faixa(self, monkeypatch, pedido, esperado):
        """`limite` vem da URL. Sem teto, `?limite=100000` transforma a rota do
        painel numa varredura de tabela."""
        saida, cur = self._rodar(monkeypatch, limite=pedido)
        assert saida["limite"] == esperado
        assert cur.params[0] == (esperado,)


class TestVermelhoLegado:
    def test_o_predicado_vem_do_script(self):
        """A regra do backfill mora em scripts/backfill_cartao_vermelho.py.
        Copiar o predicado pra ca' criaria duas verdades sobre quando um NULL
        de vermelho pode virar zero -- e uma delas envelheceria."""
        alvo = admin._alvo_vermelho()
        from scripts.backfill_cartao_vermelho import _ALVO
        assert alvo is _ALVO

    def test_a_regra_e_estreita(self):
        """So' entra a linha com a folha COMPLETA no resto: essa combinacao so'
        sai do coletor lendo uma folha publicada, ou seja, a API respondeu e
        disse que nao houve expulsao. Folha de fato incompleta continua NULL."""
        alvo = " ".join(admin._alvo_vermelho().split())
        for coluna in ("total_corners", "total_yellow_cards", "home_fouls",
                       "home_total_shots"):
            assert f"{coluna} IS NOT NULL" in alvo
        assert "home_red_cards IS NULL" in alvo

    def test_contagem_separa_alvo_de_folha_incompleta(self, monkeypatch):
        """Mostrar so' o alvo faria o backfill parecer que "deixou linha pra
        tras" quando sobrasse jogo sem folha nenhuma."""
        cur = _FakeCursor()
        monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
        saida = admin.vermelho_legado(current_user=ADMIN)
        assert saida["disponivel"] is True
        assert saida["folha_incompleta"] == max(0, saida["sem_vermelho"] - saida["alvo"])

    def test_correcao_refaz_a_media_do_arbitro_na_mesma_transacao(self, monkeypatch):
        """AVG ignora NULL, entao a media de vermelho do arbitro saia tirada
        SO' dos jogos com expulsao. Corrigir a partida e deixar
        `referee_stats.avg_red` inflado troca um numero errado por outro."""
        passos = []
        cur = _FakeCursor()
        conn = _FakeConn(cur)
        monkeypatch.setattr(admin, "get_connection", lambda: conn)
        monkeypatch.setattr(admin, "_no_path", lambda: None)

        import scripts.backfill_cartao_vermelho as script
        monkeypatch.setattr(script, "_aplicar", lambda c: passos.append("aplicar") or 12)
        monkeypatch.setattr(script, "_recalcular_arbitros", lambda c: passos.append("arbitros") or 5)

        saida = admin.corrigir_vermelho_legado(current_user=ADMIN)
        assert passos == ["aplicar", "arbitros"]
        assert conn.commits == 1
        assert saida == {"ok": True, "corrigidas": 12, "arbitros": 5}


class TestDefinicaoDeFolhaCompleta:
    """A mesma definicao nos dois lados, ou o painel manda recoletar o que o
    coletor considera pronto -- e queima cota pra receber a folha identica."""

    def _colunas_do_coletor(self):
        import re
        caminho = os.path.join(
            admin._PIPELINE_DIR, "collectors", "match_statistics_sync_service.py")
        with open(caminho, encoding="utf-8-sig") as fh:
            fonte = fh.read()
        inicio = fonte.index("Remove os que já têm a folha COMPLETA")
        trecho = fonte[inicio:inicio + 900]
        return set(re.findall(r"(\w+) IS NOT NULL", trecho))

    def test_as_colunas_batem_com_as_do_coletor(self):
        assert set(admin._COLUNAS_DA_FOLHA) == self._colunas_do_coletor()

    def test_nao_exige_as_dezesseis_familias(self):
        """Defesa de goleiro aparece em menos de 1% das folhas · exigir as 16
        marcaria a tabela inteira como incompleta e mandaria recoletar milhares
        de partidas pra receber exatamente o mesmo vazio."""
        assert len(admin._COLUNAS_DA_FOLHA) < len(admin.STATS_DA_PARTIDA)
        assert "home_goalkeeper_saves" not in admin._COLUNAS_DA_FOLHA


class TestRecoletaEmLote:
    def _limpar(self):
        admin._recoleta.update({"rodando": False, "total": 0, "feitas": 0,
                                "gravadas": 0, "falhas": 0, "erro": None})

    def test_recusa_lote_concorrente(self, monkeypatch):
        """Duas recoletas ao mesmo tempo dobram o consumo de cota por minuto e
        disputam a mesma linha no banco."""
        from fastapi import HTTPException
        self._limpar()
        admin._recoleta["rodando"] = True
        try:
            with pytest.raises(HTTPException) as e:
                asyncio.run(admin.recoletar_em_lote(current_user=ADMIN))
            assert e.value.status_code == 409
        finally:
            self._limpar()

    def test_teto_de_partidas_por_lote(self, monkeypatch):
        """Cada partida custa DUAS requisicoes. Sem teto, um `?limite=100000`
        no painel repete o estouro de cota de 2026-08-01."""
        self._limpar()
        pedidos = []
        monkeypatch.setattr(admin, "_ids_para_recoletar",
                            lambda limite, meses: pedidos.append((limite, meses)) or [])
        asyncio.run(admin.recoletar_em_lote(limite=99999, meses=999, current_user=ADMIN))
        assert pedidos == [(admin._RECOLETA_TETO, 24)]

    def test_lista_vazia_nao_abre_thread(self, monkeypatch):
        self._limpar()
        monkeypatch.setattr(admin, "_ids_para_recoletar", lambda *a: [])
        saida = asyncio.run(admin.recoletar_em_lote(current_user=ADMIN))
        assert saida["total"] == 0
        assert admin._recoleta["rodando"] is False

    def test_avisa_o_custo_em_requisicoes(self, monkeypatch):
        """O numero que importa antes de clicar nao e' o de partidas."""
        self._limpar()
        monkeypatch.setattr(admin, "_ids_para_recoletar", lambda *a: [1, 2, 3])
        monkeypatch.setattr(admin.threading, "Thread",
                            lambda *a, **k: type("T", (), {"start": lambda s: None})())
        saida = asyncio.run(admin.recoletar_em_lote(current_user=ADMIN))
        self._limpar()
        assert "6 requisições" in saida["mensagem"]

    def test_alvo_junta_folha_furada_e_partida_sem_linha(self, monkeypatch):
        """Pra quem opera as duas sao o mesmo problema: o motor nao viu o jogo.
        Tenha a linha nascido incompleta ou nao tenha nascido."""
        cur = _FakeCursor()
        monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
        admin._ids_para_recoletar(20, 3)
        sql = cur.sqls[0]
        assert "UNION" in sql
        assert "m2.fixture_id IS NULL" in sql
        assert "ORDER BY match_date DESC" in sql


class TestDiagnostico:
    def test_janela_de_meses_fica_dentro_da_faixa(self, monkeypatch):
        cur = _FakeCursor()
        monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
        assert admin.diagnostico_da_folha(meses=999, current_user=ADMIN)["meses"] == 60
        assert admin.diagnostico_da_folha(meses=0, current_user=ADMIN)["meses"] == 1

    def test_conta_as_dezesseis_familias(self, monkeypatch):
        """O diagnostico mostra TODAS as familias, mesmo as que nao entram na
        definicao de folha completa · e' o unico lugar que enxerga o buraco de
        posse, impedimento ou passe."""
        cur = _FakeCursor()
        monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
        admin.diagnostico_da_folha(current_user=ADMIN)
        sql = cur.sqls[0]
        for chave, _r, _c, _f, _m in admin.STATS_DA_PARTIDA:
            assert f"AS {chave}_n" in sql
            assert f"AS {chave}_desde" in sql
