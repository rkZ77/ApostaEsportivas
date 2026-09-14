"""A aba Meu Plano, e o que ela diz pra quem ainda não paga (14/09/2026).

Quem abre "Meu Plano" sem ter plano está na pergunta "vale a pena?". A tela
respondia com uma faixa de uma linha: a letra F, "1 pick gratuito por dia" e um
botão. Sem preço, sem o que existe do outro lado, sem resultado nenhum.

Estes testes guardam as três respostas que ela passou a dar, e o par de bugs de
contagem que apareceu junto.
"""
from pathlib import Path

_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _tela() -> str:
    return (_FRONT / "pages" / "Planos.tsx").read_text(encoding="utf-8")


def _contexto() -> str:
    return (_FRONT / "context" / "AuthContext.tsx").read_text(encoding="utf-8")


# ── a contagem de dias ────────────────────────────────────────────────────
class TestOsDoisNumerosConcordam:
    def test_o_dia_e_truncado_como_no_backend(self):
        """Era `Math.ceil`, e num trial de 2 dias recém-ativado a tela mostrava
        "3 dias restantes" em letra grande com "Expira em 2d 2h 59m" logo
        acima: dois números sobre a mesma coisa, discordando, e o maior deles
        sendo o mais visível."""
        src = _contexto()
        assert "Math.floor(diff / (1000 * 60 * 60 * 24))" in src
        assert "Math.ceil(diff" not in src

    def test_o_ultimo_dia_nao_vira_expirado(self):
        """Com a contagem truncada, `remaining` chega a 0 com o acesso ainda
        valendo. Dizer "Expirado" pra quem ainda pode usar o produto é o pior
        erro possível nesta tela."""
        src = _tela()
        assert "'Último dia'" in src
        assert "aindaVale" in src

    def test_a_barra_mede_tempo_e_nao_dia_inteiro(self):
        """Senão ela zera no último dia com o acesso valendo."""
        src = _tela()
        assert "msRestantes" in src
        trecho = src[src.index("const pct"):src.index("const pct") + 300]
        assert "msRestantes" in trecho


# ── o que o plano abre ────────────────────────────────────────────────────
class TestAListaDoPlanoSaiDoCatalogo:
    def test_nao_ha_lista_escrita_a_mao(self):
        """A lista tinha envelhecido: prometia seis itens e não citava Pick
        Boost, Pick Jogador, faltas, goleiros nem o ao vivo."""
        src = _tela()
        assert "'Picks VIP (10 a 20/dia)'" not in src
        assert "'Agente IA de futebol'" not in src
        assert "modulosDoPlano" in src

    def test_o_assinante_de_entrada_nao_ve_o_que_nao_tem(self):
        """Com dois planos a lista passou a MENTIR pra quem tem o Pick IA,
        anunciando o agente de futebol, que é do Pro."""
        src = _tela()
        assert "temPickIABase ? MODULOS_PAGOS : [...MODULOS_PAGOS, ...MODULOS_PRO]" in src

    def test_o_trial_nao_e_tratado_como_candidato_a_upgrade(self):
        """O trial abre o Pro inteiro, então oferecer o Pro a ele faz a tela
        parecer desatenta."""
        src = _tela()
        assert "const tierAtual      = isTrial || isAdmin ? 'pro'" in src

    def test_o_upgrade_mostra_a_diferenca_e_nao_o_preco_cheio(self):
        """Quem já paga não vai pagar de novo o que já paga: o número que
        decide o upgrade é o quanto ele custa A MAIS."""
        src = _tela()
        assert "planoDeUpgrade.price_per_month - planoAtual.price_per_month" in src

    def test_o_upgrade_compara_o_mesmo_ciclo(self):
        """Comparar com o mensal enquanto ela tem anual daria um número que
        não é o dela."""
        src = _tela()
        trecho = src[src.index("const planoDeUpgrade"):]
        trecho = trecho[:trecho.index("\n\n")]
        assert "p.cycle === planoAtual.cycle" in trecho


# ── a conta sem plano ─────────────────────────────────────────────────────
class TestOFreeVeUmaOfertaDeVerdade:
    def _bloco_do_free(self) -> str:
        src = _tela()
        ini = src.index("{user && !activated && !isVip && !isAdmin && !isTrial && (")
        return src[ini:ini + 4000]

    def test_mostra_a_prova_publica(self):
        """É o único argumento que não é opinião nossa."""
        assert "<ProvaPublica compacta />" in self._bloco_do_free()

    def test_mostra_o_que_esta_fechado(self):
        """Sem a lista do que existe do outro lado, não há decisão a tomar."""
        bloco = self._bloco_do_free()
        assert "O que está fechado hoje" in bloco
        assert "[...MODULOS_PAGOS, ...MODULOS_PRO]" in bloco

    def test_mostra_o_preco_de_entrada(self):
        """Uma tela de plano sem preço obriga a pessoa a ir procurar em outra."""
        bloco = self._bloco_do_free()
        assert "monthlyBase" in bloco
        assert "fmtPlanPrice(monthlyBase.price)" in bloco

    def test_o_preco_nao_e_digitado(self):
        """Mesmo motivo de sempre: o valor anunciado tem que ser o cobrado."""
        bloco = self._bloco_do_free()
        for digitado in ("29,90", "39,90", "R$ 29", "R$ 39"):
            assert digitado not in bloco, digitado

    def test_diz_que_nao_ha_renovacao_automatica(self):
        """É a objeção mais comum de quem assina qualquer coisa no Brasil, e a
        resposta é favorável ao produto."""
        assert "SEM_RENOVACAO_AUTOMATICA" in self._bloco_do_free()


def test_a_tela_oferece_uma_vez_so():
    """A faixa "Quer o acesso completo?" era a segunda oferta da MESMA tela pra
    mesma pessoa, e as duas discordavam: ela dizia "a partir de R$ 39,90" com
    quatro módulos escritos à mão, enquanto o card do topo já mostrava o
    catálogo inteiro a partir de R$ 29,90. Duas ofertas com dois preços é pior
    que nenhuma."""
    src = _tela()
    assert "Quer o acesso completo?" not in src
