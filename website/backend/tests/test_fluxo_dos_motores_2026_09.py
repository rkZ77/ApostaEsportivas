"""O desenho dos motores na tela sai do motor, não de texto no frontend.

A aba Motor respondia só o que ACONTECEU (quais execuções rodaram, o que o
motor olhou num dia). Faltava a pergunta anterior: como o motor chega num pick,
e com que dado.

O risco óbvio dessa tela era virar a quarta cópia da mesma coisa neste projeto
-- depois do registro de motores, do registro de comandos e da sequência do
"Rodar Tudo", que já divergiram cada uma pelo menos uma vez. Então os números
saem do config real e os métodos do registro; o que é escrito à mão é só a
ORDEM e o PAPEL das camadas, que não existem como dado em lugar nenhum.
"""
import os

# SEM setar PIPELINE_SRC_PATH no import: fazer isso aqui montava o motor no
# caminho durante a COLETA do pytest e contaminava a suite inteira (o teste do
# pool chegou a receber uma conexao real de producao). O ambiente ja traz a
# variavel onde ela importa; sem ela, os testes que precisam do motor pulam.
import pytest

import motor_fluxo

pytestmark = pytest.mark.skipif(
    motor_fluxo._registro() is None,
    reason="motor fora do caminho neste ambiente (PIPELINE_SRC_PATH)")


def _fluxo():
    return motor_fluxo.fluxo_dos_motores()


def _motor(slug):
    return next(m for m in _fluxo()["motores"] if m["slug"] == slug)


def _limiar(motor_slug, camada, chave):
    camadas = {c["nome"]: c for c in _motor(motor_slug)["camadas"]}
    return camadas[camada]["limiares"][chave]


class TestOsQuatroMotores:
    def test_todos_aparecem(self):
        slugs = [m["slug"] for m in _fluxo()["motores"]]
        assert slugs == ["PRE_LIVE", "LIVE", "PICK_BOOST", "PLAYER_STATS"]

    def test_cada_um_diz_o_que_entra_e_por_onde_passa(self):
        for m in _fluxo()["motores"]:
            assert m["entradas"], f"{m['slug']} sem fonte de dado"
            assert m["camadas"], f"{m['slug']} sem fluxo"
            for e in m["entradas"]:
                assert e["fonte"] and e["o_que"] and e["origem"]
            for c in m["camadas"]:
                assert c["nome"] and c["faz"]


class TestNadaDeCopia:
    def test_os_metodos_saem_do_registro_do_motor(self):
        """Método novo no motor tem que aparecer nesta tela sozinho."""
        engine_registry = motor_fluxo._registro()
        do_registro = {m.slug: {met.slug for met in m.metodos}
                       for m in engine_registry.MOTORES}
        for m in _fluxo()["motores"]:
            if m["slug"] in do_registro:
                assert {x["slug"] for x in m["metodos"]} == do_registro[m["slug"]]

    def test_os_limiares_saem_do_config_real(self):
        from services.pick_engine.config import DEFAULT_CONFIG
        assert _limiar("PRE_LIVE", "Preço", "odd mínima") == DEFAULT_CONFIG.min_odd
        assert _limiar("PRE_LIVE", "Preço", "edge mínimo") == DEFAULT_CONFIG.min_edge
        assert _limiar("PRE_LIVE", "Taxa histórica", "taxa mínima") == DEFAULT_CONFIG.min_taxa
        assert _limiar("PRE_LIVE", "Confiança", "confiança mínima") == DEFAULT_CONFIG.min_confidence

    def test_os_limiares_do_ao_vivo_tambem(self):
        from services.pick_engine_live.config import DEFAULT_LIVE_CONFIG
        assert _limiar("LIVE", "Avaliação e gates", "EV mínimo") == DEFAULT_LIVE_CONFIG.ev_minimo
        assert (_limiar("LIVE", "Orçamento de API", "teto de requisições")
                == DEFAULT_LIVE_CONFIG.max_requisicoes)
        assert (_limiar("LIVE", "Seleção de partidas", "minuto final")
                == DEFAULT_LIVE_CONFIG.minuto_final)

    def test_baixar_um_limiar_no_config_muda_a_tela(self, monkeypatch):
        """É a prova de que o número não está escrito aqui."""
        from services.pick_engine import config as cfg
        original = cfg.DEFAULT_CONFIG
        monkeypatch.setattr(cfg, "DEFAULT_CONFIG",
                            original.__class__(**{**original.__dict__, "min_odd": 1.11}))
        assert _limiar("PRE_LIVE", "Preço", "odd mínima") == 1.11


class TestFalhaAberto:
    def test_motor_fora_do_path_nao_derruba_a_tela(self, monkeypatch):
        """Sem o motor, a tela mostra o desenho sem método e sem número --
        e diz isso, em vez de exibir um limiar velho."""
        monkeypatch.setattr(motor_fluxo, "engine_registry", None)
        monkeypatch.setattr(motor_fluxo, "_registro", lambda: None)
        monkeypatch.setattr(motor_fluxo, "_config_pre_live", lambda: None)
        monkeypatch.setattr(motor_fluxo, "_config_live", lambda: None)

        fluxo = motor_fluxo.fluxo_dos_motores()

        assert fluxo["derivado"] is False
        assert fluxo["limiares_disponiveis"] is False
        assert len(fluxo["motores"]) == 4
        pre = next(m for m in fluxo["motores"] if m["slug"] == "PRE_LIVE")
        assert pre["metodos"] == []
        preco = next(c for c in pre["camadas"] if c["nome"] == "Preço")
        assert all(v is None for v in preco["limiares"].values()), (
            "limiar sem motor tem que vir nulo, nunca um padrão inventado")


def test_o_endpoint_existe_e_e_de_admin():
    import inspect
    from routers.admin import motor_fluxo as rota
    assert "current_user" in inspect.signature(rota).parameters
