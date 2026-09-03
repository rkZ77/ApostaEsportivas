"""Todo resultado passa a dizer com qual número foi decidido (2026-09-02).

"Esse resultado está errado" era uma frase impossível de responder. O card
mostrava PUSH e mais nada, e três coisas muito diferentes chegavam na tela com
a mesma cara:

  · empate técnico em linha cheia (12 escanteios numa linha de 12.0) · a casa
    devolve, e está certo;
  · anulação porque o provedor não publicou a estatística;
  · anulação porque o jogo foi pra prorrogação e a folha soma os 120 minutos.

A diferença entre elas morava num log do Railway. Agora `settled_value` guarda
o contador que decidiu e `void_reason` o motivo, quando existe, e os dois vão
pra tela: a conferência deixa de depender de nós.

O que este arquivo trava:

  1. As colunas nascem em TODA tabela de pick, e a migration não pode derrubar
     o site quando uma delas não existe (picks_live nasce no motor).
  2. A gravação nunca perde o resultado por causa da auditoria: se as colunas
     faltarem, grava só o resultado, como antes.
  3. A leitura NÃO entra na consulta que lista os picks · é a mesma regressão
     de 02/09 que sumiu com os picks de jogador.
"""
import os
import re

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONT = os.path.join(os.path.dirname(_BACKEND), "frontend", "src")


def _ler(*partes) -> str:
    with open(os.path.join(*partes), encoding="utf-8") as f:
        return f.read()


def test_as_colunas_nascem_em_toda_tabela_de_pick():
    fonte = _ler(_BACKEND, "migrations.py")
    bloco = fonte[fonte.index("POR QUE DEU ISSO, E COM QUAL NÚMERO"):]
    bloco = bloco[:bloco.index("Índice composto")]
    for tabela in ("picks_vip", "picks_free", "picks_faltas", "picks_goleiros",
                   "picks_boost", "picks_multiplas", "picks_alavancagem",
                   "picks_live", "picks_player_stats"):
        assert tabela in bloco, f"{tabela} ficou sem as colunas de auditoria"
    assert "ADD COLUMN IF NOT EXISTS settled_value" in bloco
    assert "ADD COLUMN IF NOT EXISTS void_reason" in bloco
    # picks_live nasce no MOTOR: a migration não pode explodir onde ela falta.
    assert "to_regclass" in bloco and "except Exception" in bloco


def test_gravar_o_resultado_nunca_depende_da_auditoria():
    """A auditoria é um plus. Se a coluna não existir nesta instância, o pick
    ainda tem que ser liquidado · o contrário troca "resultado sem número" por
    "pick pendente pra sempre"."""
    fonte = _ler(_BACKEND, "routers", "live.py")
    for func in ("_save_single_result", "_save_market_pick_result",
                 "_save_live_pick_result"):
        i = fonte.index(f"def {func}(")
        corpo = fonte[i:fonte.index("\n\n\n", i)]
        assert "except Exception" in corpo, f"{func} não tem o caminho de reserva"
        assert corpo.count("UPDATE") >= 2, f"{func} não regrava sem as colunas"


def test_o_motivo_da_anulacao_chega_a_quem_grava():
    """Os cinco call sites usam `res = res or _anulacao_sem_estatistica(leg)`,
    então o motivo viaja por uma variável de módulo lida na mesma passada."""
    fonte = _ler(_BACKEND, "routers", "live.py")
    assert "_ultimo_motivo_anulacao" in fonte
    # E ele é limpo no começo de cada avaliação: sem isso, o motivo de um pick
    # anulado grudaria no próximo que passasse pela função.
    corpo = fonte[fonte.index("def _anulacao_sem_estatistica("):]
    corpo = corpo[:corpo.index("\n\n\n")]
    assert "_ultimo_motivo_anulacao = None" in corpo


def test_a_lista_de_picks_nao_depende_das_colunas_novas():
    """A regressão de 02/09, de novo: `_safe_query` devolve lista vazia quando
    qualquer coisa falha, então campo opcional não entra na consulta que traz
    os picks."""
    fonte = _ler(_BACKEND, "routers", "suggestions.py")
    bloco = fonte[fonte.index("_LIVE_COLUNAS = "):]
    bloco = bloco[:bloco.index('"""')]
    for proibido in ("settled_value", "void_reason"):
        assert proibido not in bloco, (
            f"'{proibido}' entrou na consulta do ao vivo: se a coluna faltar, "
            "o produto inteiro some da tela")
    assert "_juntar_auditoria" in fonte


def test_a_tela_mostra_o_numero_com_a_unidade_do_mercado():
    """"12 escanteios", e não "12 unidades" · a unidade sai do próprio catálogo
    de mercados, então não existe segunda lista pra manter em dia."""
    fonte = _ler(_FRONT, "utils", "marketTranslate.ts")
    assert "export function valorLiquidado" in fonte
    corpo = fonte[fonte.index("export function valorLiquidado"):]
    corpo = corpo[:corpo.index("\n}")]
    assert "unidadeDoMercado" in corpo and "sujeitoDoMercado" in corpo

    card = _ler(_FRONT, "components", "SuggestionCard.tsx")
    assert 'rotulo="Deu"' in card
    # Só com o pick liquidado: antes disso o número ainda está mudando.
    assert "s.result && s.settled_value != null" in card
