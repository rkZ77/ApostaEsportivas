"""Dois picks Ao Vivo de escanteios gravados PUSH em cima da linha cheia.

O RELATO (2026-09-06): "Menos de 9.0" e "Menos de 7.0", os dois Ao Vivo, os
dois PUSH, um atras do outro. PUSH numa linha cheia so' sai quando o contador
para EXATAMENTE em cima dela -- acontece, mas nao duas vezes seguidas.

A matematica estava certa: 9 escanteios contra a linha 9.0 e' entrada
devolvida, e e' o que a casa faz. O defeito estava em QUAL numero chegava ate
ela, e sao dois, um que erra e outro que deixa o erro gravado:

1 · A FOLHA DO MINUTO ~90 PASSAVA POR FOLHA DO APITO FINAL

`_fetch_stats` escolhia o TTL pelo status DE AGORA e comparava com o carimbo
de QUANDO a folha foi tirada. No apito o status vira FT, o TTL vira 300s, e a
folha tirada com a bola rolando valia por mais cinco minutos. No Ao Vivo ela
esta sempre quente -- o ticker busca estatistica a cada 60s enquanto o jogo
corre --, entao a varredura logo apos o apito lia o contador SEM os escanteios
dos acrescimos. Um escanteio a menos num Under vira RED em PUSH.

2 · O AO VIVO ESTAVA FORA DA RECONFERENCIA

`reverify_recent_stats_results` existe porque a API revisa escanteios e
cartoes horas depois do FT. Ela cobria VIP, Free, multipla e alavancagem, e
nao cobria `picks_live` -- o produto que publica QUASE SO' escanteios. Como
`resolve_all_pending` so' olha pick com `result IS NULL`, o numero errado do
item 1 ficava gravado pra sempre.

A terceira suspeita do mesmo dia, essa SEM defeito: "Mais de 4.75" com 5 gols
saiu meia-green. Linha de quarto-de-bola e' metade em 4.5 (ganha) e metade em
5.0 (devolve). Meia-green e' o resultado certo, e o teste abaixo fixa isso pra
que nenhuma "correcao" futura o transforme em green cheio.
"""
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from routers import live
from settlement_bridge import settlement


class _Resposta:
    status_code = 200
    headers: dict = {}

    def __init__(self, corpo):
        self._corpo = corpo

    def json(self):
        return self._corpo


def _folha(escanteios: int):
    return [{"team": {"id": 1},
             "statistics": [{"type": "Corner Kicks", "value": escanteios}]}]


# ── 1 · a folha tirada em jogo nao vale no apito ────────────────────────────
class TestFolhaCongeladaNoJogo:
    def test_folha_do_segundo_tempo_e_refeita_quando_o_jogo_acaba(self, monkeypatch):
        live._stats_cache.clear()
        # Folha do minuto ~90, tirada agora mesmo (dentro de qualquer TTL).
        live._stats_cache[990101] = (live.time.time(), _folha(9), "2H")
        monkeypatch.setattr(live.requests, "get", lambda *a, **k: _Resposta(
            {"errors": [], "response": _folha(11)}))
        # No apito, o contador dos acrescimos entra: 11, e nao os 9 do cache.
        assert live._fetch_stats(990101, "FT") == _folha(11)

    def test_folha_do_apito_continua_valendo_pelo_ttl(self, monkeypatch):
        live._stats_cache.clear()
        live._stats_cache[990102] = (live.time.time(), _folha(11), "FT")

        def _nao_chama(*a, **k):
            raise AssertionError("folha ja' era do apito final; nao ha' o que refazer")

        monkeypatch.setattr(live.requests, "get", _nao_chama)
        assert live._fetch_stats(990102, "FT") == _folha(11)

    def test_folha_em_jogo_nao_e_refeita_a_cada_poll(self, monkeypatch):
        # O consumo de cota do ticker nao pode mudar: com o jogo ainda
        # rolando, o cache de 60s segue valendo.
        live._stats_cache.clear()
        live._stats_cache[990103] = (live.time.time(), _folha(6), "2H")

        def _nao_chama(*a, **k):
            raise AssertionError("jogo em andamento deve sair do cache")

        monkeypatch.setattr(live.requests, "get", _nao_chama)
        assert live._fetch_stats(990103, "2H") == _folha(6)

    def test_status_e_gravado_junto_com_a_folha(self, monkeypatch):
        live._stats_cache.clear()
        monkeypatch.setattr(live.requests, "get", lambda *a, **k: _Resposta(
            {"errors": [], "response": _folha(4)}))
        live._fetch_stats(990104, "1H")
        assert live._stats_cache[990104][2] == "1H"

    def test_regra_isolada(self):
        assert live._folha_e_do_jogo_em_andamento("2H", "FT") is True
        assert live._folha_e_do_jogo_em_andamento("HT", "FT") is True
        assert live._folha_e_do_jogo_em_andamento("FT", "FT") is False
        assert live._folha_e_do_jogo_em_andamento("2H", "2H") is False


# ── 2 · o Ao Vivo entra na reconferencia ────────────────────────────────────
class TestAoVivoNaReconferencia:
    def test_picks_live_esta_na_lista_de_tabelas(self):
        import inspect
        fonte = inspect.getsource(live.reverify_recent_stats_results)
        codigo = "\n".join(l for l in fonte.split("\n")
                           if not l.lstrip().startswith("#"))
        assert '("picks_live", "live"' in codigo, (
            "o produto que publica quase so' escanteios nao pode ficar de fora "
            "da unica rotina que reconfere escanteios")


# ── 3 · o que NAO era defeito ───────────────────────────────────────────────
class TestQuartoDeBolaNaoEDefeito:
    def test_over_4_75_com_5_gols_e_meia_green(self):
        p = settlement.parse_line("Mais de 4.75")
        assert settlement.settle_over_under(5, p["value"], p["op"])[0] == settlement.HALF_WIN

    def test_over_4_75_com_6_gols_e_green_cheia(self):
        p = settlement.parse_line("Mais de 4.75")
        assert settlement.settle_over_under(6, p["value"], p["op"])[0] == settlement.GREEN

    def test_under_linha_cheia_em_cima_da_linha_e_push(self):
        p = settlement.parse_line("Menos de 9.0")
        assert settlement.settle_over_under(9, p["value"], p["op"])[0] == settlement.PUSH
        assert settlement.settle_over_under(10, p["value"], p["op"])[0] == settlement.RED
