"""Reexporta modulos do motor pro backend do site.

`services/settlement.py` vive em ApostaEsportivas/src/ e e' a fonte unica da
matematica de GREEN/RED/PUSH/HALF-*. O backend precisa da MESMA implementacao
(nao de uma copia): foi ter duas que produziu, entre outras divergencias, um
PUSH de perna virando RED de um lado e PUSH do bilhete inteiro do outro.

O Dockerfile copia ApostaEsportivas/src/ pra /app/pipeline e exporta
PIPELINE_SRC_PATH; em desenvolvimento o caminho relativo resolve sozinho.
Mesma busca de diretorio ja usada por routers/admin.py::_find_pipeline_dir.

`utils/stat_sheet.py` viaja junto pelo mesmo motivo: e' quem decide o que
`value: null` significa na folha da API-Football. O backend tinha a sua
propria leitura, e ela discordava do motor exatamente no vermelho -- ver o
cabecalho daquele modulo.

O import e' obrigatorio de proposito -- sem ele nao existe fallback "meia
boca" que liquide pick de um jeito diferente; a API sobe com erro claro no
lugar de gradear errado em silencio.
"""

import os
import sys


def _pipeline_dir() -> str:
    if env := os.getenv("PIPELINE_SRC_PATH"):
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.path.abspath(os.path.join(here, "../../ApostaEsportivas/src")),
        os.path.abspath(os.path.join(os.getcwd(), "ApostaEsportivas/src")),
        os.path.abspath(os.path.join(here, "pipeline")),
    ):
        if os.path.isdir(candidate):
            return candidate
    return ""


_DIR = _pipeline_dir()
if _DIR and _DIR not in sys.path:
    # APPEND, NUNCA insert(0) -- corrigido em 2026-09-04.
    #
    # Este import monta o caminho do motor e NAO desmonta: e' um efeito de
    # import de modulo, permanente no processo. Na frente do sys.path ele
    # SOMBREIA os modulos de topo do proprio backend que tem nome igual, e ha'
    # tres: `main`, `run_dev` e `__pycache__`. A partir daqui, qualquer
    # `import main` no processo devolvia
    # ApostaEsportivas/src/main.py -- o CLI do motor -- em vez do app FastAPI.
    #
    # Em producao passava batido porque o `main` do site ja' esta' em
    # sys.modules antes de qualquer router ser importado. Na suite nao: 22
    # testes de tres arquivos quebravam com "module 'main' has no attribute
    # 'app'", e eles passavam quando rodados sozinhos -- o sintoma classico de
    # ordem, que faz procurar o defeito no arquivo errado.
    #
    # No fim do path resolve os dois lados: o backend continua achando o
    # proprio `main`, e `services`/`utils`/`collectors`/`engine_pipelines` so'
    # existem do lado do motor, entao para eles a posicao e' indiferente.
    sys.path.append(_DIR)

from services import settlement          # noqa: E402
from utils import stat_sheet             # noqa: E402

# A folha POR JOGADOR (/fixtures/players) tem regra propria de leitura, e ela
# ja' existe no coletor do motor: `null` num contador de quem ENTROU EM CAMPO
# quer dizer zero, porque a API omite o zero em vez de escreve-lo (medido em
# 2026-09-02: 169 zeros explicitos contra 8.115 nulls no mesmo `shots_on`).
#
# Viaja por aqui pelo mesmo motivo dos dois acima: o site passou a buscar essa
# folha por conta propria pra liquidar pick de jogador, e uma segunda leitura
# do mesmo JSON discordaria do coletor no caso mais comum da folha inteira --
# que e' exatamente o erro que inflava a media de chutes em 3,4x.
#
# So' as funcoes puras sao usadas; o coletor nao abre banco no import.
from collectors import player_stats_collector_service as player_sheet  # noqa: E402

# Catalogo de motores e metodos (2026-08-27). Viaja pelo mesmo caminho e pelo
# mesmo motivo dos dois acima: a aba Auditoria dos Motores precisa dizer QUAL
# motor, QUAL metodo e QUAL versao gerou cada decisao, e essa lista tem que ser
# a MESMA que o motor usa pra gravar. Uma copia no backend divergiria no
# primeiro metodo novo -- que e' exatamente o que aconteceu com
# `_PIPELINES_DO_MOTOR`, mantida a mao neste backend e que ja' nasceu
# precisando de um ramo "pipeline que a lista nao conhece".
#
# Import isolado do resto: se o motor nao estiver no caminho (ambiente antigo,
# imagem sem /app/pipeline), o painel cai pra rotulos crus em vez de a API
# inteira recusar subir. Liquidacao errada e' inaceitavel; rotulo cru nao e'.
try:
    from services.engine_audit import registry as engine_registry  # noqa: E402
except Exception:                                                  # pragma: no cover
    engine_registry = None

__all__ = ["settlement", "stat_sheet", "player_sheet", "engine_registry"]
