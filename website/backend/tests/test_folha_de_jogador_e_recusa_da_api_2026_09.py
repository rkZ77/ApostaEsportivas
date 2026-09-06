"""O produto de jogadores nao atualizava resultado, e a API recusa com HTTP 200.

DOIS ACHADOS DO MESMO DIA (2026-09-06), os dois na fronteira com a
API-Football.


1 · O PRODUTO DE JOGADORES ESPERAVA UM COMANDO, NAO O PROVEDOR

Defesas de goleiro e Player Stats liquidavam por JOIN em `player_match_stats`.
Nada no site escreve nessa tabela: quem escreve e'
`collectors/player_stats_collector_service.py`, que roda dentro do motor, na
mao -- e nao ha' agendador no projeto desde 01/08. Sem a linha, o JOIN nao
encontrava nada, o pick nao entrava na lista da varredura e ficava Pendente
pra sempre, sem UM erro no log.

E' o pior formato de bug: o produto parecia esperar o provedor quando estava
esperando alguem rodar um script em outro repositorio. E, mesmo rodando, a
fila do coletor tem rodizio por liga e filtro de `leagues.ativa` -- a folha de
uma partida especifica pode demorar dias.

O JOIN virou LEFT JOIN e a lacuna passou a ser buscada na API, com teto por
passada, so' pra partida ENCERRADA, e lendo a folha pela MESMA funcao do
coletor (a que sabe que `null` de quem entrou em campo e' zero).


2 · A RECUSA DA API VIRAVA "O PROVEDOR NAO PUBLICOU"

Cota estourada, plano sem endpoint e chave invalida nao viram status de erro
na API-Football: vem HTTP 200, `response: []` e o motivo dentro de `errors`.
O motor aprendeu isso em 05/09 (live_feed._get). Este lado nao, e aqui a
consequencia era pior do que um pick que nao nasce: a lista vazia atravessava
`_parse_stats`, o contador ficava None e, 12 horas depois,
`_anulacao_sem_estatistica` gravava PUSH com o motivo "provedor nao publicou a
estatistica". A cota do nosso lado escrita no historico como falha do
provedor, num pick que podia ter ganhado.
"""
import os
import re
import sys
from pathlib import Path

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from routers import live

FONTE = Path(_BACKEND) / "routers" / "live.py"


def _sem_comentarios(fonte: str) -> str:
    """A fonte sem as linhas de comentario.

    As guardas abaixo procuram SQL, e este arquivo explica cada correcao em
    prosa logo acima dela -- entao o texto que descreve o defeito antigo
    ("eram `JOIN player_match_stats`") casava com a busca e reprovava o codigo
    ja corrigido. Grep em codigo tem que olhar codigo.
    """
    return "\n".join(l for l in fonte.split("\n") if not l.lstrip().startswith("#"))


class _Resposta:
    """Resposta 200 da API-Football, com ou sem recusa dentro."""
    status_code = 200
    headers: dict = {}

    def __init__(self, corpo):
        self._corpo = corpo

    def json(self):
        return self._corpo


# ── 1 · reconhecer a recusa ─────────────────────────────────────────────────
class TestRecusaDaApi:
    def test_errors_como_dict_e_recusa(self):
        motivo = live._recusa_da_api(
            {"errors": {"requests": "limite do dia atingido"}, "response": []})
        assert motivo and "limite do dia" in motivo

    def test_lista_vazia_nao_e_recusa(self):
        # E' o formato que a API usa quando esta tudo bem.
        assert live._recusa_da_api({"errors": [], "response": []}) is None

    def test_corpo_sem_errors_nao_e_recusa(self):
        assert live._recusa_da_api({"response": []}) is None
        assert live._recusa_da_api({}) is None


class TestRecusaNaoViraFolhaVazia:
    def test_folha_recusada_nao_entra_no_cache(self, monkeypatch):
        live._stats_cache.clear()
        monkeypatch.setattr(live.requests, "get", lambda *a, **k: _Resposta(
            {"errors": {"token": "chave invalida"}, "response": []}))
        assert live._fetch_stats(999001, "FT") == []
        # O ponto todo: nada guardado. Guardar a lista vazia por 5 minutos
        # transformaria a recusa em dado, e o dado em PUSH.
        assert 999001 not in live._stats_cache

    def test_recusa_devolve_o_cache_bom_de_antes(self, monkeypatch):
        live._stats_cache.clear()
        folha = [{"team": {"id": 1},
                  "statistics": [{"type": "Corner Kicks", "value": 6}]}]
        live._stats_cache[999002] = (0.0, folha)  # timestamp velho: expirado
        monkeypatch.setattr(live.requests, "get", lambda *a, **k: _Resposta(
            {"errors": {"requests": "cota"}, "response": []}))
        assert live._fetch_stats(999002, "FT") == folha

    def test_fixture_recusada_nao_vira_jogo_que_nao_comecou(self, monkeypatch):
        live._fix_cache.clear()
        monkeypatch.setattr(live.requests, "get", lambda *a, **k: _Resposta(
            {"errors": {"requests": "cota"}, "response": []}))
        assert live._fetch_fixture(999003) == {}
        assert 999003 not in live._fix_cache


# ── 2 · a folha por jogador, lida pela regra do coletor ─────────────────────
def _folha(player_id, stats):
    return [{"team": {"id": 7},
             "players": [{"player": {"id": player_id}, "statistics": [stats]}]}]


class TestFolhaDeJogador:
    @pytest.fixture(autouse=True)
    def _limpa(self):
        live._player_sheet_cache.clear()
        live._folhas_de_jogador_buscadas = 0

    def test_le_o_contador_e_os_minutos(self, monkeypatch):
        monkeypatch.setattr(live.requests, "get", lambda *a, **k: _Resposta(
            {"response": _folha(50, {"games": {"minutes": 90},
                                     "goals": {"saves": 4}})}))
        assert live._valor_do_jogador(1, 50, "saves") == (4, 90)

    def test_null_de_quem_entrou_em_campo_e_zero(self, monkeypatch):
        # A REGRA DO COLETOR, e nao uma segunda leitura: a API OMITE o zero em
        # vez de escreve-lo (169 zeros contra 8.115 nulls no mesmo shots_on).
        # Tratar isso como ausencia deixaria o pick pendente pra sempre num
        # jogo em que o jogador simplesmente nao chutou -- ou seja, num RED.
        monkeypatch.setattr(live.requests, "get", lambda *a, **k: _Resposta(
            {"response": _folha(50, {"games": {"minutes": 75},
                                     "shots": {"on": None}})}))
        assert live._valor_do_jogador(1, 50, "shots_on") == (0, 75)

    def test_quem_nao_entrou_continua_desconhecido(self, monkeypatch):
        monkeypatch.setattr(live.requests, "get", lambda *a, **k: _Resposta(
            {"response": _folha(50, {"games": {"minutes": 0},
                                     "shots": {"on": None}})}))
        assert live._valor_do_jogador(1, 50, "shots_on") == (None, 0)

    def test_jogador_fora_da_folha_da_none(self, monkeypatch):
        monkeypatch.setattr(live.requests, "get", lambda *a, **k: _Resposta(
            {"response": _folha(50, {"games": {"minutes": 90},
                                     "goals": {"saves": 4}})}))
        assert live._valor_do_jogador(1, 999, "saves") == (None, None)

    def test_coluna_fora_do_mapa_nao_chama_a_api(self, monkeypatch):
        def _explode(*a, **k):
            raise AssertionError("nao devia chamar a API")
        monkeypatch.setattr(live.requests, "get", _explode)
        assert live._valor_do_jogador(1, 50, "coluna_inventada") == (None, None)

    def test_recusa_da_api_nao_entra_no_cache(self, monkeypatch):
        monkeypatch.setattr(live.requests, "get", lambda *a, **k: _Resposta(
            {"errors": {"requests": "cota"}, "response": []}))
        assert live._fetch_player_sheet(999004) == []
        assert 999004 not in live._player_sheet_cache


class TestQuandoValeGastarRequisicao:
    @pytest.fixture(autouse=True)
    def _limpa(self):
        live._player_sheet_cache.clear()
        live._fix_cache.clear()
        live._folhas_de_jogador_buscadas = 0

    def test_valor_do_banco_nao_gasta_nada(self, monkeypatch):
        def _explode(*a, **k):
            raise AssertionError("o banco ja tinha o numero")
        monkeypatch.setattr(live.requests, "get", _explode)
        p = {"fixture_id": 1, "player_id": 50, "saves": 3}
        assert live._defesas_do_goleiro(p) == 3

    def test_jogo_em_andamento_nao_liquida(self, monkeypatch):
        # A folha de jogo em andamento existe e esta' incompleta: liquidar por
        # ela seria repetir, no pick de jogador, o erro que este mesmo arquivo
        # corrigiu nos mercados de time (ver _travado_antes_do_apito).
        live._fix_cache[1] = (9e18, {"fixture": {"status": {"short": "2H"}}})
        monkeypatch.setattr(live.requests, "get", lambda *a, **k: _Resposta(
            {"response": _folha(50, {"games": {"minutes": 60},
                                     "goals": {"saves": 9}})}))
        p = {"fixture_id": 1, "player_id": 50, "saves": None}
        assert live._defesas_do_goleiro(p) is None

    def test_jogo_encerrado_busca_a_folha(self, monkeypatch):
        live._fix_cache[1] = (9e18, {"fixture": {"status": {"short": "FT"}}})
        monkeypatch.setattr(live.requests, "get", lambda *a, **k: _Resposta(
            {"response": _folha(50, {"games": {"minutes": 90},
                                     "goals": {"saves": 5}})}))
        p = {"fixture_id": 1, "player_id": 50, "saves": None}
        assert live._defesas_do_goleiro(p) == 5

    def test_teto_por_passada(self, monkeypatch):
        live._fix_cache[1] = (9e18, {"fixture": {"status": {"short": "FT"}}})
        monkeypatch.setattr(live, "_MAX_FOLHAS_DE_JOGADOR", 2)
        monkeypatch.setattr(live.requests, "get", lambda *a, **k: _Resposta(
            {"response": _folha(50, {"games": {"minutes": 90},
                                     "goals": {"saves": 5}})}))
        # Fila grande nao pode gastar a cota do dia numa visita so'. O que
        # sobra segue pendente e sai na proxima passada.
        vistos = []
        for _ in range(4):
            live._player_sheet_cache.clear()
            vistos.append(live._defesas_do_goleiro(
                {"fixture_id": 1, "player_id": 50, "saves": None}))
        assert vistos == [5, 5, None, None]


# ── 3 · guarda de fonte: o produto nao pode voltar a depender do coletor ────
class TestNaoDependeMaisDoColetorManual:
    def test_nenhum_join_fechado_em_player_match_stats(self):
        """Todo JOIN nessa tabela tem que ser LEFT.

        E' a forma do defeito, e ela apareceu em TRES lugares: os dois
        resolvedores e o freio da varredura. Um JOIN fechado ali significa
        "so' liquida o que o coletor manual do motor alcancou".
        """
        fonte = _sem_comentarios(FONTE.read_text(encoding="utf-8"))
        achados = list(re.finditer(r"(LEFT\s+)?JOIN\s+player_match_stats", fonte))
        assert achados, "os JOINs sumiram -- o teste perdeu o alvo"
        for m in achados:
            assert m.group(1), fonte[max(0, m.start() - 200):m.end()]

    def test_o_freio_da_varredura_pergunta_pela_hora_do_jogo(self):
        """O freio nao pode depender da folha pra deixar a varredura disparar.

        Num dia cuja unica pendencia fosse pick de jogador, o freio respondia
        "nao ha' o que resolver" e nada rodava -- o pick esperava outra
        pendencia aparecer por acaso e carregar ele junto.
        """
        fonte = _sem_comentarios(FONTE.read_text(encoding="utf-8"))
        corpo = fonte[fonte.index("def _ha_pendente_em_jogo"):]
        corpo = corpo[:corpo.index("def ", 10)]
        assert "player_match_stats" not in corpo
        assert '("picks_goleiros", "picks_player_stats")' in corpo

    def test_a_anulacao_exige_a_folha_em_maos(self):
        """Pick que o teto de requisicoes nao alcancou NAO pode ser anulado.

        `_anular_sem_estatistica` roda depois do resolvedor, e antes disto ele
        anulava como PUSH todo pick de jogador com mais de um dia sem linha em
        `player_match_stats` -- uma tabela que o site nunca preencheu. Ou seja:
        registrava como falha do provedor a falta da nossa propria coleta.
        """
        fonte = _sem_comentarios(FONTE.read_text(encoding="utf-8"))
        corpo = fonte[fonte.index("def _anular_sem_estatistica"):]
        corpo = corpo[:corpo.index("picks_boost")]
        assert "_folha_do_jogador_consultada" in corpo
        assert "_jogador_esta_na_folha" in corpo

    def test_motivo_da_anulacao_vai_pra_tela_com_acento(self):
        """`void_reason` e' texto de PRODUTO, nao de log -- o card o imprime."""
        fonte = FONTE.read_text(encoding="utf-8")
        for frase in ("o provedor não publicou a estatística do jogo",
                      "o jogo foi para a prorrogação e a folha não separa os 90 minutos",
                      "a folha do jogo não cobre a atuação deste jogador"):
            assert frase in fonte, frase

    def test_o_teto_de_folhas_e_zerado_em_cada_passada(self):
        fonte = FONTE.read_text(encoding="utf-8")
        corpo = fonte[fonte.index("def resolve_all_pending"):]
        corpo = corpo[:corpo.index("today_br =")]
        assert re.search(r"_folhas_de_jogador_buscadas\s*=\s*0", corpo)
