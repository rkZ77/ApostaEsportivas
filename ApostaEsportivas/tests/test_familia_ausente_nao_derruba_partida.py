"""Familia sem dado sai sozinha · nao leva a partida junto.

O motor Ao Vivo trabalha com duas familias, escanteios e gols. O pipeline
descartava a PARTIDA inteira quando qualquer uma das duas vinha sem numero, e
isso custava caro por um motivo que nao e' obvio olhando o codigo:

    `goals_total` NAO sai de /fixtures/statistics. Sai do placar, que vem no
    feed de fixtures.

Ou seja, quando o provedor nao publica estatistica nenhuma -- medido em
2026-08-22 em 11 partidas ao vivo de 11 ligas, dos 29' aos 90', todas com zero
bloco -- escanteio fica None e gols continua sendo um numero real. O gate
antigo jogava a partida fora por causa do escanteio, levando gols junto.

Estes testes fixam as duas metades: o orchestrator sabe conviver com familia
ausente, e o placar sobrevive a folha de estatistica vazia.
"""
import re
from pathlib import Path

from services.pick_engine_live import live_state, orchestrator
from services.pick_engine_live.config import DEFAULT_LIVE_CONFIG


def _partida(minuto=33, gols=(0, 0), home_stats=None, away_stats=None):
    bruto = {
        "fixture": {"id": 9999, "timestamp": 1755880000,
                    "status": {"short": "1H", "elapsed": minuto, "extra": None}},
        "goals": {"home": gols[0], "away": gols[1]},
        "teams": {"home": {"id": 119, "name": "Internacional"},
                  "away": {"id": 1062, "name": "Atletico-MG"}},
        "league": {"id": 71, "name": "Serie A"},
    }
    return live_state.montar_estado(bruto, home_stats or {}, away_stats or {}, [])


class TestPlacarSobreviveASemEstatistica:
    def test_gols_vem_do_placar_e_nao_da_folha_de_estatistica(self):
        """E' a razao inteira de a partida nao poder ser descartada."""
        estado = _partida(gols=(1, 1))
        assert estado["corners_total"] is None
        assert estado["goals_total"] == 2

    def test_ausencia_de_escanteio_nunca_vira_zero(self):
        """Invariante 1 de services/settlement.py.

        Zero e "nao publicado" levariam o modelo a conclusoes opostas: um jogo
        travado sem escanteio contra um jogo cujo numero ninguem informou.
        """
        assert _partida()["corners_total"] is None

    def test_um_lado_so_tambem_e_ausencia(self):
        """Metade da folha nao e' meia verdade, e' numero errado."""
        estado = _partida(home_stats={"Corner Kicks": 4}, away_stats={})
        assert estado["corners_total"] is None


class TestOrchestratorConviveComFamiliaAusente:
    def test_marca_a_familia_como_indisponivel_em_vez_de_explodir(self):
        estado = _partida()
        analise = orchestrator.analisar(estado, [], DEFAULT_LIVE_CONFIG,
                                        baselines={}, eventos={}, fresh=None)
        assert analise["familias"]["corners"]["disponivel"] is False
        assert "provedor" in analise["familias"]["corners"]["motivo"]

    def test_a_outra_familia_continua_de_pe(self):
        """O ponto todo: gols segue analisavel sem escanteio nenhum."""
        estado = _partida(gols=(0, 1))
        analise = orchestrator.analisar(estado, [], DEFAULT_LIVE_CONFIG,
                                        baselines={}, eventos={}, fresh=None)
        assert analise["familias"]["goals"]["disponivel"] is True
        assert analise["familias"]["goals"]["observado"] == 1


class TestPipelineNaoDescartaAPartidaInteira:
    """Le o codigo do pipeline · a decisao mora num `if`, nao numa funcao.

    Extrair isso pra uma funcao so' pra poder testar deixaria o teste bonito e
    o codigo pior: o trecho usa meia duzia de variaveis locais do laco. Ler a
    fonte pega exatamente a regressao que importa, que e' alguem devolver o
    `return` pra dentro do primeiro `if`.
    """

    @property
    def fonte(self) -> str:
        caminho = (Path(__file__).resolve().parents[1]
                   / "src" / "engine_pipelines" / "live_pipeline.py")
        return caminho.read_text(encoding="utf-8")

    def test_so_descarta_quando_NENHUMA_familia_tem_dado(self):
        assert "if not disponiveis:" in self.fonte
        assert re.search(r"disponiveis = \[f for f in config\.familias", self.fonte)

    def test_a_mensagem_separa_folha_vazia_de_familia_faltando(self):
        """"corners nao publicado" escondia o caso que derruba a rodada.

        Quando o provedor nao manda folha nenhuma, o problema e' cobertura da
        partida · culpar o escanteio manda quem le' procurar no lugar errado.
        """
        fonte = self.fonte
        assert "folha_vazia" in fonte
        assert "nao publicou estatistica nenhuma" in fonte

    def test_a_leitura_da_partida_e_gravada_mesmo_quando_descarta(self):
        """Sem observar, a rodada seguinte nao tem janela nem tendencia ·
        /fixtures/statistics devolve so' acumulado."""
        trecho = self.fonte[self.fonte.index("if not disponiveis:"):]
        assert "_observar(cur, conn, estado)" in trecho[:400]
