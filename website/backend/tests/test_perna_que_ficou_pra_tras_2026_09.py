"""A perna que nunca era resolvida depois de o bilhete morrer no RED.

O RELATO (13/09): duas múltiplas VIP fechadas em RED, cada uma com a primeira
perna marcada com o X e a segunda sem selo nenhum, paradas assim para sempre.

A ORIGEM. Uma perna RED já mata o bilhete, e o atalho que fecha ele na hora
(`_bilhete_morto`) está certo: o dinheiro não depende do resto. Só que ele
grava `result: null` nas pernas que ainda não jogaram, e a partir daí o
bilhete some da varredura -- as duas consultas de `resolve_all_pending`
filtram `result IS NULL`, e ele deixou de ser pendente no instante em que
virou RED. Ninguém voltava nele.

O bilhete estava certo; o detalhe dele é que ficava pela metade. É o detalhe
que a passada nova completa, e ela não toca em `result` nem em `profit`: mexer
em lucro por causa de exibição mudaria a banca de quem seguiu.
"""
import json
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from routers import live
from settlement_bridge import settlement


class _CursorDeUmBilhete:
    """Cursor mínimo: devolve sempre o mesmo `games` e guarda o UPDATE."""

    def __init__(self, pernas):
        self._pernas = pernas
        self.executados: list[tuple] = []

    def execute(self, sql, args=None):
        self.executados.append((sql, args))

    def fetchone(self):
        return {"games": json.dumps(self._pernas)}

    def close(self):
        pass


# ── 1 · quem ainda tem o que responder ──────────────────────────────────────
class TestPernaSemVeredito:
    def test_perna_sem_result_conta(self):
        assert live._perna_sem_veredito({"fixture_id": 1, "result": None}) is True

    def test_perna_ja_liquidada_nao_conta(self):
        assert live._perna_sem_veredito({"fixture_id": 1, "result": "GREEN"}) is False
        assert live._perna_sem_veredito({"fixture_id": 1, "result": "PUSH"}) is False

    def test_lixo_gravado_por_versao_antiga_conta_como_ausente(self):
        assert live._perna_sem_veredito({"fixture_id": 1, "result": "pendente"}) is True

    def test_jogo_que_nem_comecou_nao_e_perguntado(self):
        # Não gastar chamada de API com jogo que ainda vai rolar é a mesma
        # economia que o resto da varredura já faz.
        assert live._perna_sem_veredito({"fixture_id": 7, "result": None}, {7}) is False

    def test_perna_sem_fixture_nao_tem_o_que_perguntar(self):
        assert live._perna_sem_veredito({"result": None}) is False


# ── 2 · o veredito gravado não é apagado ────────────────────────────────────
class TestGravarNaoApaga:
    def test_none_nao_derruba_perna_ja_liquidada(self):
        cur = _CursorDeUmBilhete([{"fixture_id": 1, "result": "GREEN"},
                                  {"fixture_id": 2, "result": None}])
        saida = live._gravar_resultado_das_pernas(cur, "picks_multiplas", 1, [None, "RED"])
        pernas = json.loads(saida)
        assert pernas[0]["result"] == "GREEN", "um GREEN gravado não pode virar null"
        assert pernas[1]["result"] == "RED"

    def test_veredito_novo_sobrescreve_o_antigo(self):
        # Reconferência do provedor continua podendo corrigir uma perna.
        cur = _CursorDeUmBilhete([{"fixture_id": 1, "result": "RED"}])
        pernas = json.loads(
            live._gravar_resultado_das_pernas(cur, "picks_multiplas", 1, ["GREEN"]))
        assert pernas[0]["result"] == "GREEN"


# ── 3 · a passada que completa as pernas existe, e é só detalhe ─────────────
class TestPassadaDeCompletarPernas:
    def _fonte(self):
        import inspect
        fonte = inspect.getsource(live.resolve_all_pending)
        return "\n".join(l for l in fonte.split("\n") if not l.lstrip().startswith("#"))

    def test_bilhete_ja_fechado_volta_a_ser_lido(self):
        assert "result IS NOT NULL" in self._fonte(), (
            "sem reler bilhete fechado, a perna deixada em aberto pelo "
            "fechamento antecipado no RED nunca é preenchida")

    def test_a_passada_nao_toca_em_result_nem_em_profit(self):
        import inspect
        fonte = inspect.getsource(live.resolve_all_pending)
        inicio = fonte.index("A PERNA QUE FICOU PRA TRAS")
        trecho = fonte[inicio:fonte.index("ALAVANCAGEM", inicio)]
        assert "SET games = %s" in trecho
        assert "SET result" not in trecho, (
            "o bilhete estava certo; reescrever result/profit aqui mexeria na "
            "banca de quem seguiu por causa de exibição")

    def test_a_contagem_separa_perna_de_pick(self):
        import inspect
        assert '"pernas": 0' in inspect.getsource(live.resolve_all_pending)


# ── 4 · o bilhete continua fechando cedo, e certo ───────────────────────────
class TestBilheteMorreNoPrimeiroRed:
    def test_uma_perna_red_fecha_o_bilhete_com_a_outra_em_aberto(self):
        assert live._bilhete_morto(["RED", None]) is True

    def test_perna_em_aberto_sozinha_nao_fecha_nada(self):
        assert live._bilhete_morto(["GREEN", None]) is False

    def test_o_red_do_bilhete_custa_a_entrada_inteira(self):
        assert settlement.combine_legs(["RED", "GREEN"], [1.40, 1.80], 2.52)[1] == -1
