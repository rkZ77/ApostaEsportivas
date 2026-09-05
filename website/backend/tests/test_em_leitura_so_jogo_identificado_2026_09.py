"""O bloco "A IA está lendo" mostrava cartão sem jogo dentro.

`live_match_observations` guarda o que o motor LEU -- fixture_id, minuto e os
contadores --, e o nome dos times vem da tabela `fixtures`. Nem toda partida
observada esta la': o motor le' o que a API devolve como ao vivo, e a coleta
pode nao ter trazido aquele jogo. Com LEFT JOIN essas linhas viravam cartao
"liga ? / Time ? x Time ?", com placar e contadores mas sem dizer de que jogo se
tratava -- em 05/09 metade da tela era isso.

E o mesmo bloco anunciava partida ENCERRADA: a observacao e' um retrato, ninguem
reescreve a linha quando o juiz apita, entao ela sobrevivia na janela de 60
minutos como se o motor ainda estivesse acompanhando.
"""
from tests.test_home_2026_08 import _codigo


def _consulta() -> str:
    return _codigo("routers/live_picks.py", "em_leitura")


def test_partida_sem_nome_nao_vira_cartao():
    corpo = _consulta()
    assert "JOIN fixtures f ON f.fixture_id = u.fixture_id" in corpo
    assert "LEFT JOIN fixtures" not in corpo, "voltou o LEFT JOIN dos cartoes vazios"
    assert "f.home_team IS NOT NULL" in corpo


def test_jogo_encerrado_sai_do_que_esta_sendo_lido():
    corpo = _consulta()
    # 1. status atual da fixture, que o coletor mantem
    assert "COALESCE(f.status, '') <> ALL(%s)" in corpo
    # 2. rede de seguranca pra fixture ainda nao atualizada
    assert "COALESCE(u.minuto, 0) >= 90" in corpo


def test_a_lista_continua_saindo_da_observacao_e_nao_da_api():
    """O numero exibido e' o que o motor leu · uma segunda consulta a API
    poderia divergir dele, e ainda custaria requisicao."""
    corpo = _consulta()
    assert "live_match_observations" in corpo
    assert "httpx" not in corpo and "_fetch" not in corpo
