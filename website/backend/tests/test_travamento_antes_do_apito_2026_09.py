"""O jogo ainda esta rolando: nada de resultado de fim de jogo (2026-09-06).

O CASO RELATADO
---------------
Na aba Ao Vivo apareceram dois picks com resultado ANTES do apito final:

  a) "Gols · Mais de 4.75" marcado HALF-WIN assim que saiu o 5o gol;
  b) um pick marcado PUSH que o jogo ainda podia desmentir.

A conta nao estava errada -- a PERGUNTA estava. Com 5 gols no placar final,
"Over 4.75" e' HALF-WIN mesmo (metade em Over 4.5, que ganhou, metade em Over
5.0, que empatou). So' que o placar nao era final: o sexto gol faria GREEN.

Eram dois defeitos somados:

  1. a varredura chamava `_calc_result` -- a liquidacao de FIM DE JOGO -- toda
     vez que `is_locked` era verdadeiro, inclusive com a bola rolando;
  2. `is_locked` marcava travado cedo demais, porque a conta dele estava
     escrita a mao em tres lugares e um deles discordava dos outros dois.

A correcao e' uma regra so' (`_teto_da_linha`) e um portao so'
(`_locked_leg_result`). Antes do apito, o unico veredito possivel e' o que
mais nenhum evento do jogo pode mudar.
"""

import re
from pathlib import Path

from routers.live import (
    _calc_result, _locked_leg_result, _teto_da_linha, _travado_antes_do_apito,
)

FONTE = Path(__file__).resolve().parents[1] / "routers" / "live.py"


class TestTetoDaLinha:
    def test_quarto_de_bola_sobe_pra_meia_linha_de_cima(self):
        assert _teto_da_linha(4.75) == 5.0
        assert _teto_da_linha(4.25) == 4.5
        assert _teto_da_linha(9.75) == 10.0

    def test_linha_inteira_ou_meia_e_ela_mesma(self):
        assert _teto_da_linha(3.0) == 3.0
        assert _teto_da_linha(2.5) == 2.5


class TestOverNaoTravaEmMeiaVitoria:
    """O caso (a): Over 4.75 com 5 gols ainda pode virar GREEN."""

    def test_encostar_no_teto_nao_trava(self):
        assert _travado_antes_do_apito("Gols", "Mais de 4.75", 5) is None

    def test_passar_do_teto_trava_como_green(self):
        assert _travado_antes_do_apito("Gols", "Mais de 4.75", 6) == "GREEN"

    def test_no_apito_o_mesmo_5_e_meia_vitoria(self):
        # A liquidacao de fim de jogo continua certa -- ela e' que nao podia
        # ser chamada antes da hora.
        assert _calc_result("Gols", "Mais de 4.75", 5, 3, 2) == "HALF-WIN"

    def test_quarto_de_baixo_segue_a_mesma_regra(self):
        assert _travado_antes_do_apito("Escanteios", "Mais de 9.25", 9) is None
        assert _travado_antes_do_apito("Escanteios", "Mais de 9.25", 10) == "GREEN"


class TestUnderNaoTravaEmPush:
    """O caso (b): Under que empatou com a linha ainda nao e' RED."""

    def test_empatar_com_linha_inteira_nao_trava(self):
        # Parou em 3 -> PUSH no apito. Sai o quarto -> RED. Nao ha veredito.
        assert _travado_antes_do_apito("Gols", "Menos de 3.0", 3) is None
        assert _calc_result("Gols", "Menos de 3.0", 3, 2, 1) == "PUSH"

    def test_estourar_a_linha_inteira_trava_como_red(self):
        assert _travado_antes_do_apito("Gols", "Menos de 3.0", 4) == "RED"

    def test_quarto_de_bola_so_trava_depois_da_meia_derrota(self):
        # Under 9.75 com 10: HALF-LOSS se acabar assim, RED se sair o 11o.
        assert _travado_antes_do_apito("Escanteios", "Menos de 9.75", 10) is None
        assert _travado_antes_do_apito("Escanteios", "Menos de 9.75", 11) == "RED"

    def test_meia_linha_trava_normalmente(self):
        assert _travado_antes_do_apito("Escanteios", "Menos de 9.5", 10) == "RED"

    def test_under_nunca_trava_pra_green(self):
        # Under 11 com 9 escanteios aos 80' ainda cabe dois.
        assert _travado_antes_do_apito("Escanteios", "Menos de 11.5", 9) is None


class TestPortaoUnico:
    """Antes do apito, `_locked_leg_result` nao pode devolver PUSH nem HALF-*."""

    def _perna(self, line, valor, **extra):
        base = {
            "market": "Gols", "market_type": "goals", "line": line,
            "current_val": valor, "home_goals": 3, "away_goals": 2,
            "home_team": "A", "away_team": "B",
            "is_ft": False, "is_locked": True,
            "home_stats": {}, "away_stats": {},
            "went_to_extra_time": False, "precisa_stats": False,
            "status": "2H",
        }
        base.update(extra)
        return base

    def test_perna_ao_vivo_nunca_recebe_veredito_de_fim_de_jogo(self):
        for line, valor in (("Mais de 4.75", 5), ("Menos de 3.0", 3),
                            ("Menos de 9.75", 10), ("Mais de 4.25", 4)):
            assert _locked_leg_result(self._perna(line, valor)) not in (
                "PUSH", "HALF-WIN", "HALF-LOSS")

    def test_o_que_travou_de_verdade_continua_travando(self):
        assert _locked_leg_result(self._perna("Mais de 4.75", 6)) == "GREEN"
        assert _locked_leg_result(self._perna("Menos de 3.0", 4)) == "RED"

    def test_com_o_apito_o_portao_libera_a_liquidacao_completa(self):
        perna = self._perna("Mais de 4.75", 5, is_ft=True, status="FT")
        assert _locked_leg_result(perna) == "HALF-WIN"


class TestNenhumaVarreduraPulaOPortao:
    """Guarda de fonte: o padrao que causou o bug nao pode voltar.

    `_calc_result` so' pode ser chamado por quem ja' garantiu o fim do jogo.
    O padrao removido era `if leg["is_ft"] or leg["is_locked"]:` seguido de
    `_calc_result` -- seis copias dele, uma por produto.
    """

    def test_ninguem_mais_casa_is_locked_com_calc_result(self):
        fonte = FONTE.read_text(encoding="utf-8")
        assert 'leg["is_ft"] or leg["is_locked"]' not in fonte

    def test_calc_result_so_e_chamado_de_tres_lugares(self):
        fonte = FONTE.read_text(encoding="utf-8")
        chamadas = len(re.findall(r"(?<!def )_calc_result\(", fonte))
        # 1) dentro de _locked_leg_result, no ramo de FT;
        # 2) na reconferencia tardia, guardada por `if not leg["is_ft"]`.
        assert chamadas == 2
