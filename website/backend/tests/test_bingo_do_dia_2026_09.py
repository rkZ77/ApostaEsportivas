"""Bingo do Dia: a cartela de 4 pernas, uma por dia (2026-09-08).

O QUE O PRODUTO PROMETE, E O QUE ESTE ARQUIVO TRAVA
---------------------------------------------------
Quatro seleções, em quatro jogos DIFERENTES, cada uma cotada entre 1.40 e
2.00, uma cartela por dia. E a régua de cada perna é a do VIP, não uma régua
nova: foi o pedido explícito ("motor idêntico ao do VIP com todas as premissas
mapeadas").

Cada uma dessas frases é uma linha aqui, porque cada uma delas se perde de um
jeito silencioso:

  · a faixa por perna mora em `BINGO_CONFIG`, e um `enforce_odd_band=False`
    ali não quebra nada -- só faz a cartela sair com uma perna de 1.15;
  · "quatro jogos diferentes" é o que sustenta o `prob_combinada`: o produto
    das probabilidades foi MEDIDO em 2026-08-20 sobre 1.960 bilhetes de pernas
    em jogos diferentes (-0,7pp de viés). Aceitar duas pernas do mesmo jogo
    tiraria a conta do recorte medido sem nenhum erro aparecer na tela;
  · "a régua é a do VIP" é uma afirmação sobre AUSÊNCIA de parâmetro próprio.
    O jeito de ela se perder é alguém ajustar um limiar só do bingo, e o único
    lugar onde isso ficaria visível é aqui.

E o produto novo tem que ser CONTABILIZADO em todo lugar, que é a lição que
`pick_sources.py` documenta: tipo que falta num mapa não dá erro, a aposta só
some da tela. O teste geral disso é
test_contabilizacao_de_todos_os_produtos_2026_08.py, que já cobre o bingo
sozinho porque deriva das listas. O que fica aqui é o que é específico DESTE
produto.
"""
import os
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# O motor vem pelo mesmo caminho que o backend já usa em produção.
import settlement_bridge  # noqa: F401,E402  (monta o sys.path do motor)

from engine_pipelines import bingo_pipeline as bingo          # noqa: E402
from services.pick_engine.config import BINGO_CONFIG, VIP_CONFIG, DEFAULT_CONFIG  # noqa: E402
from services.pick_engine.staking import calculate_stake      # noqa: E402


def _perna(fixture_id: int, odd: float, taxa: float, score: float,
           market_type: str = "goals") -> dict:
    return {"odd": odd, "taxa_real": taxa, "final_score": score,
            "market_type": market_type,
            "_fixture": {"fixture_id": fixture_id}}


# ─────────────────────────── O FORMATO DO PRODUTO ───────────────────────────

class TestOFormatoDaCartela:

    def test_sao_quatro_pernas_e_nao_ate_quatro(self):
        """Cartela de 3 não é bingo, é múltipla. O número é o produto."""
        assert bingo.PERNAS == 4

    def test_a_faixa_por_perna_e_1_40_a_2_00(self):
        assert (bingo.ODD_PERNA_MIN, bingo.ODD_PERNA_MAX) == (1.40, 2.00)

    def test_a_faixa_do_produto_e_a_da_config_do_motor(self):
        """Os dois números dizem a MESMA coisa por caminhos diferentes: o
        pipeline checa no fim, o motor barra antes de virar candidato. Se eles
        divergirem, a cartela sai com uma perna que o produto não aceita ou
        deixa de sair por um motivo que ninguém consegue nomear."""
        assert BINGO_CONFIG.min_odd == bingo.ODD_PERNA_MIN
        assert BINGO_CONFIG.max_odd == bingo.ODD_PERNA_MAX
        assert BINGO_CONFIG.conservative_odd_low == bingo.ODD_PERNA_MIN
        assert BINGO_CONFIG.conservative_odd_high == bingo.ODD_PERNA_MAX

    def test_a_faixa_e_filtro_e_nao_preferencia(self):
        """`enforce_odd_band=False` não quebra nada · só faz a linha fora da
        faixa voltar a competir, com edge maior, e vencer."""
        assert BINGO_CONFIG.enforce_odd_band is True


# ────────────────────── A RÉGUA É A DO VIP, MEDIDA ──────────────────────────

class TestAReguaEADoVip:

    @pytest.mark.parametrize("campo", [
        "min_taxa", "min_amostra", "min_confidence", "min_ev", "min_edge",
        "min_bookmakers_count", "odd_evaluation",
        "line_weight_taxa", "line_weight_edge", "line_weight_safety",
        "line_weight_bookmakers", "line_weight_stability",
        "safety_band_tilt", "round_line_push_penalty",
    ])
    def test_todo_criterio_de_qualidade_e_o_mesmo_do_vip(self, campo):
        """A ÚNICA divergência autorizada é a faixa de odd (e o teto que a
        acompanha). Qualquer outro limiar diferente aqui seria uma régua nova
        vestida de "igual ao VIP"."""
        assert getattr(BINGO_CONFIG, campo) == getattr(VIP_CONFIG, campo)

    def test_e_esses_criterios_sao_os_do_default_tambem(self):
        """O VIP não inventa limiar próprio: ele liga a faixa e usa o resto do
        default. Se um dia o VIP passar a ter limiar próprio, este teste cai
        junto com o de cima e a decisão volta pra mesa em vez de o bingo herdar
        em silêncio."""
        assert BINGO_CONFIG.min_taxa == DEFAULT_CONFIG.min_taxa
        assert BINGO_CONFIG.min_confidence == DEFAULT_CONFIG.min_confidence
        assert BINGO_CONFIG.min_edge == DEFAULT_CONFIG.min_edge

    def test_a_ia_revisa_a_cartela_no_provedor_do_vip(self):
        from services.pick_engine.ai_review import DEFAULT_PROVIDERS
        assert DEFAULT_PROVIDERS["bingo"] == DEFAULT_PROVIDERS["vip"]


# ─────────────────────── A ESCOLHA DAS QUATRO PERNAS ────────────────────────

class TestAEscolhaDaCartela:

    def test_quatro_jogos_diferentes(self):
        """O pool tem duas pernas do MESMO jogo, e as duas são as de maior
        score. A cartela ainda assim tem que sair com quatro partidas: duas
        pernas do mesmo jogo dariam a aparência de quatro chances com três, e
        o RED daquela partida derrubaria duas casas de uma vez."""
        pool = [
            _perna(1, 1.50, 0.72, 0.99),
            _perna(1, 1.60, 0.71, 0.98, market_type="corners"),
            _perna(2, 1.70, 0.70, 0.85),
            _perna(3, 1.80, 0.68, 0.80),
            _perna(4, 1.90, 0.66, 0.78),
        ]
        pernas, _score, _odd = bingo._find_cartela(pool)
        fixtures = [p["_fixture"]["fixture_id"] for p in pernas]
        assert sorted(fixtures) == [1, 2, 3, 4]
        assert len(set(fixtures)) == bingo.PERNAS

    def test_sem_quatro_jogos_a_cartela_nao_sai(self):
        """Três jogos não viram bingo. Não sair é a resposta certa · publicar
        uma cartela de três seria vender outro produto com o nome deste."""
        pool = [_perna(1, 1.50, 0.72, 0.9), _perna(2, 1.60, 0.71, 0.88),
                _perna(3, 1.70, 0.70, 0.85), _perna(3, 1.80, 0.68, 0.80)]
        assert bingo._find_cartela(pool) is None

    def test_perna_fora_da_faixa_nunca_entra(self):
        """1.20 com 90% de chance é a perna mais "certa" do pool, e é
        exatamente a que descaracteriza a cartela: ela não paga o risco das
        outras três."""
        pool = [_perna(1, 1.20, 0.90, 0.99), _perna(2, 1.70, 0.70, 0.85),
                _perna(3, 1.80, 0.68, 0.80), _perna(4, 1.90, 0.66, 0.78)]
        assert bingo._find_cartela(pool) is None
        assert bingo._na_faixa(_perna(9, 1.20, 0.9, 0.9)) is False
        assert bingo._na_faixa(_perna(9, 2.00, 0.5, 0.9)) is True
        assert bingo._na_faixa(_perna(9, 2.01, 0.5, 0.9)) is False

    def test_ordena_pela_chance_da_cartela_e_nao_pela_odd(self):
        """Odd alta é alerta, não qualidade (é a regra do site inteiro).

        Dentro de uma faixa de preço fixa, maximizar EV é maximizar odd · por
        isso o critério é `prob_combinada`. Aqui existem cinco jogos: o pool
        caro tem odd maior e chance menor, e ele NÃO pode ganhar.
        """
        pool = [
            _perna(1, 1.45, 0.75, 0.90),
            _perna(2, 1.45, 0.75, 0.90),
            _perna(3, 1.45, 0.75, 0.90),
            _perna(4, 1.45, 0.75, 0.90),
            _perna(5, 2.00, 0.55, 0.99),   # a mais cara, e a de menor chance
        ]
        pernas, _score, odd = bingo._find_cartela(pool)
        fixtures = sorted(p["_fixture"]["fixture_id"] for p in pernas)
        assert fixtures == [1, 2, 3, 4], "a perna cara não pode entrar por ser cara"
        assert odd == pytest.approx(1.45 ** 4, abs=1e-4)

    def test_nao_ha_faixa_de_odd_TOTAL(self):
        """A faixa é POR PERNA · o total é consequência dela.

        Somar um segundo intervalo por cima rejeitaria cartela boa por
        aritmética, que foi o problema que obrigou a alargar o teto da múltipla
        em 21/07. O piso e o teto possíveis são 1.40^4 e 2.00^4.
        """
        caro = [_perna(i, 2.00, 0.55, 0.9) for i in (1, 2, 3, 4)]
        _pernas, _score, odd = bingo._find_cartela(caro)
        assert odd == pytest.approx(16.0, abs=1e-4)

        barato = [_perna(i, 1.40, 0.78, 0.9) for i in (1, 2, 3, 4)]
        _pernas, _score, odd = bingo._find_cartela(barato)
        assert odd == pytest.approx(1.40 ** 4, abs=1e-4)


# ──────────────────────────── O DIMENSIONAMENTO ─────────────────────────────

class TestAStakeDaCartela:

    def test_kelly_recebe_a_chance_da_CARTELA(self):
        """Com `score_combo` (média de um score de ranqueamento) o Kelly satura
        o teto em qualquer bilhete e o dimensionamento vira constante · foi o
        erro corrigido na múltipla em 05/08. Aqui a prova é indireta e basta:
        chances diferentes têm que produzir stakes diferentes."""
        pouca, _ = calculate_stake(confidence=0.20, odd=6.0, ev=0.20, pick_type="bingo")
        muita, _ = calculate_stake(confidence=0.22, odd=6.0, ev=0.32, pick_type="bingo")
        assert muita > pouca

    def test_e_o_teto_de_2_por_cento_realmente_morde(self):
        """Os dois números acima são baixos de propósito · numa cartela com
        chance de 24% e odd 6.00 o Kelly de 1/4 já pede 2,2% da banca, e o teto
        corta. Isso não é o Kelly "morto": é o teto fazendo o serviço dele num
        produto de quatro pernas, onde o erro de cada perna entra no produto
        elevado à quarta potência. O teste de cima prova que o Kelly está vivo
        ABAIXO do teto; este prova que o teto existe acima dele."""
        acima, _ = calculate_stake(confidence=0.24, odd=6.0, ev=0.44, pick_type="bingo")
        bem_acima, _ = calculate_stake(confidence=0.45, odd=6.0, ev=1.70, pick_type="bingo")
        assert acima == bem_acima == 0.02

    def test_o_teto_e_um_degrau_abaixo_da_multipla(self):
        """Quatro eventos, não dois ou três: o erro de cada perna entra no
        produto elevado à quarta potência."""
        from routers.banca import STAKE_LIMITS
        assert STAKE_LIMITS["bingo"][1] < STAKE_LIMITS["multipla"][1]

    def test_o_teto_do_motor_e_o_do_site_sao_o_mesmo_numero(self):
        """O motor grava `stake_pct` e o site recalcula a sugestão com a banca
        real. Tetos diferentes fariam o card anunciar uma unidade que o pick
        não tem · é o mesmo espelho que stake_plan.py mantém."""
        fonte = open(os.path.join(_BACKEND, "routers", "suggestions.py"),
                     encoding="utf-8").read()
        assert "'bingo': 0.02," in fonte
        motor = open(os.path.join(os.path.dirname(bingo.__file__), "..",
                                  "services", "pick_engine", "staking.py"),
                     encoding="utf-8").read()
        assert '"bingo":    (0.02, 0.25, 3),' in motor

    def test_o_peso_no_placar_publico_e_o_da_multipla(self):
        """Bilhete combinado entra com 1u · igualar a stake de uma entrada
        simples inflaria tanto o lucro dos meses bons quanto o buraco dos
        ruins."""
        from stake_plan import STAKE_PADRAO
        assert STAKE_PADRAO["bingo"] == STAKE_PADRAO["multiplas"] == 1


# ─────────────────────── UMA POR DIA, E A LIQUIDAÇÃO ────────────────────────

class TestUmaPorDia:

    def test_o_indice_unico_e_o_backstop(self):
        """O check em Python é select-then-insert, e corrida entre processos
        passa por cima dele · foi assim que a múltipla duplicou em 25/07, com
        2,5s de diferença. Quem impede de verdade é o índice."""
        fonte = open(bingo.__file__, encoding="utf-8").read()
        assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_picks_bingo_match_date_unique" in fonte
        assert "ON CONFLICT (match_date) WHERE bingo_name = 'BINGO_ENGINE' DO NOTHING" in fonte

    def test_o_site_tambem_cria_a_tabela(self):
        """`pick_sources` declara `picks_bingo` como fonte NÃO-opcional: um
        ambiente sem a tabela derrubaria o LEFT JOIN do ranking, da banca e do
        placar de uma vez. Por isso ela não pode depender de o motor ter
        rodado."""
        migr = open(os.path.join(_BACKEND, "migrations.py"), encoding="utf-8").read()
        assert "CREATE TABLE IF NOT EXISTS picks_bingo" in migr

    def test_a_cartela_liquida_pela_mesma_matematica_da_multipla(self):
        """Duas implementações de liquidação já produziram, uma vez, um PUSH de
        perna virando RED de um lado e PUSH do bilhete do outro."""
        from services.ai_result_checker_multiplas import _ALLOWED_MULTIPLAS_TABLES
        assert "picks_bingo" in _ALLOWED_MULTIPLAS_TABLES

    def test_as_pernas_entram_no_ledger(self):
        """Sem o nome do produto aqui o `fetch_all_legs` traria as quatro
        pernas e o ledger as descartaria caladas · e é o ledger que responde
        CLV e atribuição."""
        from services.picks_ledger_sync_service import _PICK_TYPE_BY_TABLE
        assert _PICK_TYPE_BY_TABLE["picks_bingo"] == "bingo"

    def test_a_folha_dos_quatro_jogos_e_buscada(self):
        """A cartela não liquida sozinha: alguém precisa pedir a folha das
        quatro partidas. Sem esta varredura ela ficaria esperando outro produto
        pedir a mesma fixture por acaso."""
        from collectors import match_statistics_sync_service as sync
        fonte = open(sync.__file__, encoding="utf-8").read()
        assert '("picks_multiplas", "picks_bingo")' in fonte


# ─────────────── A FLAG QUE SEGURA O PRODUTO FORA DE PRODUÇÃO ───────────────

class TestOGateDeAdmin:
    """O corte que segura o Bingo enquanto ele e' medido com dado de PRODUCAO.

    ELE MUDOU DE LUGAR EM 2026-09-10. Era `BINGO_ENABLED`, um booleano do FRONT
    que subia `false` pra `main`, e o comentario dele dizia por que aquilo
    bastava: em producao a tabela `picks_bingo` estava VAZIA, entao nao havia o
    que esconder. Com o motor publicando cartela em producao a premissa acabou
    -- um `/api/suggestions/today` no DevTools entregaria a cartela inteira,
    com pernas, mercados e odds, pra qualquer assinante.

    Hoje o corte e' do SERVIDOR (`feature_flags.bingo_visivel`), e o front so'
    deixa de desenhar o que o servidor ja' nao manda. Sao duas metades com o
    MESMO nome de constante, de proposito: par com nomes diferentes e' par que
    sai de sincronia.

        website/backend/feature_flags.py :: BINGO_BETA_ADMIN_ONLY
        website/frontend/src/config.ts   :: BINGO_BETA_ADMIN_ONLY

    Estes testes NAO afirmam o VALOR da flag: travar isso quebraria a liberacao
    do produto de proposito. O que se trava e' a LIGACAO -- cada lugar por onde
    a cartela sai tem que perguntar. Um esquecido e' o vazamento inteiro, e ele
    nao daria erro nenhum.
    """

    def _front(self, caminho: str) -> str:
        alvo = os.path.join(os.path.dirname(_BACKEND), "frontend", "src", caminho)
        with open(alvo, encoding="utf-8") as fh:
            return fh.read()

    def _backend(self, caminho: str) -> str:
        with open(os.path.join(_BACKEND, caminho), encoding="utf-8") as fh:
            return fh.read()

    # ── O gate em si ──────────────────────────────────────────────────────

    def test_o_gate_fechado_deixa_so_o_admin(self):
        """A REGRA do gate, medida com ele FECHADO, e nao o valor da flag.

        A flag abriu em 12/09 e estes dois testes afirmavam o valor dela --
        eram justamente os que o comentario da classe dizia pra nao escrever.
        Agora o teste liga a flag no lugar (monkeypatch) e cobra a regra, que
        e' a coisa que nao pode quebrar quando o produto for escondido de novo.
        """
        import feature_flags as ff
        monkey = ff.BINGO_BETA_ADMIN_ONLY
        ff.BINGO_BETA_ADMIN_ONLY = True
        try:
            assert ff.bingo_visivel({"plan": "admin"}) is True
            assert ff.bingo_visivel({"plan": "vip"}) is False
            assert ff.bingo_visivel({"plan": "free"}) is False
            # `user=None` e' o endpoint publico: com o gate fechado ele nao ve'
            # o produto nem no placar. Um total que conta cartela invisivel e'
            # pior que nao contar -- o usuario soma os produtos da tela e nao
            # chega no numero que o site mostra.
            assert ff.bingo_visivel(None) is False
        finally:
            ff.BINGO_BETA_ADMIN_ONLY = monkey

    def test_o_gate_aberto_vale_pra_todo_mundo(self):
        """Aberto, `bingo_visivel` para de ser um filtro: some' do caminho e
        deixa o paywall decidir (_FOLLOW_SO_VIP em banca.py, teaser em
        suggestions.py). Inclusive pro publico sem sessao, que passa a ver a
        cartela liquidada no placar, com o peso de 1u."""
        import feature_flags as ff
        monkey = ff.BINGO_BETA_ADMIN_ONLY
        ff.BINGO_BETA_ADMIN_ONLY = False
        try:
            assert ff.bingo_visivel({"plan": "vip"}) is True
            assert ff.bingo_visivel({"plan": "free"}) is True
            assert ff.bingo_visivel(None) is True
        finally:
            ff.BINGO_BETA_ADMIN_ONLY = monkey

    def test_a_flag_e_uma_constante_e_nao_uma_env(self):
        """Variavel de ambiente que ninguem configura e' so' um caminho a mais
        pro produto sumir por engano · foi o que aconteceu com o Live em 28/08.
        Constante aparece no diff.
        """
        import feature_flags as ff
        assert isinstance(ff.BINGO_BETA_ADMIN_ONLY, bool)
        assert "os.getenv" not in self._backend("feature_flags.py")

    def test_as_duas_metades_tem_o_MESMO_nome(self):
        """Par com nomes diferentes e' par que sai de sincronia · e foi
        exatamente assim que o /admin quebrou, com um lado renomeado e o outro
        importando o nome morto."""
        assert "export const BINGO_BETA_ADMIN_ONLY" in self._front("config.ts")
        assert "export const bingoVisivel" in self._front("config.ts")
        assert "VITE_BINGO" not in self._front("config.ts")

    # ── Todo caminho que serve bingo pergunta ─────────────────────────────

    @pytest.mark.parametrize("modulo", ["suggestions", "public", "banca"])
    def test_os_routers_que_servem_bingo_perguntam_pelo_gate(self, modulo):
        """Router que serve o produto e nao importa o gate e' um vazamento que
        nao levanta erro nenhum."""
        fonte = self._backend(os.path.join("routers", f"{modulo}.py"))
        assert "from feature_flags import bingo_visivel" in fonte
        assert "bingo_visivel(" in fonte

    def test_seguir_e_ler_entao_o_follow_tambem_fecha(self):
        """Seguir uma cartela e' ler a cartela: o pick entra na banca com perna,
        mercado e odd. Fechar so' a listagem deixaria a porta dos fundos."""
        fonte = self._backend(os.path.join("routers", "banca.py"))
        assert 'pick_type == "bingo" and not bingo_visivel(' in fonte

    # ── O front so' nao desenha o que o servidor nao manda ────────────────

    def test_a_aba_pergunta_pelo_gate(self):
        src = self._front("pages/Picks.tsx")
        assert "bingoVisivel(isAdmin)" in src
        assert "oculta: !verBingo" in src

    def test_o_filtro_de_resultados_pergunta_pelo_gate(self):
        src = self._front("pages/ResultadosPublicos.tsx")
        assert "bingoVisivel(" in src

    def test_o_admin_NAO_esconde_o_botao_de_gerar(self):
        """A pagina inteira e' de admin, e e' la' que a cartela e' gerada e
        medida durante o teste · esconder o botao de quem esta' medindo era o
        contrario do que o gate quer.

        O IMPORT, e nao a mencao: o comentario que explica por que o nome saiu
        precisa poder cita-lo. E o import e' o que de fato quebrava --
        `BINGO_ENABLED` deixou de existir em `config.ts` no rename, e o import
        que ficou pra tras nao derrubava so' o cartao do Bingo: derrubava o
        /admin INTEIRO em "Algo deu errado".
        """
        src = self._front("pages/Admin.tsx")
        assert "import { BINGO_ENABLED }" not in src, (
            "nome antigo · a constante nao existe mais e o import quebra a pagina")
        assert "gerar_bingo" in src

    def test_o_passo_continua_existindo_no_backend(self):
        """A flag decide o que APARECE, nunca o que existe · o /admin precisa do
        passo pra gerar a cartela que esta' sendo medida."""
        import routers.admin as adm
        assert "gerar_bingo" in adm._TUDO_STEPS
        assert adm._TUDO_STEPS_DERIVADA, (
            "os passos deixaram de sair do registro do motor e viraram copia")
