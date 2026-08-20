"""Curva da banca por dia e quebra por pipeline · 2026-08-19.

Duas entregas independentes, pedidas pelo usuário no mesmo dia:

1. EVOLUÇÃO DA BANCA POR DIA. O gráfico plotava um ponto por PICK resolvido,
   todos carimbados com a mesma data -- quem seguiu cinco picks em 19/08 via
   cinco pontos "19/08" empilhados no eixo. Agora é um ponto por dia, e só de
   dia já encerrado e sem aposta pendente.

2. QUEBRA POR PIPELINE. Meus Picks só sabia dizer o total. "Estou no lucro" e
   "estou no lucro apesar de um pipeline" são diagnósticos diferentes.

Nada aqui abre conexão: as duas funções são puras, recebem a lista de entradas
já montada e devolvem o agregado.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from routers.banca import BR_TZ, _curva_diaria, _dia_br, _quebra_por_pipeline


def _iso_utc_de_br(dia, hora=15):
    """ISO ingênuo em UTC de uma hora de Brasília · é o formato da coluna."""
    br = datetime(dia.year, dia.month, dia.day, hora, tzinfo=BR_TZ)
    return br.astimezone(ZoneInfo("UTC")).replace(tzinfo=None).isoformat()


def _entrada(dia, pnl, tipo="vip", stake=1.0, hora=15):
    return {
        "pick_type":    tipo,
        "stake_units":  stake,
        "followed_at":  _iso_utc_de_br(dia, hora),
        "result":       None if pnl is None else ("GREEN" if pnl > 0 else "RED"),
        "pnl":          pnl,
    }


HOJE = datetime.now(BR_TZ).date()
ONTEM = HOJE - timedelta(days=1)
ANTEONTEM = HOJE - timedelta(days=2)


# ─────────────────────── 1. Curva por dia ───────────────────────


def test_cinco_apostas_no_mesmo_dia_viram_um_ponto():
    """O defeito relatado: cinco pontos "19/08" no eixo de um dia só.

    O gráfico era `for e in entries: chart.append(...)`, então o eixo tinha um
    ponto por aposta e a linha subia e descia dentro do mesmo dia -- que não é
    o que "evolução da banca" comunica.
    """
    entries = [_entrada(ANTEONTEM, 10.0, hora=h) for h in (10, 12, 14, 16, 18)]

    curva = _curva_diaria(entries, 100.0)

    assert len(curva) == 1, f"esperava 1 ponto no dia, veio {len(curva)}"
    assert curva[0]["date"] == ANTEONTEM.isoformat()
    # O ponto do dia é o saldo ao FIM dele: os cinco P&L somados.
    assert curva[0]["bankroll"] == 150.0


def test_dia_de_hoje_nao_entra_na_curva():
    """Ponto do dia corrente é ponto que ainda vai mudar.

    A curva de banca é o registro do que já não muda mais -- plotar hoje faz o
    último ponto pular a cada aposta liquidada, que é meia versão do defeito
    original."""
    entries = [_entrada(ONTEM, 20.0), _entrada(HOJE, 50.0)]

    curva = _curva_diaria(entries, 100.0)

    assert [p["date"] for p in curva] == [ONTEM.isoformat()]


def test_dia_com_aposta_pendente_interrompe_a_curva():
    """Não é pular o dia incompleto: é PARAR nele.

    O saldo é acumulado. Plotar D+1 por cima de um D que ainda tem aposta de pé
    desenharia uma banca que nunca existiu -- e era exatamente o que o
    `if pnl is not None` fazia, em silêncio.
    """
    entries = [
        _entrada(ANTEONTEM, 30.0),
        _entrada(ONTEM, None),       # pendente
        _entrada(ONTEM, 10.0),
    ]

    curva = _curva_diaria(entries, 100.0)

    assert [p["date"] for p in curva] == [ANTEONTEM.isoformat()]
    assert curva[0]["bankroll"] == 130.0


def test_dia_e_o_de_brasilia_nao_o_utc():
    """Aposta das 22h de Brasília é do dia dela, não do dia seguinte.

    `followed_at` é timestamp ingênuo em UTC; o gráfico cortava os 10 primeiros
    caracteres do ISO, e entre 21:00 e 00:00 essa fatia já é o dia seguinte.
    """
    assert _dia_br(_iso_utc_de_br(ANTEONTEM, hora=22)) == ANTEONTEM
    assert _dia_br(_iso_utc_de_br(ANTEONTEM, hora=1)) == ANTEONTEM
    assert _dia_br(None) is None
    assert _dia_br("nao e data") is None


def test_curva_vazia_quando_so_ha_hoje():
    """Conta nova que apostou hoje ainda não tem curva · e não deve inventar
    uma. O front exige 2 pontos pra desenhar, então isto vira "sem gráfico"."""
    assert _curva_diaria([_entrada(HOJE, 10.0)], 100.0) == []


# ─────────────────────── 2. Quebra por pipeline ───────────────────────


def test_quebra_separa_por_pipeline_e_agrupa_os_mercados():
    """Faltas e defesas entram juntos como "Mercados".

    Os dois nasceram juntos, são o mesmo formato (um jogo, um mercado) e têm
    volume baixo: duas linhas separadas responderiam menos que uma.
    """
    entries = [
        _entrada(ONTEM, 30.0, "vip", stake=4),
        _entrada(ONTEM, -10.0, "vip", stake=4),
        _entrada(ONTEM, 15.0, "free", stake=3),
        _entrada(ONTEM, 8.0, "faltas", stake=3),
        _entrada(ONTEM, -3.0, "goleiros", stake=3),
        _entrada(ONTEM, 5.0, "multipla", stake=1),
    ]

    quebra = {q["key"]: q for q in _quebra_por_pipeline(entries, unit_value=10.0)}

    assert set(quebra) == {"vip", "free", "mercados", "multipla"}
    assert quebra["vip"]["total"] == 2
    assert quebra["vip"]["greens"] == 1 and quebra["vip"]["reds"] == 1
    assert quebra["vip"]["pnl"] == 20.0
    # Mercados = faltas + goleiros somados numa linha só.
    assert quebra["mercados"]["total"] == 2
    assert quebra["mercados"]["pnl"] == 5.0


def test_quebra_ignora_pendente_e_ordena_por_lucro():
    """Aposta de pé não tem resultado pra contar · entrar como zero puxaria o
    win rate do pipeline pra baixo sem nada ter acontecido."""
    entries = [
        _entrada(ONTEM, 5.0, "free", stake=3),
        _entrada(ONTEM, 40.0, "vip", stake=4),
        _entrada(ONTEM, None, "vip", stake=4),
    ]

    quebra = _quebra_por_pipeline(entries, unit_value=10.0)

    assert [q["key"] for q in quebra] == ["vip", "free"], "não veio ordenado por lucro"
    assert quebra[0]["total"] == 1, "pendente entrou na contagem"


def test_yield_usa_unidades_apostadas_nao_a_banca():
    """É o que compara pipelines de volume diferente entre si.

    ROI sobre banca faria o pipeline mais frequente parecer sempre o melhor,
    que é o oposto do que a tela precisa responder.
    """
    # 1 aposta de 4u, lucro de R$20 com unidade de R$10 = +2u sobre 4u = 50%.
    entries = [_entrada(ONTEM, 20.0, "vip", stake=4)]

    (vip,) = _quebra_por_pipeline(entries, unit_value=10.0)

    assert vip["units"] == 2.0
    assert vip["staked_units"] == 4.0
    assert vip["yield"] == 50.0


def test_alavancagem_nunca_aparece_na_quebra():
    """Ela nem chega em `entries` (a consulta filtra pick_type != 'alavancagem'),
    mas o teste trava a intenção: caminho em andamento não é dinheiro e não
    pode ser somado degrau a degrau junto dos outros. A tela dela é
    /banca/alavancagem."""
    from routers.banca import PIPELINES_DA_QUEBRA

    tipos = {t for _, _, grupo in PIPELINES_DA_QUEBRA for t in grupo}
    assert "alavancagem" not in tipos

    entries = [_entrada(ONTEM, 99.0, "alavancagem", stake=1)]
    assert _quebra_por_pipeline(entries, unit_value=10.0) == []
