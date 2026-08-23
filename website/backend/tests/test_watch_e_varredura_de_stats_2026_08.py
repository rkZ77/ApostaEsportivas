"""Duas automacoes que precisavam sobreviver ao mundo real.

1 · O LACO DO MOTOR AO VIVO NAO CONTAVA QUE TINHA CAIDO

O estado vivia so' na memoria do processo. Toda morte DENTRO do processo grava
motivo (disjuntor de falhas, cancelamento, desligar no painel); o processo
morrer inteiro nao gravava nada -- o modulo recarregava zerado e o painel
voltava dizendo "desligado, 0 rodadas, sem motivo". O Railway recicla container
por conta propria, entao quem ligava via cair "sozinho", sem bilhete.

2 · A ESTATISTICA SO' ENTRAVA NO CLIQUE

`match_statistics` so' enchia quando alguem abria o /admin. E' dela que saem os
baselines do motor, entao jogo encerrado sem estatistica e' partida que
aconteceu e o motor nao viu -- sem sintoma, so' media velha.

A varredura copia a forma que a resolucao de picks ja' usa: puxada por VISITA,
com freios em ordem de custo, e NUNCA um agendador -- agendador foi removido
deste backend em 2026-08-01 depois de a cota estourar, e a decisao vale.
"""
import inspect

import pytest

import stats_sweep
from routers import live_picks


class TestOLacoDeixaBilhete:
    def test_o_processo_tem_identidade(self):
        """Sem `boot_id` nao da' pra separar "reiniciou" de "alguem desligou":
        os dois deixam a linha com ativo=False."""
        assert live_picks._BOOT_ID
        assert len(live_picks._BOOT_ID) >= 16

    def test_grava_em_todo_ponto_de_saida(self):
        """Ligar, cada rodada, desligar no painel e o `finally` do laco · se um
        deles nao gravar, o banco fica contando uma historia diferente da
        memoria."""
        fonte = inspect.getsource(live_picks)
        assert fonte.count("_salvar_watch()") >= 4

    def test_falha_de_banco_nao_derruba_a_rodada(self, monkeypatch):
        """A tabela pode nem existir · `run_migrations()` nao roda sozinha
        depois de um merge. Sem ela o painel volta a se comportar como antes,
        que e' ruim mas conhecido; estourar no meio da rodada seria pior.
        """
        def explode(*a, **k):
            raise RuntimeError("sem tabela")
        monkeypatch.setattr(live_picks, "get_connection", explode)
        live_picks._salvar_watch()          # nao pode levantar
        assert live_picks.reconciliar_watch_no_boot() is None

    def test_reconciliacao_ignora_linha_do_proprio_processo(self, monkeypatch):
        """Se o dono da linha sou eu, o laco esta vivo · nao ha queda a relatar."""
        linha = {"ativo": True, "boot_id": live_picks._BOOT_ID, "rodadas": 3,
                 "ultimo_sinal": None, "intervalo_min": 8, "dry_run": True,
                 "max_partidas": None}
        monkeypatch.setattr(live_picks, "get_connection",
                            lambda: _conexao_fake(linha))
        assert live_picks.reconciliar_watch_no_boot() is None

    def test_linha_de_outro_processo_vira_motivo_legivel(self, monkeypatch):
        from datetime import datetime
        linha = {"ativo": True, "boot_id": "outro-processo", "rodadas": 9,
                 "ultimo_sinal": datetime(2026, 8, 22, 14, 32),
                 "intervalo_min": 8, "dry_run": True, "max_partidas": None}
        monkeypatch.setattr(live_picks, "get_connection",
                            lambda: _conexao_fake(linha))
        monkeypatch.setattr(live_picks, "_salvar_watch", lambda *a, **k: None)

        achado = live_picks.reconciliar_watch_no_boot()
        assert achado is not None
        motivo = live_picks._watch_state["motivo_parada"]
        assert "reiniciou" in motivo
        assert "22/08 14:32" in motivo and "9 rodada" in motivo
        assert live_picks._watch_state["ativo"] is False


class TestRearmeENaoPadrao:
    """"Nada sobe ligado" foi o que se estabeleceu quando o scheduler saiu, em
    2026-08-01, depois de a cota da API estourar. Religar sozinho tem que ser
    pedido de quem opera, nao efeito colateral de um deploy."""

    def test_desligado_sem_variavel(self, monkeypatch):
        monkeypatch.delenv("LIVE_WATCH_REARM", raising=False)
        assert live_picks._rearmar_apos_restart() is False

    @pytest.mark.parametrize("valor", ["true", "1", "on", "sim", "YES"])
    def test_liga_com_a_variavel(self, monkeypatch, valor):
        monkeypatch.setenv("LIVE_WATCH_REARM", valor)
        assert live_picks._rearmar_apos_restart() is True

    @pytest.mark.parametrize("valor", ["false", "0", "off", "", "talvez"])
    def test_qualquer_outra_coisa_e_desligado(self, monkeypatch, valor):
        monkeypatch.setenv("LIVE_WATCH_REARM", valor)
        assert live_picks._rearmar_apos_restart() is False


class TestVarreduraDeEstatistica:
    def test_nao_e_agendador(self):
        """O gatilho e' a visita. Se aparecer laco proprio ou sleep de relogio
        aqui, viramos o scheduler que foi removido."""
        fonte = inspect.getsource(stats_sweep)
        assert "while True" not in fonte
        assert "schedule" not in fonte.lower()

    def test_so_roda_em_producao(self, monkeypatch):
        """A chave da API-Football e' uma conta so' pros tres ambientes · dev
        aberto consumiria a cota do site real."""
        monkeypatch.delenv("STATS_SWEEP", raising=False)
        monkeypatch.setattr("runtime_env.is_production", lambda: False)
        assert stats_sweep._habilitada() is False

    def test_variavel_desliga_em_qualquer_ambiente(self, monkeypatch):
        monkeypatch.setenv("STATS_SWEEP", "off")
        monkeypatch.setattr("runtime_env.is_production", lambda: True)
        monkeypatch.setattr("runtime_env.side_effects_enabled", lambda: True)
        assert stats_sweep._habilitada() is False

    def test_desabilitada_nao_consulta_banco(self, monkeypatch):
        """O freio mais barato tem que vir primeiro."""
        monkeypatch.setattr(stats_sweep, "_habilitada", lambda: False)
        def nao_devia(*a, **k):
            raise AssertionError("consultou o banco com a varredura desligada")
        monkeypatch.setattr(stats_sweep, "_ha_jogo_sem_estatistica", nao_devia)
        stats_sweep.maybe_sync_finished_stats()

    def test_intervalo_segura_a_segunda_visita(self, monkeypatch):
        """Duas visitas seguidas nao viram duas coletas."""
        monkeypatch.setattr(stats_sweep, "_habilitada", lambda: True)
        chamadas = {"n": 0}
        def contar():
            chamadas["n"] += 1
            return False
        monkeypatch.setattr(stats_sweep, "_ha_jogo_sem_estatistica", contar)
        stats_sweep._estado.update({"ultima": 0.0, "rodando": False})

        stats_sweep.maybe_sync_finished_stats()
        stats_sweep.maybe_sync_finished_stats()
        assert chamadas["n"] == 1

    def test_sem_buraco_no_banco_nao_chama_api(self, monkeypatch):
        monkeypatch.setattr(stats_sweep, "_habilitada", lambda: True)
        monkeypatch.setattr(stats_sweep, "_ha_jogo_sem_estatistica", lambda: False)
        def nao_devia(*a, **k):
            raise AssertionError("foi pra API sem ter o que coletar")
        monkeypatch.setattr(stats_sweep, "_coletar", nao_devia)
        stats_sweep._estado.update({"ultima": 0.0, "rodando": False})
        stats_sweep.maybe_sync_finished_stats()
        assert stats_sweep._estado["rodando"] is False

    def test_o_estado_serve_pro_painel(self):
        estado = stats_sweep.estado_da_varredura()
        assert set(estado) >= {"habilitada", "intervalo_s", "janela_dias", "rodando"}


def _conexao_fake(linha):
    class Cur:
        def execute(self, *a, **k): pass
        def fetchone(self): return linha
        def close(self): pass
    class Conn:
        def cursor(self): return Cur()
        def commit(self): pass
        def close(self): pass
    return Conn()
