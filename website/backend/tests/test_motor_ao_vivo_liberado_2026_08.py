"""O Motor Ao Vivo abrindo pro assinante (2026-08-27).

Ate' aqui o produto existia e ninguem via: o feed so' respondia pra admin, a aba
so' aparecia pra admin, e o unico aviso de pick ao vivo era "o pick QUE VOCE
SEGUIU entrou em jogo" -- que nao serve pra descobrir um pick que voce ainda nao
tem.

O QUE ESTE ARQUIVO TRAVA

  · a liberacao e' UMA variavel de ambiente dos dois lados, e nao um `if plan`
    espalhado. Sem isso, abrir o produto viraria deploy de codigo;
  · pick novo do motor gera notificacao PRA BASE, e nao por usuario. O produto
    tem janela de minutos: "abrir o site mais tarde" nao existe aqui;
  · o dedupe e' por PICK. Sem ele, um poll de 60 segundos encheria o sino de
    repeticao do mesmo pick;
  · pick liquidado ou com odd vencida NAO notifica. Mandar o assinante correr
    atras de um preco que nao existe mais e' pior que nao avisar.

Nada toca banco nem rede.
"""

import os
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

_FRONT = os.path.join(os.path.dirname(_BACKEND), "frontend", "src")


def _ler(*partes) -> str:
    with open(os.path.join(*partes), encoding="utf-8") as f:
        return f.read()


# ── a liberacao ──────────────────────────────────────────────────────────
class TestLiberacao:
    """O produto ABRIU em 27/08 e o padrao inverteu junto.

    Enquanto o motor estava em validacao, o default era fechado: esquecer a
    variavel so' custava uma aba escondida. Agora custa o contrario -- esquecer
    ESCONDERIA um produto que existe, e ninguem percebe: nao ha' quem reclame de
    uma aba que nao aparece nem de uma rota que responde 403 pra todo mundo.

    E' a mesma escolha de `SIDE_EFFECTS` e de `STATS_SWEEP`: default certo, e a
    variavel serve pra DESLIGAR sem deploy.
    """

    def test_o_backend_responde_pro_assinante_SEM_variavel_nenhuma(self, monkeypatch):
        monkeypatch.delenv("LIVE_PICKS_PUBLIC", raising=False)
        import routers.live_picks as live

        assinante = {"id": 1, "plan": "vip"}
        assert live.require_live_reader(assinante) is assinante

    @pytest.mark.parametrize("valor", ["off", "false", "0", "no", "nao", "OFF"])
    def test_a_variavel_sumiu_e_o_assinante_passa(self, monkeypatch, valor):
        """`LIVE_PICKS_PUBLIC` deixou de existir em 2026-08-28.

        Ela teve duas vidas: liberacao (o produto nascia admin-only) e, depois
        que o produto abriu, interruptor de emergencia. Morreu quando o usuario
        removeu as variaveis do Live no Railway -- um interruptor que ninguem
        configura e' so' um `if` a mais entre o assinante e o produto, e um
        caminho a mais pro produto sumir por engano.

        `require_vip` faz o trabalho todo. Este teste tranca que setar a
        variavel velha nao volta a barrar ninguem.
        """
        monkeypatch.setenv("LIVE_PICKS_PUBLIC", valor)
        import routers.live_picks as live

        vip = {"id": 1, "plan": "vip"}
        assert live.require_live_reader(vip) is vip

    def test_admin_tambem_passa(self, monkeypatch):
        monkeypatch.setenv("LIVE_PICKS_PUBLIC", "off")
        import routers.live_picks as live

        admin = {"id": 1, "plan": "admin"}
        assert live.require_live_reader(admin) is admin

    def test_o_plano_continua_sendo_o_gate(self):
        """"Aberto pra todos" e' todo ASSINANTE · quem nao e' VIP nunca chega
        em require_live_reader, porque require_vip barra antes."""
        src = _ler(_BACKEND, "routers", "live_picks.py")
        assert "Depends(require_vip)" in src

    def test_o_front_abre_sem_depender_de_variavel(self):
        """`LIVE_PICKS_ENABLED` virou CONSTANTE em 28/08.

        A aba tem que APARECER sem ninguem configurar nada · o inverso deixaria
        o produto invisivel por esquecimento de variavel, com o pior sintoma
        possivel: nenhum. Esconder de novo passou a ser editar uma linha, que
        aparece no diff, em vez de mexer numa variavel que some sem rastro.
        """
        src = _ler(_FRONT, "config.ts")
        assert "export const LIVE_PICKS_ENABLED = true" in src
        assert "import.meta.env.VITE_LIVE_PICKS_ENABLED" not in src

    def test_a_aba_continua_sendo_premium(self):
        src = _ler(_FRONT, "pages", "Picks.tsx")
        trecho = src[src.index("key: 'ao_vivo'"):]
        assert "premiumOnly: true" in trecho[:400]

    def test_admin_ve_mesmo_com_o_produto_desligado(self):
        """Quem opera precisa ver a MESMA tela que o assinante ve, e nao so' o
        painel de diagnostico do /admin."""
        src = _ler(_FRONT, "pages", "Picks.tsx")
        assert "LIVE_PICKS_ENABLED || isAdmin" in src


# ── a notificacao ────────────────────────────────────────────────────────
class TestNotificacaoDePickNovo:
    def test_e_um_tipo_proprio(self):
        """`pick_live` e' "o pick que VOCE seguiu comecou" -- pessoal, so'
        existe pra quem apostou. Um tipo so' faria o sino dizer "comecou" pra um
        pick que ninguem pegou ainda."""
        import routers.notifications as notif

        assert notif.TYPE_LIVE_NOVO == "live_novo"
        assert notif.TYPE_LIVE_NOVO != notif.TYPE_PICK_LIVE

    def test_o_dedupe_e_por_pick(self, monkeypatch):
        """E' ele que permite chamar isto de dentro de um poll sem encher o
        sino: o primeiro visitante cria o item pra base, os proximos caem no
        ON CONFLICT DO NOTHING."""
        import routers.notifications as notif

        chamadas = []
        monkeypatch.setattr(notif, "notify_all_users",
                            lambda *a, **kw: chamadas.append(kw) or 1)

        notif.notificar_pick_live_novo([
            {"id": 7, "home_team_name": "Flamengo", "away_team_name": "Palmeiras",
             "market": "Escanteios", "line": "Over 9.5", "odd": 1.85,
             "minute_at_creation": 62},
        ])

        assert len(chamadas) == 1
        assert chamadas[0]["dedupe_key"] == "live_novo:7"

    def test_o_aviso_leva_o_jogo_e_a_linha(self, monkeypatch):
        """"Pick ao vivo" sozinho nao diz se vale a pena abrir · a janela e' de
        minutos e o usuario decide pela bandeja do sistema."""
        import routers.notifications as notif

        chamadas = []
        monkeypatch.setattr(notif, "notify_all_users",
                            lambda *a, **kw: chamadas.append(kw) or 1)

        notif.notificar_pick_live_novo([
            {"id": 7, "home_team_name": "Flamengo", "away_team_name": "Palmeiras",
             "market": "Escanteios", "line": "Over 9.5", "odd": 1.85,
             "minute_at_creation": 62},
        ])

        assert "Flamengo x Palmeiras" in chamadas[0]["title"]
        corpo = chamadas[0]["body"]
        assert "Escanteios" in corpo and "Over 9.5" in corpo and "62" in corpo
        assert chamadas[0]["url"].endswith("#ao_vivo")

    def test_pick_sem_id_nao_estoura(self, monkeypatch):
        import routers.notifications as notif

        monkeypatch.setattr(notif, "notify_all_users", lambda *a, **kw: 1)
        assert notif.notificar_pick_live_novo([{"home_team_name": "A"}]) == 0
        assert notif.notificar_pick_live_novo([]) == 0

    def test_o_feed_so_notifica_o_que_esta_de_pe(self):
        """Pick liquidado ou com a odd vencida nao e' oportunidade · notificar
        sobre ele manda o assinante atras de um preco que nao existe mais."""
        src = _ler(_BACKEND, "routers", "live_picks.py")
        assert "notificar_pick_live_novo" in src
        assert 'not p.get("result")' in src
        assert 'p.get("status") == STATUS_ATIVO' in src

    def test_falha_ao_notificar_nao_derruba_o_feed(self):
        """O pick esta' na tela de quem ja' esta' olhando · isso vale mais que
        o aviso."""
        src = _ler(_BACKEND, "routers", "live_picks.py")
        trecho = src[src.index("notificar_pick_live_novo"):]
        assert "except Exception" in trecho[:900]


# ── o card ───────────────────────────────────────────────────────────────
class TestOCardSegueOPadrao:
    def test_usa_a_peca_comum_de_probabilidade(self):
        """Era um ladrilho proprio, com outra cor e outro corte · a mesma
        porcentagem aparecia diferente dependendo da aba."""
        src = _ler(_FRONT, "components", "LivePicksFeed.tsx")
        assert "PickProbability" in src

    def test_mostra_quanto_apostar_e_quanto_paga(self):
        """Faltava no card ao vivo e existia em todos os outros · sem os dois
        numeros o assinante tem o pick e nao tem a aposta."""
        src = _ler(_FRONT, "components", "LivePicksFeed.tsx")
        assert "Lucro pot." in src
        # Em unidades E em reais · sem a banca o card mostra so' as unidades,
        # que e' a metade que nao decide nada.
        assert "banca.unit_value" in src

    def test_a_unidade_sugerida_olha_a_BANCA_do_usuario(self):
        """Igual VIP, multipla e free · pedido do usuario em 27/08.

        `picks_live.stake_units` e' a sugestao do MOTOR, e ela nao conhece a
        banca de ninguem: e' a mesma pra quem tem R$ 200 e pra quem tem
        R$ 20.000. Os cards pre-jogo resolvem isso com Kelly em cima do bankroll
        real, e nao havia razao pro Live ser o unico produto a mostrar uma
        unidade que nao fala da banca de quem esta' lendo.

        `calcVipStake` e' a MESMA funcao do card VIP · o que muda e' so' o teto.
        """
        src = _ler(_FRONT, "components", "LivePicksFeed.tsx")
        assert "calcVipStake" in src
        assert "bankroll_current" in src
        # Sem banca configurada cai na sugestao do motor, que continua vindo do
        # feed · e' melhor que nada, e e' o mesmo numero que o /admin mostra.
        assert "pick.stake_units" in src
        api = _ler(_BACKEND, "routers", "live_picks.py")
        assert "stake_units" in api

    def test_o_teto_do_live_e_o_mesmo_dos_dois_lados(self):
        """Sem o teto no cliente, o Kelly pediria 7u num pick de 82% e o modal
        deixaria escolher · o erro so' apareceria no POST, DEPOIS de o usuario
        confirmar. Mesmo defeito que MAX_UNITS_POR_TIPO ja' corrigiu nos cards
        pre-jogo."""
        import re

        import routers.banca as banca

        src = _ler(_FRONT, "components", "LivePicksFeed.tsx")
        achado = re.search(r"MAX_UNIDADES_LIVE\s*=\s*(\d+)", src)
        assert achado, "o card nao declara teto de unidades"
        assert int(achado.group(1)) == banca.STAKE_LIMITS["live"][1]

    def test_o_modal_abre_com_o_MESMO_numero_do_card(self):
        """Enquanto o modal calculava por conta propria (`stake_units ?? 1`), o
        card dizia "3u" e o modal abria em "1u" · duas respostas pra mesma
        pergunta, na mesma batida de dedo."""
        src = _ler(_FRONT, "components", "LivePicksFeed.tsx")
        assert "function unidadesSugeridas" in src
        assert "suggestedUnits={unidadesSugeridas(alvo, banca)}" in src

    def test_a_odd_da_conta_e_a_que_o_usuario_registrou(self):
        """Ao vivo a linha se move mais que em pre-jogo · usar a do pick pra
        calcular o lucro de quem ja' apostou daria um numero que ele nao ve."""
        src = _ler(_FRONT, "components", "LivePicksFeed.tsx")
        assert "user_actual_odd ?? pick.odd" in src
