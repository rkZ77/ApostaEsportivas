"""A odd do pick ao vivo passa a ser lida de novo enquanto o pick esta' aberto.

O card mostrava a odd do instante da publicacao e, passados alguns minutos,
trocava aquilo por "odd vencida" -- um pick que o mercado ainda estava cotando
aparecia morto porque o RELOGIO venceu, nao porque a casa fechou.

O QUE ESTES TESTES GUARDAM E' O CUSTO. `_fetch_live_odds` pergunta por UMA
fixture: com 5 picks abertos e leitura por minuto seriam 300 requisicoes por
hora, e o plano inteiro tem 7.500 por dia. `/odds/live` sem `fixture` devolve o
mundo, entao UMA leitura cobre todos os picks de todos os usuarios -- e o cache
de 60s no servidor e' o que segura isso com a aba de varias pessoas pedindo a
cada 15 segundos.

Trocar a leitura global por uma por partida, ou afrouxar o cache, refaz a conta
que estourou a cota em 01/08 e custou o agendador do projeto.
"""
from tests.test_home_2026_08 import _codigo, _fonte, _front_codigo


def test_a_leitura_e_global_e_nao_por_partida():
    corpo = _codigo("routers/live.py", "_fetch_live_odds_mundo")
    # sem `fixture` na querystring: e' o que faz uma chamada valer por todas
    assert '{"page": pagina}' in corpo, "a leitura deixou de paginar o mundo"
    assert 'params={"fixture"' not in corpo, "voltou a perguntar partida por partida"
    assert "api_quota.registrar" in corpo, "leitura que nao registra cota nao aparece no painel"


def test_o_cache_do_mundo_e_de_tres_minutos():
    """1 minuto era mais do que a pergunta pede: odd ao vivo se move em
    minutos, e o que a leitura responde e' "o mercado ainda esta' de pe'".
    Tres minutos levam a conta de ~240 requisicoes num dia de 4 horas pra ~80."""
    fonte = _fonte("routers/live.py")
    assert "_TTL_ODDS_MUNDO = 180" in fonte
    corpo = _codigo("routers/live.py", "_fetch_live_odds_mundo")
    assert "agora - ts < _TTL_ODDS_MUNDO" in corpo


def test_falha_de_leitura_devolve_o_cache_e_nao_vazio():
    """Vazio seria lido como "o mercado suspendeu tudo" · e' a diferenca entre
    marcar o pick como sem cotacao e admitir que a leitura falhou."""
    corpo = _codigo("routers/live.py", "_fetch_live_odds_mundo")
    assert "return cache" in corpo


def test_a_rota_nao_reescreve_a_odd_do_pick():
    """`odd` e' o preco que a IA analisou e contra o que o resultado e' medido.
    A leitura corrente vai pra TELA e adia a expiracao -- nao vira historico."""
    corpo = _codigo("routers/live_picks.py", "odds_agora")
    assert "SET odd_valid_until" in corpo
    assert "SET odd =" not in corpo


def test_sem_cotacao_agora_nao_e_erro():
    corpo = _codigo("routers/live_picks.py", "odds_agora")
    assert '"cotado": False' in corpo


def test_so_pergunta_odd_de_jogo_que_nao_acabou():
    """Entre o apito final e a liquidacao o pick fica pendente com a partida
    encerrada, e perguntar a odd dele e' trabalho sobre um mercado que nao
    existe mais. O status sai de `fixtures` -- custo zero de API."""
    corpo = _codigo("routers/live_picks.py", "odds_agora")
    assert "LEFT JOIN fixtures f" in corpo
    assert "COALESCE(f.status, '') <> ALL(%s)" in corpo


def test_a_tela_para_de_pedir_quando_ninguem_esta_olhando():
    """`isActive` so' dizia que a aba do produto estava escolhida. Com o site
    aberto numa aba que ninguem ve', a tela seguia pedindo feed, leitura e odd
    -- e cada um desses caminhos consulta a API-Football do outro lado."""
    tela = _front_codigo("components/LivePicksFeed.tsx")
    assert "useJanelaVisivel" in tela
    assert "visibilitychange" in tela
    assert "if (!isActive || !visivel)" in tela


def test_o_pick_expirado_volta_quando_a_casa_ainda_cota():
    """O caso que mais precisa da leitura: pick que NINGUEM pegou e que o
    relogio marcou como "odd vencida". Se a casa continua cotando, ele nao
    venceu -- so' o nosso cronometro achou que sim. Ficar fora da consulta
    congelava o card na frase errada pra sempre."""
    corpo = _codigo("routers/live_picks.py", "odds_agora")
    assert "pl.status = ANY(%s)" in corpo
    assert "STATUS_EXPIRADO" in corpo
    # e a volta: status de novo ativo, motivo da expiracao apagado
    assert "expiration_reason = NULL" in corpo
    assert "SET odd_valid_until" in corpo
