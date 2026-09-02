"""O "Entenda esta análise" abre pronto (2026-09-02).

O modal buscava a forma do mercado numa requisição e a amostra do motor em
outra, cada uma com o próprio esqueleto: ele abria e ia se montando em duas
etapas, tremendo justamente na hora de ler número.

`/suggestions/{id}/analise` devolve as duas juntas, e o front busca isso quando
o dedo encosta no botão (services/analisePick), então na maior parte das vezes
o modal abre com tudo carregado.

O que este arquivo trava:

  1. A rota NÃO recalcula nada · ela chama os dois handlers que já existem.
     Reimplementar aqui criaria uma segunda fonte pra mesma pergunta, que é
     exatamente como as duas telas de amostra divergiram em produção.
  2. `limit` vai EXPLÍCITO. Chamada direta em Python não passa pelo FastAPI, e
     o default do parâmetro é um objeto `Query(10)`, não o número 10 · ele iria
     inteiro pro `LIMIT %s` do SQL.
  3. Uma metade que falha não derruba a outra.
  4. O front pede UMA vez por pick e guarda a promessa, não o resultado: o caso
     comum é o prefetch ainda estar no ar quando o modal abre.

Leitura de código-fonte, nada toca banco.
"""
import os
import re

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONT = os.path.join(os.path.dirname(_BACKEND), "frontend", "src")


def _ler(*partes) -> str:
    with open(os.path.join(*partes), encoding="utf-8") as f:
        return f.read()


def _rota_analise() -> str:
    fonte = _ler(_BACKEND, "routers", "suggestions.py")
    i = fonte.index('@router.get("/{suggestion_id}/analise")')
    return fonte[i:]


def test_a_rota_junta_os_dois_handlers_que_ja_existem():
    bloco = _rota_analise()
    assert "get_market_form(" in bloco
    assert "get_amostra(" in bloco
    # Nada de SQL novo: se aparecer um SELECT aqui, virou segunda fonte.
    assert "SELECT" not in bloco.upper()


def test_o_limit_vai_explicito():
    """Sem isto, o default `Query(10)` chega inteiro no LIMIT do SQL."""
    bloco = _rota_analise()
    assert re.search(r"get_market_form\([^)]*limit=10", bloco, re.S)


def test_uma_metade_que_falha_nao_derruba_a_outra():
    """Pick anterior a 27/08 não tem amostra gravada, e quem tem forma de
    mercado precisa continuar vendo a metade que existe."""
    bloco = _rota_analise()
    assert "_tentar(" in bloco
    assert 'return {"available": False}' in bloco
    # HTTPException (paywall, 404) tem que subir inteira pro chamador.
    assert "except HTTPException:" in bloco and "raise" in bloco


def test_o_front_guarda_a_promessa_e_nao_o_resultado():
    """O caso comum é o prefetch AINDA ESTAR NO AR quando o modal abre: com
    cache de resultado, cada abertura rápida viraria duas chamadas iguais."""
    fonte = _ler(_FRONT, "services", "analisePick.ts")
    assert "Map<string, Promise<AnalisePick>>" in fonte
    # Falha não pode ficar no cache, senão a próxima tentativa nasce condenada.
    assert "cache.delete(k)" in fonte


def test_o_botao_adianta_a_busca_no_toque():
    """`pointerdown` no celular acontece de 100 a 300ms antes do clique · é
    esse tempo que faz o modal abrir pronto."""
    partes = _ler(_FRONT, "components", "PickCardParts.tsx")
    assert "onPointerDown={onIntencao}" in partes
    assert "onPointerEnter={onIntencao}" in partes

    for tela, quantos in (("components/SuggestionCard.tsx", 1), ("pages/Picks.tsx", 3)):
        fonte = _ler(_FRONT, *tela.split("/"))
        assert fonte.count("onIntencao={() => prefetchAnalise(") >= quantos, (
            f"{tela} tem botão de análise sem adiantar a busca")


def test_um_esqueleto_so_para_as_duas_secoes():
    """Dois esqueletos terminando em momentos diferentes é o pulo que a
    mudança inteira existe pra tirar."""
    modal = _ler(_FRONT, "components", "AnalysisModal.tsx")
    assert modal.count("<Skeleton") == 1, "voltou a ter mais de um bloco de espera"
    # E os dois blocos recebem os dados prontos, em vez de buscarem sozinhos.
    assert "dados={analise?.market_form ?? null}" in modal
    assert "dados={analise?.amostra ?? null}" in modal
