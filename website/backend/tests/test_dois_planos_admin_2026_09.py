"""O admin e a cobrança com dois planos (12/09/2026).

A primeira leva dos dois planos parou no site. Estes testes cobrem o que ficou
de fora e só apareceu na revisão: a tela que existe pra CONSERTAR assinatura
não conhecia as chaves novas, e o aviso de vencimento chamava os dois produtos
pelo nome de nenhum deles.
"""
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.append(str(_BACKEND))


# ── o admin ───────────────────────────────────────────────────────────────
class TestAdminConheceOsOitoPlanos:
    def test_o_ciclo_valido_sai_do_catalogo(self):
        """A lista era literal com as quatro chaves antigas, então o admin que
        tentasse ajustar na mão um assinante do Pick IA levava "Tipo inválido"
        justamente na tela que existe pra consertar o que o webhook errou."""
        from routers.admin import _valid_sub_types
        from routers.payments import PLANS

        validos = _valid_sub_types()
        for chave in PLANS:
            assert chave in validos, chave
        assert None in validos, "limpar o campo tem que continuar valendo"

    def test_o_body_aceita_as_chaves_novas(self):
        from routers.admin import UpdateUserBody

        for chave in ("mensal_base", "anual_base", "mensal", "anual"):
            assert UpdateUserBody(subscription_type=chave).subscription_type == chave

    def test_o_body_recusa_chave_inventada(self):
        from routers.admin import UpdateUserBody

        with pytest.raises(ValueError):
            UpdateUserBody(subscription_type="quinzenal")

    def test_o_admin_pode_trocar_o_produto(self):
        """Sem isto ele só conseguia mexer no plano e na data: conceder ou
        corrigir o Pick IA Pro na mão não tinha porta nenhuma."""
        from routers.admin import UpdateUserBody

        assert UpdateUserBody(plan_tier="base").plan_tier == "base"
        assert UpdateUserBody(plan_tier="pro").plan_tier == "pro"
        with pytest.raises(ValueError):
            UpdateUserBody(plan_tier="premium")

    def test_o_update_grava_o_tier(self):
        src = (_BACKEND / "routers" / "admin.py").read_text(encoding="utf-8")
        assert 'fields.append("plan_tier = %s")' in src

    def test_a_listagem_devolve_o_tier(self):
        src = (_BACKEND / "routers" / "admin.py").read_text(encoding="utf-8")
        trecho = src[src.index("def list_users"):]
        assert "u.plan_tier" in trecho[:1200]


class TestOsNumerosSeparamOsDoisProdutos:
    """Somar os dois planos num número só esconde exatamente o que a mudança
    de preço quis medir: quantos ficaram na entrada e quantos subiram."""

    def test_a_receita_conta_os_dois(self):
        src = (_BACKEND / "routers" / "admin.py").read_text(encoding="utf-8")
        assert "AS active_base" in src and "AS active_pro" in src
        assert '"active_base": int(ativos["active_base"])' in src.replace("  ", " ") \
            or '"active_base"' in src

    def test_as_stats_contam_os_dois(self):
        src = (_BACKEND / "routers" / "admin.py").read_text(encoding="utf-8")
        assert "AS vip_base" in src and "AS vip_pro" in src

    def test_o_total_antigo_continua_existindo(self):
        """`active_vip` é o que o resto da tela usa: tirar quebraria o card."""
        src = (_BACKEND / "routers" / "admin.py").read_text(encoding="utf-8")
        assert "AS active_vip" in src

    def test_a_contagem_le_o_tier_so_de_quem_paga(self):
        """`plan_tier` nasce com DEFAULT 'pro' em TODA linha, free inclusive.
        Contar sem filtrar `plan = 'vip'` transformaria a base inteira em
        assinante do Pro."""
        src = (_BACKEND / "routers" / "admin.py").read_text(encoding="utf-8")
        trecho = src[src.index("AS vip_base") - 400:src.index("AS vip_pro") + 40]
        assert trecho.count("plan = 'vip'") >= 2


# ── o aviso de vencimento ─────────────────────────────────────────────────
class TestOAvisoNomeiaOProduto:
    def test_o_job_de_vencidos_carrega_o_tier(self):
        """Sem a coluna no SELECT, todo assinante do plano de entrada recebia
        o texto do Pro."""
        src = (_BACKEND / "plan_expiry.py").read_text(encoding="utf-8")
        assert "SELECT id, name, email, plan, plan_tier, expires_at" in src

    def test_o_login_carrega_o_tier(self):
        src = (_BACKEND / "routers" / "auth.py").read_text(encoding="utf-8")
        assert "password_hash, plan, plan_tier, active" in src

    def test_o_me_carrega_o_tier(self):
        src = (_BACKEND / "routers" / "auth.py").read_text(encoding="utf-8")
        assert "u.plan_tier" in src or "plan, plan_tier, active" in src


# ── a cobrança ────────────────────────────────────────────────────────────
class TestOMercadoPagoLeDoCatalogo:
    def test_a_preferencia_sai_toda_do_catalogo(self):
        """Título, preço e referência do MercadoPago não podem ser escritos à
        mão: é assim que o valor anunciado deixa de bater com o cobrado."""
        src = (_BACKEND / "routers" / "payments.py").read_text(encoding="utf-8")
        trecho = src[src.index('@router.post("/create")'):]
        trecho = trecho[:trecho.index('@router.post', 10)]
        assert "PLANS.get(body.plan)" in trecho
        assert 'plan_info["title"]' in trecho
        assert 'plan_info["price"]' in trecho
        assert 'f"{current_user[\'sub\']}:{body.plan}"' in trecho

    def test_todo_plano_do_catalogo_e_comprável(self):
        """O webhook resolve o plano por `PLANS.get(chave)`: uma chave que o
        catálogo publica e o webhook não conhece vira pagamento aprovado sem
        acesso liberado."""
        from routers.payments import PLANS, list_plans

        for p in list_plans()["plans"]:
            assert p["id"] in PLANS, p["id"]
            assert PLANS[p["id"]]["price"] == p["price"]
