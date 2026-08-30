# -*- coding: utf-8 -*-
"""A captura de odds pula jogo sem base no mando.

POR QUE (2026-08-30, pedido do usuario)
---------------------------------------
Cada fixture custa uma requisicao POR CASA (Bet365 + Betano = 2). Num dia cheio
sao 40+ jogos, 80+ requisicoes, e o limite estoura antes de a coleta terminar --
entao quem fica sem odd e o fim da lista, escolhido por ordem de nada.

Parte desses jogos nunca virou pick e nunca vai virar: todo motor do projeto
exige um minimo de partidas por time antes de estimar qualquer coisa. A odd
deles era baixada, gravada, nunca lida, e apagada no TRUNCATE do dia seguinte.

O PISO E POR MANDO, e nao pelo total (decisao do usuario). O piso unico do
projeto e 4 jogos, e o 4 sempre significou "2 em casa e 2 fora" -- esta escrito
na razao dele em pick_engine_boost/config.py. Contar o total diria que um time
com 4 jogos, todos fora, tem base pra ser mandante; e nao tem. E' o mesmo
motivo que fez o motor ao vivo passar a ler mando em 29/08.

MEDIDO EM PROD (30/08): dos 41 jogos do dia, 10 tinham base nos dois mandos.
Os 31 cortados eram ligas europeias na primeira ou segunda rodada da
temporada -- Premier League, Bundesliga, Serie A, Ligue 1 com zero ou um jogo
no banco.

A VALIDACAO QUE IMPORTA e' a de tras: o filtro teria cortado jogo que PRODUZIU
pick? Sobre 60 dias de producao, nenhum -- 159 picks VIP e 40 Free, zero
cortados.

Um detalhe que quase virou falso alarme: a primeira medicao juntou os picks com
`fixtures`, e `fixtures` e' EFEMERA (guarda jogo futuro; a partida antiga vive
em `match_statistics`). O JOIN derrubava quase todos os picks e a amostra vinha
com 1 linha. Quem valida filtro de coleta precisa ler a partida de onde ela
sobrevive.

O AO VIVO aparece com 30% dos picks "cortados" nessa conta e nao e' problema
dele: o motor Live le `/odds/live`, endpoint em tempo real, e nunca consome a
tabela `odds_values` que este script alimenta. Ele tambem nao depende de
historico do time pra decidir -- le a partida acontecendo.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import capturar_odds  # noqa: E402


FONTE = None


def _fonte() -> str:
    global FONTE
    if FONTE is None:
        caminho = os.path.join(os.path.dirname(__file__), "..", "src", "capturar_odds.py")
        with open(caminho, encoding="utf-8") as f:
            FONTE = f.read()
    return FONTE


class TestOPiso:
    def test_sao_dois_jogos_no_mando(self):
        assert capturar_odds.MIN_JOGOS_NO_MANDO == 2

    def test_dois_por_mando_fecha_o_piso_unico_do_projeto(self):
        """2 em casa + 2 fora = os 4 jogos que os motores exigem. O filtro nao
        pode ser mais duro que o motor: cortaria odd de jogo que produziria
        pick."""
        from services.pick_engine_boost import config as boost

        assert capturar_odds.MIN_JOGOS_NO_MANDO * 2 <= boost.MIN_JOGOS_FT


class TestAConsulta:
    def test_conta_casa_e_fora_separado(self):
        """O recorte inteiro mora aqui. Somar os dois lados devolveria numero
        plausivel e errado, que e o pior tipo de defeito neste filtro."""
        fonte = _fonte()
        assert "em_casa AS (" in fonte
        assert "fora AS (" in fonte
        assert "SELECT home_team_id AS team_id" in fonte
        assert "SELECT away_team_id AS team_id" in fonte

    def test_o_mandante_e_medido_em_casa_e_o_visitante_fora(self):
        fonte = _fonte()
        assert "em_casa c ON c.team_id = f.home_team_id" in fonte
        assert "fora    v ON v.team_id = f.away_team_id" in fonte

    def test_os_dois_lados_precisam_ter_base(self):
        """Um pick e sobre o confronto · com um lado cego nenhuma estimativa do
        projeto se sustenta."""
        fonte = _fonte()
        assert re.search(r"COALESCE\(c\.n, 0\) >= \{MIN_JOGOS_NO_MANDO\}", fonte)
        assert re.search(r"COALESCE\(v\.n, 0\) >= \{MIN_JOGOS_NO_MANDO\}", fonte)

    def test_conta_na_competicao_da_partida(self):
        """Time com 30 jogos na liga nacional e nenhum na copa continua sem
        base pro jogo de copa."""
        fonte = _fonte()
        assert "c.league_id = f.league_id" in fonte
        assert "v.league_id = f.league_id" in fonte

    def test_so_partida_encerrada_conta_como_historico(self):
        fonte = _fonte()
        assert "status IN ('FT','AET','PEN')" in fonte

    def test_a_conta_nao_custa_api(self):
        """`match_statistics` ja sabe tudo isto. Se um dia alguem trocar por uma
        chamada externa, o filtro passa a custar o que deveria economizar."""
        trecho = _fonte()[_fonte().index("def get_pre_match_fixtures"):]
        trecho = trecho[:trecho.index("def ", 10)]
        for proibido in ("requests", "api-sports", "_fetch"):
            assert proibido not in trecho

    def test_a_janela_de_dia_continua_sendo_hoje(self):
        """O filtro novo nao pode ter alargado a janela por acidente · odd de
        jogo futuro e' apagada no dia seguinte sem nunca ter sido lida."""
        assert "match_datetime::date = {HOJE_BR}" in _fonte()
