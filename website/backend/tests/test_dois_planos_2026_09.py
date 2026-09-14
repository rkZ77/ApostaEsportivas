"""Dois planos de assinatura: Pick IA e Pick IA Pro (12/09/2026).

O que estes testes guardam é a ideia inteira do desenho: o tier é uma coluna
SEPARADA de `users.plan`, e não mais um valor dela. Se alguém "simplificar"
isso um dia, os ~25 `is_vip_active` e os ~20 `require_vip` espalhados pelos
routers passam a responder False pra quem paga, e cada produto que ficar sem
revisão vira um paywall no lugar errado.

O resto é o furo que já aconteceu duas vezes com um plano só (o sino em 10/09,
o `follow` no mesmo dia): toda porta lateral que entrega a análise tem que
enxergar o tier, não só a assinatura.
"""
import ast
import os
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.append(str(_BACKEND))


def _fonte(*partes: str) -> str:
    return (_BACKEND.joinpath(*partes)).read_text(encoding="utf-8")


# ── o catálogo ────────────────────────────────────────────────────────────
class TestCatalogo:
    def test_as_chaves_antigas_nao_mudaram_de_nome(self):
        """O `external_reference` do MercadoPago é "<user_id>:<chave>".

        Renomear "mensal" quebraria a conciliação de todo pagamento já feito
        (que é manual, filtrando por essa string) e qualquer link de checkout
        ainda aberto no navegador de alguém. As quatro chaves sem sufixo
        continuam existindo, e agora são o Pro.
        """
        from routers.payments import PLANS

        for chave in ("mensal", "trimestral", "semestral", "anual"):
            assert chave in PLANS, f"{chave} sumiu: pagamento antigo fica órfão"
            assert PLANS[chave]["tier"] == "pro"

    def test_o_preco_do_pro_nao_subiu(self):
        """Ninguém da base toma aumento por causa desta mudança."""
        from routers.payments import PLANS

        assert PLANS["mensal"]["price"] == 39.90
        assert PLANS["trimestral"]["price"] == 99.90
        assert PLANS["semestral"]["price"] == 199.90
        assert PLANS["anual"]["price"] == 359.90

    def test_a_entrada_custa_menos_em_todos_os_ciclos(self):
        from routers.payments import PLANS, TIER_MENSAL

        for ciclo in ("mensal", "trimestral", "semestral", "anual"):
            base = PLANS[f"{ciclo}_base"]["price"]
            pro = PLANS[ciclo]["price"]
            assert base < pro, f"{ciclo}: entrada não pode custar mais que o Pro"
        assert TIER_MENSAL == {"base": "mensal_base", "pro": "mensal"}

    def test_todo_plano_declara_tier_e_ciclo(self):
        from routers.payments import PLANS, CYCLE_LABELS, TIER_LABELS

        for chave, info in PLANS.items():
            assert info["tier"] in TIER_LABELS, chave
            assert info["cycle"] in CYCLE_LABELS, chave

    def test_o_desconto_compara_com_o_mensal_do_mesmo_produto(self):
        """Comparar o anual do Pick IA com o mensal do Pro anunciaria um
        desconto que não existe, que é a mesma classe de erro do "17% num
        plano de 16%" que já foi ao ar."""
        from routers.payments import _plan_payload, PLANS

        anual = _plan_payload("anual_base")
        cheio = PLANS["mensal_base"]["price"] * anual["months"]
        assert anual["save_pct"] == round((1 - anual["price"] / cheio) * 100)
        assert _plan_payload("mensal_base")["save_pct"] == 0

    def test_o_catalogo_publico_entrega_os_dois_produtos(self):
        from routers.payments import list_plans

        tiers = {p["tier"] for p in list_plans()["plans"]}
        assert tiers == {"base", "pro"}


# ── o gate ────────────────────────────────────────────────────────────────
class TestGateDeTier:
    def _user(self, plan="vip", tier="pro", expira="2099-01-01T00:00:00"):
        return {"id": 1, "plan": plan, "plan_tier": tier, "plan_expires_at": expira}

    def test_o_assinante_de_entrada_continua_sendo_vip(self):
        """O ponto inteiro do desenho: ele paga, então `is_vip_active` diz
        sim, e todo produto de pré-jogo continua aberto pra ele sem nenhum
        router ter sido tocado."""
        from auth_utils import is_vip_active, tem_tier_pro

        base = self._user(tier="base")
        assert is_vip_active(base) is True
        assert tem_tier_pro(base) is False

    def test_o_pro_passa_nos_dois(self):
        from auth_utils import is_vip_active, tem_tier_pro

        assert tem_tier_pro(self._user(tier="pro")) is True

    def test_free_nao_passa_nem_com_tier_pro_na_coluna(self):
        """A coluna nasce com DEFAULT 'pro' pra não rebaixar a base antiga,
        então TODO free tem 'pro' escrito nela. Ler o tier sozinho liberaria
        o site inteiro: os dois gates andam juntos, sempre."""
        from auth_utils import tem_tier_pro

        assert tem_tier_pro({"id": 1, "plan": "free", "plan_tier": "pro"}) is False

    def test_plano_vencido_nao_passa(self):
        from auth_utils import tem_tier_pro

        vencido = self._user(expira="2020-01-01T00:00:00")
        assert tem_tier_pro(vencido) is False

    def test_trial_e_admin_veem_o_produto_inteiro(self):
        """Um trial que esconde metade do produto vende menos que nenhum."""
        from auth_utils import tem_tier_pro

        assert tem_tier_pro(self._user(plan="trial", tier="base")) is True
        assert tem_tier_pro({"id": 1, "plan": "admin", "plan_tier": "base"}) is True

    def test_tier_ausente_e_lido_como_pro(self):
        """Quem assinou antes de 12/09 não tem valor nenhum na coluna quando
        o dict vem de um caminho que não a seleciona. O default nunca pode
        tirar acesso de quem já pagou."""
        from auth_utils import tem_tier_pro

        assert tem_tier_pro({"id": 1, "plan": "vip", "plan_expires_at": None}) is True


# ── as portas laterais ────────────────────────────────────────────────────
class TestOTierNaoVazaPelasLaterais:
    """Com UM plano, a análise vazou pelo sino e pelo `follow` (10/09/2026).
    Com dois, cada uma dessas portas precisa enxergar o tier, não a assinatura.
    """

    def test_o_feed_ao_vivo_corta_pelo_tier(self):
        src = _fonte("routers", "live_picks.py")
        assert "tem_ao_vivo = tem_tier_pro(current_user)" in src
        assert "if not tem_ao_vivo:" in src, (
            "o corte do teaser tem que ser por tier: com `is_vip_active` o "
            "assinante Pick IA receberia o pick ao vivo completo"
        )

    def test_o_ao_vivo_exige_o_pro_nas_rotas(self):
        src = _fonte("routers", "live_picks.py")
        assert "def require_live_reader(user: dict = Depends(require_pro))" in src

    def test_seguir_pick_ao_vivo_exige_o_pro(self):
        """Seguir é ler: o teaser entrega o id do pick, e a Banca devolve
        market, line e odd de tudo que o usuário segue."""
        src = _fonte("routers", "banca.py")
        trecho = src[src.index("def _pode_seguir"):]
        trecho = trecho[:trecho.index("@router.post(\"/follow\")")]
        assert 'if pick_type == "live":' in trecho
        assert "tem_tier_pro(user)" in trecho

    def test_o_mural_do_pick_ao_vivo_exige_o_pro(self):
        from routers.social import _pode_ver_social

        base = {"id": 1, "plan": "vip", "plan_tier": "base",
                "plan_expires_at": "2099-01-01T00:00:00"}
        assert _pode_ver_social("live", base) is False
        assert _pode_ver_social("vip", base) is True
        assert _pode_ver_social("free", base) is True

    def test_o_sino_do_ao_vivo_so_alcanca_o_pro(self):
        src = _fonte("routers", "notifications.py")
        trecho = src[src.index("def notificar_pick_live_novo"):]
        trecho = trecho[:trecho.index("LIVE_NOVO_JANELA_MIN")]
        assert "notify_pro_users(" in trecho
        assert "notify_all_users(" not in trecho
        assert "notify_vip_users(" not in trecho

    def test_a_clausula_sql_do_pro_e_a_traducao_do_gate_python(self):
        """Mesma lista de planos, mesma leitura de vencimento, e o tier só
        cobrado de quem paga em `vip`."""
        from routers.notifications import SQL_PRO_ATIVO

        sql = " ".join(SQL_PRO_ATIVO.split())
        assert "u.plan IN ('vip', 'trial', 'admin')" in sql
        assert "u.expires_at > NOW()" in sql
        assert "COALESCE(u.plan_tier, 'pro') = 'pro'" in sql
        assert "u.plan <> 'vip' OR" in sql, "admin e trial não podem ser cortados"

    def test_o_agente_de_chat_separa_os_dois_recados(self):
        """Dizer "assine" pra quem já assinou parece defeito do site."""
        src = _fonte("routers", "chat.py")
        assert "if not is_vip_active(current_user):" in src
        assert "if not tem_tier_pro(current_user):" in src
        assert "_UPGRADE_PRO" in src


# ── a compra ──────────────────────────────────────────────────────────────
class TestOPagamentoNaoTiraNada:
    def test_comprar_a_entrada_nao_rebaixa_quem_tem_pro_ativo(self):
        """Mesmo princípio do GREATEST no `expires_at`: comprar nunca pode
        tirar do usuário algo que ele já pagou."""
        src = _fonte("routers", "payments.py")
        assert "pro_ainda_ativo" in src
        assert 'tier_novo = "pro" if (plan_info["tier"] == "pro" or pro_ainda_ativo) else "base"' in src

    def test_o_update_grava_o_tier(self):
        src = _fonte("routers", "payments.py")
        assert "UPDATE users SET plan='vip', plan_tier=%s" in src

    def test_o_brinde_de_indicacao_e_o_plano_de_entrada(self):
        """Dois dias de presente não podem virar dois dias de Ao Vivo só
        porque a coluna nasceu com DEFAULT 'pro'."""
        src = _fonte("routers", "payments.py")
        trecho = src[src.index("SELECT referred_by"):]
        assert "plan_tier  = CASE WHEN plan IN ('free', 'trial') THEN 'base'" in trecho


# ── a migration ───────────────────────────────────────────────────────────
def test_a_coluna_nasce_pro_pra_nao_rebaixar_a_base():
    src = _fonte("migrations.py")
    assert "ADD COLUMN IF NOT EXISTS plan_tier" in src
    assert "DEFAULT 'pro'" in src


def test_a_sessao_le_o_tier_do_banco():
    """O claim do JWT fica defasado por até 12h: um upgrade pago tem que
    valer no request seguinte, não no login seguinte."""
    src = _fonte("auth_utils.py")
    assert "plan, plan_tier, expires_at FROM users" in src
    assert 'payload["plan_tier"] = row.get("plan_tier") or "pro"' in src
