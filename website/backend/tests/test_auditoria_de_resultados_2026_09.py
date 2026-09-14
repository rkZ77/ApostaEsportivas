"""Auditoria dos resultados do mês · o que ela pergunta, e de onde tira a conta.

Ela existe ao lado da reconferência (`reverify-stats-results`), não no lugar
dela: aquela pergunta o número do jogo pra API, uma requisição por fixture, e
corrige. Esta não fala com o provedor e não escreve nada -- confere o banco
contra ele mesmo, que é onde estavam quase todos os defeitos de liquidação
achados até aqui: bilhete que não bate com as próprias pernas, perna deixada em
aberto, lucro que não corresponde ao resultado, seguidor dessincronizado.

A conta do bilhete sai de `settlement.combine_legs`, a mesma que liquida. Uma
segunda aritmética aqui só poderia divergir da primeira, e auditoria que
discorda do sistema por conta própria não vale nada.
"""
import os
import sys
from datetime import date

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from routers import admin
from settlement_bridge import settlement


# ── 1 · a janela do mês ─────────────────────────────────────────────────────
class TestJanelaDoMes:
    def test_mes_pedido_comeca_no_dia_1(self):
        inicio, _fim, rotulo = admin._mes_em_datas("2026-07")
        assert inicio == date(2026, 7, 1)
        assert rotulo == "2026-07"

    def test_mes_fechado_vai_ate_o_ultimo_dia(self):
        assert admin._mes_em_datas("2026-07")[1] == date(2026, 7, 31)

    def test_virada_de_ano(self):
        assert admin._mes_em_datas("2026-12")[1] == date(2026, 12, 31)

    def test_mes_corrente_para_em_hoje(self):
        # Pick de jogo que ainda não aconteceu não é pendência · o fim da
        # janela é hoje, nunca o fim do mês.
        hoje = admin._hoje_br()
        inicio, fim, _r = admin._mes_em_datas(None)
        assert inicio == hoje.replace(day=1)
        assert fim == hoje

    def test_mes_invalido_vira_erro_de_pedido(self):
        import pytest
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            admin._mes_em_datas("julho")
        assert e.value.status_code == 400


# ── 2 · o lucro que o resultado obriga ──────────────────────────────────────
class TestLucroEsperado:
    def test_green_paga_a_odd_menos_a_entrada(self):
        assert admin._lucro_esperado("GREEN", 2.50) == 1.50

    def test_red_custa_a_entrada(self):
        assert admin._lucro_esperado("RED", 2.50) == -1.0

    def test_push_devolve(self):
        assert admin._lucro_esperado("PUSH", 2.50) == 0.0

    def test_meia_green_paga_metade(self):
        assert admin._lucro_esperado("HALF-WIN", 3.00) == 1.0

    def test_meia_red_custa_metade(self):
        assert admin._lucro_esperado("HALF-LOSS", 3.00) == -0.5

    def test_sem_odd_nao_ha_o_que_esperar_de_green(self):
        # Sem a odd não dá pra dizer quanto o GREEN pagou · a auditoria cala em
        # vez de acusar divergência que ela mesma inventou.
        assert admin._lucro_esperado("GREEN", None) is None
        assert admin._lucro_esperado("RED", None) == -1.0


# ── 3 · o bilhete conferido pelas próprias pernas ───────────────────────────
class TestBilheteContraAsPernas:
    def test_o_caso_de_13_09_e_apontado(self):
        # Múltipla RED com a segunda perna em aberto: as pernas não fecham
        # conta nenhuma, e é isso que o motivo "perna sem resultado" diz.
        vereditos = ["RED", None]
        assert any(v not in settlement.RESULT_LABELS for v in vereditos)

    def test_bilhete_green_com_perna_red_e_divergencia(self):
        combinado, _lucro, _eff = settlement.combine_legs(
            ["GREEN", "RED"], [1.40, 1.80], 2.52)
        assert combinado == "RED", "gravar GREEN nesse bilhete seria o achado"

    def test_perna_anulada_nao_derruba_o_bilhete(self):
        # PUSH sai da conta com fator 1 · o bilhete passa a pagar só a perna que
        # sobrou, e a auditoria tem que esperar exatamente esse número.
        combinado, lucro, _eff = settlement.combine_legs(
            ["GREEN", "PUSH"], [1.40, 1.80], 2.52)
        assert combinado == "GREEN"
        assert round(float(lucro), 2) == 0.40

    def test_a_auditoria_usa_a_fonte_unica(self):
        import inspect
        fonte = inspect.getsource(admin.admin_auditoria_resultados)
        assert "settlement.combine_legs" in fonte, (
            "recombinar o bilhete com aritmética própria é como nasceram as "
            "duas liquidações que divergiam")

    def test_a_auditoria_nao_escreve(self):
        import inspect
        fonte = inspect.getsource(admin.admin_auditoria_resultados)
        for proibido in ("UPDATE ", "INSERT ", "DELETE "):
            assert proibido not in fonte.upper(), (
                "auditoria que corrige por conta própria deixa de ser auditoria")


# ── 4 · a conferência contra a estatística do jogo ──────────────────────────
class _CursorDeUmaFolha:
    """Cursor mínimo que devolve sempre a mesma linha."""

    def __init__(self, linha):
        self._linha = linha

    def execute(self, sql, args=None):
        pass

    def fetchone(self):
        return self._linha


class TestFolhaDaPartida:
    def test_folha_completa_e_a_do_coletor(self):
        cheia = dict.fromkeys(admin._CONTADORES_DA_FOLHA, 3)
        cheia.update(status="FT", total_goals=2, home_goals_ht=1, away_goals_ht=0)
        assert _folha(cheia)["completa"] is True

    def test_um_contador_nulo_ja_e_folha_incompleta(self):
        # Mesmo corte do coletor · acusar divergência com folha pela metade
        # seria acusar o pick por uma falha da coleta.
        meia = dict.fromkeys(admin._CONTADORES_DA_FOLHA, 3)
        meia["home_fouls"] = None
        meia.update(status="FT", total_goals=2, home_goals_ht=1, away_goals_ht=0)
        assert _folha(meia)["completa"] is False

    def test_sem_linha_no_banco_nao_ha_folha(self):
        assert admin._folha_da_partida(_CursorDeUmaFolha(None), 123) is None


def _folha(linha):
    return admin._folha_da_partida(_CursorDeUmaFolha(linha), 123)


class TestBoostPelaFolha:
    def _folha(self, total, ht_casa, ht_fora, status="FT"):
        return {"status": status, "total_goals": total,
                "home_goals_ht": ht_casa, "away_goals_ht": ht_fora}

    def test_as_duas_pernas_pagam(self):
        assert admin._resultado_do_boost(self._folha(3, 1, 0)) == ("GREEN", "GREEN", "GREEN")

    def test_uma_perna_vermelha_derruba_o_bilhete(self):
        # Over 1.5 bate, mas o primeiro tempo teve 3 gols · o Boost é RED.
        assert admin._resultado_do_boost(self._folha(4, 2, 1)) == ("RED", "GREEN", "RED")

    def test_jogo_travado_em_um_gol(self):
        assert admin._resultado_do_boost(self._folha(1, 1, 0)) == ("RED", "RED", "GREEN")

    def test_prorrogacao_nao_e_conferida(self):
        # `total_goals` traz o tempo extra somado e a casa liquida pelos 90:
        # o número da folha não responde a pergunta.
        assert admin._resultado_do_boost(self._folha(3, 1, 0, status="AET"))[0] is None

    def test_sem_placar_do_intervalo_nao_afirma_nada(self):
        assert admin._resultado_do_boost(self._folha(3, None, None))[0] is None


class TestJogadorPelaFolha:
    def _pick(self, **extra):
        base = {"stat_column": "shots_on", "fixture_id": 1, "player_id": 9, "line_value": 2}
        base.update(extra)
        return base

    def test_linha_batida_e_green(self):
        cur = _CursorDeUmaFolha({"valor": 3, "minutes": 61})
        assert admin._resultado_do_jogador(cur, self._pick()) == "GREEN"

    def test_null_no_contador_de_quem_jogou_e_zero(self):
        # A API omite o zero em vez de escrevê-lo · quem entrou em campo e não
        # finalizou tem `null`, e isso é zero.
        cur = _CursorDeUmaFolha({"valor": None, "minutes": 90})
        assert admin._resultado_do_jogador(cur, self._pick()) == "RED"

    def test_titular_substituido_abaixo_da_linha_nao_e_afirmado(self):
        # O pick acompanha a VAGA: o que o substituto fizer soma, e buscar isso
        # custa requisição. A auditoria cala em vez de acusar um RED que pode
        # ter virado GREEN no banco de reservas.
        cur = _CursorDeUmaFolha({"valor": 1, "minutes": 58})
        assert admin._resultado_do_jogador(cur, self._pick()) is None

    def test_quem_nao_entrou_nao_tem_o_que_ler(self):
        cur = _CursorDeUmaFolha({"valor": None, "minutes": None})
        assert admin._resultado_do_jogador(cur, self._pick()) is None

    def test_coluna_fora_da_lista_nao_vira_sql(self):
        cur = _CursorDeUmaFolha({"valor": 9, "minutes": 90})
        assert admin._resultado_do_jogador(cur, self._pick(stat_column="1=1; DROP")) is None


class TestTodosOsProdutos:
    def test_nenhum_produto_fica_sem_conferencia_pela_folha(self):
        import inspect
        fonte = inspect.getsource(admin.admin_auditoria_resultados)
        # Os cinco de perna única, os dois de cartela, alavancagem, Boost e
        # Jogador · o escopo é todo tipo de pick, não só a múltipla.
        for tipo in admin._PICK_TABLES:
            if tipo in admin._CONFERIVEIS_PELA_FOLHA or tipo in admin._CARTELAS:
                continue
            assert f'"{tipo}"' in fonte, f"{tipo} ficou sem conferência própria"

    def test_o_nao_conferido_vem_com_motivo(self):
        import inspect
        fonte = inspect.getsource(admin.admin_auditoria_resultados)
        for motivo in ("sem folha do jogo", "folha incompleta", "sem folha do jogador"):
            assert motivo in fonte
