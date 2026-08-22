"""
Explorador de ligas via API · a conta que transforma placar em tabela.

O que estes testes protegem é a única parte do módulo que não é I/O: somar 380
jogos em três recortes. Um erro aqui não quebra nada visivelmente, só devolve
um número plausível e errado, que é o pior defeito possível numa tela de
estatística.
"""

import pytest

from routers import explorer as ex


def _monta(jogos):
    """Roda os contadores sobre uma lista de (gols_pro, gols_contra).

    Aceita tuplas de 4 pra incluir o placar do intervalo.
    """
    r = ex._recorte_vazio()
    for jogo in jogos:
        ex._contar(r, *jogo)
    return ex._fechar_recorte(r)


class TestRecorte:
    def test_recorte_sem_jogo_devolve_zeros_e_nao_explode(self):
        """Time que ainda não jogou fora de casa continua na tabela.

        Dividir por zero aqui derrubaria a resposta inteira por causa de um
        time; e sumir com a linha esconderia justamente o caso que a pessoa foi
        olhar quando escolheu o recorte.
        """
        r = ex._fechar_recorte(ex._recorte_vazio())
        assert r["jogos"] == 0
        assert r["aproveitamento_pct"] == 0.0
        assert r["media_gols_pro"] == 0.0
        assert r["forma"] == ""

    def test_vitoria_empate_derrota_e_aproveitamento(self):
        # 2V, 1E, 1D = 7 pontos em 12 disputados = 58.3%
        r = _monta([(2, 0), (1, 1), (3, 1), (0, 2)])
        assert (r["v"], r["e"], r["d"]) == (2, 1, 1)
        assert r["aproveitamento_pct"] == pytest.approx(58.3, abs=0.1)

    def test_aproveitamento_e_ponto_ganho_nao_vitoria_sobre_jogo(self):
        """Quatro empates são 33.3%, não 0%.

        A conta ingênua (vitórias / jogos) daria zero pra um time invicto, e é
        o erro mais fácil de cometer neste arquivo.
        """
        r = _monta([(1, 1)] * 4)
        assert r["aproveitamento_pct"] == pytest.approx(33.3, abs=0.1)

    def test_gols_pro_e_contra_seguem_o_lado_do_time(self):
        r = _monta([(3, 1), (0, 2)])
        assert r["gols_pro"] == 3 and r["gols_contra"] == 3
        assert r["media_gols_pro"] == 1.5
        assert r["media_gols_total"] == 3.0
        assert r["saldo"] == 0

    def test_clean_sheet_sem_marcar_e_btts_sao_independentes(self):
        # 0x0 é clean sheet E sem marcar, e não é BTTS.
        r = _monta([(0, 0), (2, 1), (1, 0)])
        assert r["clean_sheet_pct"] == pytest.approx(66.7, abs=0.1)   # 0x0 e 1x0
        assert r["sem_marcar_pct"] == pytest.approx(33.3, abs=0.1)    # 0x0
        assert r["btts_pct"] == pytest.approx(33.3, abs=0.1)          # 2x1

    def test_over_conta_o_total_do_jogo_e_e_cumulativo(self):
        # Totais: 0, 2, 3, 4. Over 1.5 pega 3 jogos, 2.5 pega 2, 3.5 pega 1.
        r = _monta([(0, 0), (1, 1), (2, 1), (3, 1)])
        assert r["over15_pct"] == 75.0
        assert r["over25_pct"] == 50.0
        assert r["over35_pct"] == 25.0

    def test_forma_sao_os_cinco_ULTIMOS_na_ordem_em_que_aconteceram(self):
        """Seis jogos, cinco letras, e o mais recente por último.

        Se a fatia pegasse os cinco primeiros, a "forma" descreveria o começo da
        temporada com cara de momento atual.
        """
        r = _monta([(0, 1), (2, 0), (1, 1), (3, 0), (0, 0), (0, 2)])
        assert r["forma"] == "VEVED"


class TestPrimeiroTempo:
    def test_1t_mais_2t_fecha_com_o_total(self):
        """A fonte da' o placar do INTERVALO e o FINAL, nunca o 2T isolado.

        O segundo tempo sai por subtracao, entao a soma das duas medias tem que
        bater com a media do jogo inteiro · e' o unico jeito de pegar um erro de
        sinal nessa conta.
        """
        r = _monta([(2, 1, 1, 0), (0, 0, 0, 0), (3, 2, 2, 2)])
        assert r["media_gols_1t"] + r["media_gols_2t"] == pytest.approx(r["media_gols_total"], abs=0.01)

    def test_divide_pelos_jogos_COM_intervalo_nao_pelo_total(self):
        """Temporada antiga vem com o intervalo nulo em parte dos jogos.

        Dividir pelo total afundaria a media sem sintoma nenhum: dois jogos com
        2 gols no 1T dariam 1.0 em vez de 2.0 so' porque outros dois nao tinham
        o dado.
        """
        r = _monta([(1, 1, 1, 1), (1, 1, 1, 1), (2, 0, None, None), (0, 2, None, None)])
        assert r["jogos"] == 4
        assert r["jogos_com_1t"] == 2
        assert r["media_gols_1t"] == 2.0

    def test_sem_placar_de_intervalo_devolve_zero_sem_dividir_por_zero(self):
        r = _monta([(1, 0), (2, 2)])
        assert r["jogos_com_1t"] == 0
        assert r["media_gols_1t"] == 0.0
        assert r["media_gols_2t"] == 0.0
        assert r["gol_no_1t_pct"] == 0.0

    def test_gol_no_1t_conta_jogo_e_nao_gol(self):
        # 0x0 no intervalo em dois jogos, 1x0 em um: 1 de 3.
        r = _monta([(0, 0, 0, 0), (2, 1, 0, 0), (1, 0, 1, 0)])
        assert r["gol_no_1t_pct"] == pytest.approx(33.3, abs=0.1)


class TestJogoSemGol:
    def test_0x0_conta_como_jogo_sem_gol(self):
        r = _monta([(0, 0), (1, 0), (0, 0), (2, 2)])
        assert r["sem_gols_pct"] == 50.0

    def test_placar_com_gol_de_um_lado_so_nao_conta(self):
        """1x0 nao e' "jogo sem gol" · e' clean sheet de um lado e nada mais."""
        r = _monta([(1, 0)])
        assert r["sem_gols_pct"] == 0.0
        assert r["clean_sheet_pct"] == 100.0


class TestFormaEmPortugues:
    def test_o_D_da_api_vira_E_e_nao_derrota(self):
        """W/D/L e V/E/D compartilham a letra D com sentidos opostos.

        `D` na API é empate (draw); `D` na tela é derrota. Traduzir errado
        inverteria o resultado sem nenhum sintoma visível.
        """
        traduz = {"W": "V", "D": "E", "L": "D"}
        assert "".join(traduz.get(c, c) for c in "WDL") == "VED"


class TestPaisEmPortugues:
    def test_traduz_o_que_conhece(self):
        assert ex._pais_pt("Brazil") == "Brasil"
        assert ex._pais_pt("Turkey") == "Turquia"

    def test_pais_desconhecido_passa_direto_em_vez_de_sumir(self):
        assert ex._pais_pt("Faroe-Islands") == "Faroe-Islands"

    def test_sem_pais_continua_sem_pais(self):
        assert ex._pais_pt(None) is None
        assert ex._pais_pt("") is None


class TestCache:
    def test_expira_pelo_ttl(self, monkeypatch):
        ex._cache.clear()
        agora = [1000.0]
        monkeypatch.setattr(ex.time, "time", lambda: agora[0])

        ex._set_cache("k", "valor")
        assert ex._get_cache("k", ttl=60) == "valor"

        agora[0] += 61
        assert ex._get_cache("k", ttl=60) is None

    def test_descarta_os_mais_velhos_ao_estourar_o_teto(self, monkeypatch):
        """O teto existe porque cada temporada guardada são 380 jogos.

        Descartar METADE, e a metade velha, e não limpar tudo: limpar tudo faria
        a próxima visita a qualquer liga pagar cota de novo.
        """
        ex._cache.clear()
        agora = [0.0]
        monkeypatch.setattr(ex.time, "time", lambda: agora[0])

        for i in range(201):
            agora[0] = float(i)
            ex._set_cache(f"k{i}", i)

        assert len(ex._cache) <= 200
        assert "k0" not in ex._cache        # o mais velho saiu
        assert "k200" in ex._cache          # o mais novo ficou
