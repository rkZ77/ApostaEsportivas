"""O que acontece quando ESTES DOIS times se enfrentam · no motor Ao Vivo.

A LACUNA QUE ISTO FECHA

`baselines_por_liga` descreve a liga. `baseline_do_confronto` descreve os dois
times pelas medias DELES. Nenhuma das duas sabe o que a COMBINACAO produz.

E' a mesma lacuna que o rivalry_model fechou no pre-jogo, e o caso que o
originou foi caro: "Under cartoes" aprovado num Fluminense x Vasco de volta
valendo classificacao. A media dos 15 jogos de cada time e' de campeonato
normal, e nada no calculo sabia que aquele jogo especifico nao era normal.

RIVALIDADE MEDIDA, NAO LISTADA

Nao existe cadastro de classico. Se o par produz 13 escanteios por confronto
enquanto a liga promedia 10.2, o excesso e' o que aconteceu -- nao opiniao
sobre rivalidade. Par sem historico mede excesso zero e nao sofre ajuste.

E O ENCOLHIMENTO NAO INTRODUZ CONSTANTE NOVA

`shrink_to_baseline` e' a mesma funcao que o resto do motor usa pra media de
amostra curta. Inventar aqui um teto de excesso proprio seria escolher um
parametro onde ja' existe a formula que o projeto usa pra esta pergunta.
"""
from engine_pipelines import live_pipeline as lp

BASE = {"corners": 10.2, "goals": 2.72, "cards": 4.1}
ESTADO = {"home_team_id": 10, "away_team_id": 20, "league_id": 71}


class _Cursor:
    """Uma linha fixa · o alvo e' a CONTA, nao o SQL."""

    def __init__(self, linha):
        self.linha = linha

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return self.linha


def _h2h(corners=None, goals=None, n=0, estado=None, base=None):
    return lp.baseline_do_h2h(_Cursor((corners, goals, n)), estado or ESTADO, base or BASE)


class TestOExcessoEMedido:
    def test_par_quente_sobe_o_baseline(self):
        """13.5 escanteios por confronto contra 10.2 da liga."""
        assert _h2h(13.5, 3.4, 8)["corners"] > BASE["corners"]

    def test_par_frio_desce_o_baseline(self):
        """O modelo tem que funcionar nos dois sentidos · confronto travado e'
        tao informativo quanto classico pegado, e so' subir seria vies."""
        assert _h2h(7.0, 1.9, 8)["corners"] < BASE["corners"]

    def test_vale_pra_gols_tambem_e_nao_so_pra_escanteios(self):
        saida = _h2h(13.5, 3.4, 8)
        assert saida["goals"] > BASE["goals"]

    def test_par_que_joga_na_media_nao_sofre_ajuste(self):
        """Sem excesso, sem correcao · e' o que dispensa cadastrar classico."""
        saida = _h2h(BASE["corners"], BASE["goals"], 8)
        assert saida["corners"] == BASE["corners"]
        assert saida["goals"] == BASE["goals"]


class TestAmostraPesaNaConta:
    def test_um_confronto_so_quase_nao_move(self):
        """n=1 nao pode reescrever a expectativa · e' um jogo."""
        movimento = abs(_h2h(13.5, 3.4, 1)["corners"] - BASE["corners"])
        assert movimento < 1.0

    def test_muitos_confrontos_movem_de_verdade(self):
        pouco = abs(_h2h(13.5, 3.4, 1)["corners"] - BASE["corners"])
        muito = abs(_h2h(13.5, 3.4, 8)["corners"] - BASE["corners"])
        assert muito > pouco * 2

    def test_o_valor_fica_ENTRE_o_baseline_e_a_media_do_confronto(self):
        """Nunca extrapola: encolher e' andar na direcao, nao pular pra la'."""
        saida = _h2h(13.5, 3.4, 8)["corners"]
        assert BASE["corners"] < saida < 13.5

    def test_sem_confronto_nenhum_nao_mexe_em_nada(self):
        assert _h2h(None, None, 0) == {}


class TestNaoAtrapalhaOResto:
    def test_cartao_fica_de_fora(self):
        """Naquela familia quem manda e' o arbitro, que roda depois e
        sobrescreveria de qualquer jeito · duas correcoes empilhadas seriam
        dois ajustes pro mesmo fenomeno."""
        assert "cards" not in _h2h(13.5, 3.4, 8)

    def test_familia_sem_baseline_de_referencia_e_pulada(self):
        """Sem referencia nao ha excesso pra medir · o encolhimento precisa
        dos dois lados."""
        saida = _h2h(13.5, 3.4, 8, base={"goals": 2.72})
        assert "corners" not in saida and "goals" in saida

    def test_partida_sem_os_dois_times_nao_consulta(self):
        assert _h2h(13.5, 3.4, 8, estado={"home_team_id": 10}) == {}

    def test_erro_de_banco_nao_derruba_a_rodada(self):
        """Baseline melhor e' um plus, nao requisito."""
        class Explode(_Cursor):
            def execute(self, *a, **k):
                raise RuntimeError("banco fora")
        assert lp.baseline_do_h2h(Explode(None), ESTADO, BASE) == {}


class TestOrdemDaMistura:
    """O h2h refina o que ja' foi montado, e o arbitro continua por cima."""

    @property
    def fonte(self) -> str:
        import inspect
        return inspect.getsource(lp._processar_partida)

    def test_h2h_recebe_o_baseline_ja_montado_como_referencia(self):
        assert "baselines.update(baseline_do_h2h(cur, estado, baselines))" in self.fonte

    def test_o_arbitro_entra_antes_e_nao_e_desfeito_pelo_h2h(self):
        """Se o h2h mexesse em cards, ele desfaria a media do arbitro · o teste
        de cima (cartao fica de fora) e' o que garante, este fixa a ordem."""
        fonte = self.fonte
        assert fonte.index("**do_arbitro}") < fonte.index("baseline_do_h2h")
