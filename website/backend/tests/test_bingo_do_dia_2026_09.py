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

class TestAFlagDeVisibilidade:
    """`BINGO_ENABLED` existe pra que qualquer outro commit vá pra produção sem
    levar o Bingo junto enquanto ele é medido (decisão do usuário, 09/09).

    Estes testes NÃO afirmam o valor dela: `dev` e `noprod` sobem com `true` e
    `main` sobe com `false`, então travar o valor quebraria a branch de
    produção de propósito. O que se trava é a LIGAÇÃO: os quatro lugares onde o
    produto aparece têm que perguntar pela flag. Um deles esquecido é o vazamento
    inteiro, e ele não daria erro nenhum.
    """

    def _front(self, caminho: str) -> str:
        alvo = os.path.join(os.path.dirname(_BACKEND), "frontend", "src", caminho)
        with open(alvo, encoding="utf-8") as fh:
            return fh.read()

    def test_a_flag_e_uma_constante_no_config_e_nao_uma_env(self):
        """Variável de ambiente que ninguém configura é só um caminho a mais
        pro produto sumir por engano · foi o que aconteceu com o Live em 28/08.
        Constante aparece no diff."""
        cfg = self._front("config.ts")
        assert "export const BINGO_ENABLED" in cfg
        assert "VITE_BINGO" not in cfg, "a flag virou env var e some sem rastro"

    def test_a_aba_pergunta_pela_flag(self):
        src = self._front("pages/Picks.tsx")
        assert "oculta: !BINGO_ENABLED" in src

    def test_a_secao_da_aba_hoje_pergunta_pela_flag(self):
        src = self._front("pages/Picks.tsx")
        assert "if (!BINGO_ENABLED) return null" in src

    def test_o_bloco_da_aba_pergunta_pela_flag(self):
        src = self._front("pages/Picks.tsx")
        assert "tab === 'bingo' && BINGO_ENABLED" in src

    def test_o_filtro_de_resultados_pergunta_pela_flag(self):
        src = self._front("pages/ResultadosPublicos.tsx")
        assert "BINGO_ENABLED" in src

    def test_o_botao_do_admin_pergunta_pela_flag(self):
        """O que impede um clique distraído de publicar cartela em produção."""
        src = self._front("pages/Admin.tsx")
        assert "BINGO_ENABLED" in src
        assert "'gerar_bingo'" in src

    def test_o_backend_continua_ligado_de_proposito(self):
        """Um segundo interruptor do lado do servidor seria um par pra manter
        em sincronia, e par fora de sincronia é como o produto some pela
        metade. Em produção a tabela está vazia, então não há o que esconder."""
        import pick_sources
        assert any(f[0] == "bingo" for f in pick_sources._FONTES)

