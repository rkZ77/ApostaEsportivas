"""Cobertura do que mudou no backend nesta leva, antes de ir pra producao.

Nenhum destes testes toca banco: o que se verifica aqui e a LOGICA que da pra
verificar sem ele -- tabela de precos, tipos aceitos, forma da resposta e
montagem de SQL. O que depende de banco esta listado no fim do arquivo como
verificacao manual, pra nao dar falsa sensacao de cobertura.
"""

import ast
import io
import os
import re

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fonte(caminho: str) -> str:
    return io.open(os.path.join(BASE, caminho), encoding="utf-8").read()


# ─────────────────────────── Precos ────────────────────────────────────


def _payments_ns():
    """Executa so o bloco de precos de payments.py, sem importar o router."""
    src = _fonte("routers/payments.py")
    bloco = src[src.index("PLANS = {"):src.index('@router.get("/plans")')]
    ns: dict = {}
    exec(bloco, ns)
    return ns


def test_precos_batem_com_o_cobrado():
    """O valor anunciado tem que ser o valor que o MercadoPago cobra.

    Este teste existe porque o JSON-LD anunciou R$ 49,90 por tempo
    indeterminado enquanto a cobranca era R$ 39,90.
    """
    plans = _payments_ns()["PLANS"]
    assert plans["mensal"]["price"] == 39.90
    assert plans["trimestral"]["price"] == 99.90
    assert plans["semestral"]["price"] == 199.90
    assert plans["anual"]["price"] == 359.90


def test_desconto_calculado_bate_com_a_conta():
    """O save_pct nao pode ser digitado: era assim que o Checkout dizia 17%
    num plano que economiza 16%."""
    ns = _payments_ns()
    mensal = ns["PLANS"]["mensal"]["price"]

    for chave in ns["PLANS"]:
        p = ns["_plan_payload"](chave)
        cheio = mensal * p["months"]
        esperado = 0 if chave == "mensal" else round((1 - p["price"] / cheio) * 100)
        assert p["save_pct"] == esperado, f"{chave}: {p['save_pct']}% != {esperado}%"
        # preco por mes tem que fechar com o total
        assert round(p["price_per_month"] * p["months"], 0) == pytest.approx(round(p["price"], 0), abs=1)


def test_semestral_economiza_16_e_nao_17():
    """Regressao do numero que estava errado no Checkout."""
    assert _payments_ns()["_plan_payload"]("semestral")["save_pct"] == 16


def test_todo_plano_tem_periodo_iso_valido():
    """billingIncrement do schema.org so aceita duracao ISO-8601."""
    ns = _payments_ns()
    for chave in ns["PLANS"]:
        assert re.fullmatch(r"P\d+[MY]", ns["_plan_payload"](chave)["iso_period"])


def test_endpoint_de_planos_e_publico():
    """A home mostra preco pra visitante deslogado: exigir login aqui
    quebraria justamente o caminho que ficava desatualizado."""
    arvore = ast.parse(_fonte("routers/payments.py"))
    fn = next(n for n in ast.walk(arvore)
              if isinstance(n, ast.FunctionDef) and n.name == "list_plans")
    assert not fn.args.args, "list_plans nao pode receber dependencia de auth"


# ──────────────────── Mercados como pipeline completo ──────────────────


def _banca_ns():
    src = _fonte("routers/banca.py")
    bloco = src[src.index("STAKE_LIMITS = {"):src.index('@router.post("/follow")')]
    ns: dict = {}
    exec(bloco, ns)
    return ns


def test_follow_aceita_os_seis_pipelines():
    """faltas e goleiros ficaram de fora do follow por a lista de tipos estar
    escrita duas vezes. Agora STAKE_LIMITS e a fonte unica."""
    limites = _banca_ns()["STAKE_LIMITS"]
    for tipo in ("vip", "free", "multipla", "alavancagem", "faltas", "goleiros"):
        assert tipo in limites, f"{tipo} nao pode registrar aposta"


def test_follow_valida_contra_stake_limits_e_nao_contra_lista_solta():
    """Se voltar a existir uma lista literal no if, o proximo pipeline novo
    vai ficar de fora de novo."""
    src = _fonte("routers/banca.py")
    trecho = src[src.index('@router.post("/follow")'):][:900]
    assert "body.pick_type not in STAKE_LIMITS" in trecho
    assert '("vip", "free", "multipla", "alavancagem")' not in trecho


def test_todo_tipo_tem_rotulo_de_erro():
    ns = _banca_ns()
    for tipo in ns["STAKE_LIMITS"]:
        assert tipo in ns["STAKE_LABELS"], f"{tipo} sem rotulo na mensagem de erro"


def test_mercados_tem_teto_de_stake_conservador():
    """Amostra historica menor que VIP: o teto acompanha o do Free."""
    limites = _banca_ns()["STAKE_LIMITS"]
    assert limites["faltas"] == limites["free"]
    assert limites["goleiros"] == limites["free"]


def test_detalhe_le_da_tabela_certa_pros_mercados():
    """Sem este ramo o pick caia no else e consultava picks_vip, devolvendo o
    pick VIP de mesmo id."""
    src = _fonte("routers/suggestions.py")
    # `player_stats` entrou em 27/08 como sucessor de goleiros -- o ramo passou
    # de um `if/else` de duas tabelas pra um mapa, porque com tres opcoes o
    # ternario deixa de ser legivel e passa a esconder o caso do meio.
    assert 'if pick_type in ("faltas", "goleiros", "player_stats"):' in src
    for tabela in ("picks_faltas", "picks_goleiros", "picks_player_stats"):
        assert f'"{tabela}"' in src


def test_link_publico_aceita_mercados():
    """Link compartilhado de pick de faltas abria erro 400."""
    src = _fonte("routers/public.py")
    trecho = src[src.index("def public_pick"):][:500]
    assert '"faltas", "goleiros"' in trecho
    assert '"player_stats"' in trecho


def test_resultados_publicos_somam_os_seis_pipelines():
    ns_src = _fonte("routers/public.py")
    bloco = ns_src[ns_src.index("_SUB_BUILDERS = {"):]
    bloco = bloco[:bloco.index("}")]
    for tipo in ("vip", "free", "multiplas", "alavancagem", "faltas", "goleiros"):
        assert f'"{tipo}"' in bloco


# ─────────────────── Dica do Dia com mercado bloqueado ─────────────────


def test_mercado_nao_sai_do_servidor_pra_anonimo():
    """O corte tem que ser no servidor.

    Se o market viesse no JSON e fosse so desfocado no CSS, bastava abrir o
    DevTools pra ler, e a recompensa por criar conta virava teatro.
    """
    src = _fonte("routers/public.py")
    corpo = src[src.index("def public_free_pick_today"):]
    corpo = corpo[:corpo.index("@router.get", 10)] if "@router.get" in corpo[10:] else corpo

    assert "get_current_user_optional(request)" in corpo
    assert 'd.pop("market", None)' in corpo
    assert 'd.pop("line", None)' in corpo
    # e o pop tem que estar no ramo do anonimo, nao no do logado
    ramo_anon = corpo[corpo.index("else:"):]
    assert 'd["locked"] = True' in ramo_anon


def test_auth_opcional_devolve_none_em_vez_de_estourar():
    """Endpoint publico nao pode quebrar por token expirado ou malformado."""
    src = _fonte("auth_utils.py")
    fn = src[src.index("def get_current_user_optional"):]
    assert "except Exception:" in fn
    assert "return None" in fn


# ──────────────────────── Migracao das tabelas novas ───────────────────


def test_migracao_e_aditiva_e_idempotente():
    """As tres tabelas novas rodam contra o banco de PRODUCAO no primeiro boot.

    Aditivo e idempotente sao inegociaveis aqui: nada de ALTER destrutivo,
    nada de DROP, e rodar duas vezes tem que ser inofensivo.
    """
    src = _fonte("migrations.py")
    trecho = src[src.index("user_favorites"):src.index("conn.commit()", src.index("user_achievements"))]

    for tabela in ("user_favorites", "user_alerts", "user_achievements"):
        assert f"CREATE TABLE IF NOT EXISTS {tabela}" in src

    # Comando destrutivo de verdade, nao a palavra solta: "ON DELETE CASCADE"
    # e' justamente o oposto disso (limpeza correta ao excluir a conta).
    alto = trecho.upper()
    for destrutivo in ("DROP TABLE", "DROP COLUMN", "DELETE FROM", "TRUNCATE", "ALTER COLUMN"):
        assert destrutivo not in alto, f"migracao nao pode conter {destrutivo} em prod"
    # indices tambem precisam do IF NOT EXISTS pra reboot nao falhar
    for idx in re.findall(r"CREATE (?:UNIQUE )?INDEX[^;]*", trecho):
        assert "IF NOT EXISTS" in idx


def test_tabelas_novas_apagam_junto_com_o_usuario():
    """LGPD: exclusao de conta nao pode deixar orfao."""
    src = _fonte("migrations.py")
    for tabela in ("user_favorites", "user_alerts", "user_achievements"):
        bloco = src[src.index(f"CREATE TABLE IF NOT EXISTS {tabela}"):]
        bloco = bloco[:bloco.index('""")')]
        assert "REFERENCES users(id) ON DELETE CASCADE" in bloco


def test_endpoints_pessoais_exigem_login():
    """Favorito, alerta e conquista sao dados de conta: nenhum pode ser
    publico, e nenhum pode aceitar user_id por parametro."""
    src = _fonte("routers/personal.py")
    arvore = ast.parse(src)
    rotas = [n for n in ast.walk(arvore) if isinstance(n, ast.FunctionDef)
             and any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") in
                     ("get", "post", "put", "delete") for d in n.decorator_list)]
    assert rotas, "nenhuma rota encontrada"
    for fn in rotas:
        nomes = [a.arg for a in fn.args.args]
        assert "current_user" in nomes, f"{fn.name} sem autenticacao"
        assert "user_id" not in nomes, f"{fn.name} aceita user_id por parametro"


def test_queries_pessoais_filtram_por_usuario_do_token():
    """Toda leitura e escrita tem que amarrar em current_user['id'].

    A versao anterior citava duas consultas pelo texto exato ("DELETE FROM
    user_favorites"). Quando os favoritos foram removidos em 07/08 o teste
    quebrou sem que nada tivesse piorado -- e, pior, ele nunca teria pego uma
    consulta NOVA sem filtro, porque so' olhava as duas que conhecia.

    Agora varre todas: qualquer FROM/INTO numa tabela `user_*` precisa ter
    user_id amarrado no mesmo comando.
    """
    src = _fonte("routers/personal.py")
    comandos = re.findall(r"(?:FROM|INTO|UPDATE)\s+(user_\w+)[^;\"']*", src)
    assert comandos, "nenhuma consulta pessoal encontrada"
    for trecho in re.findall(r"(?:FROM|INTO|UPDATE)\s+user_\w+.{0,400}", src, re.DOTALL):
        assert "user_id" in trecho, f"consulta pessoal sem user_id: {trecho[:80]}"


# ─────────────────────── Fica de fora, verificar na mao ────────────────
#
# O que estes testes NAO cobrem, porque exige banco de verdade:
#
#   1. A migracao rodando contra o schema real de producao.
#   2. O SQL do detalhe de faltas/goleiros retornando as colunas esperadas
#      (os nomes divergem entre picks_vip e picks_free; conferi na mao, mas
#      so o banco confirma).
#   3. /public/market-movement com dado real de closing_odds.
#   4. Registrar aposta de mercado ponta a ponta.


def test_pipeline_dev_coleta_dados_e_odds_no_banco_dev():
    """Homologacao/no-prod precisa alimentar DEV antes de gerar picks DEV.

    O bug era sutil: os passos de geracao tinham prefixo `dev_`, mas coleta de
    jogos/odds nao. Como _run_and_track so aplica DB_ENV=dev para comandos com
    esse prefixo, o pipeline alimentava PROD e depois tentava gerar picks em
    DEV sem fixtures/odds recentes.
    """
    src = _fonte("routers/admin.py")
    ns: dict = {"os": os}
    tree = ast.parse(src)
    wanted = {"_PIPELINE_SCRIPTS", "_DEV_PIPELINE_STEPS"}
    nodes = [n for n in tree.body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id in wanted for t in n.targets)]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "admin_subset", "exec"), ns)

    assert ns["_DEV_PIPELINE_STEPS"][:2] == ["dev_atualizar_jogos", "dev_capturar_odds"]
    assert all(step.startswith("dev_") for step in ns["_DEV_PIPELINE_STEPS"])
    assert ns["_PIPELINE_SCRIPTS"]["dev_atualizar_jogos"] == "atualizar_jogos.py"
    assert ns["_PIPELINE_SCRIPTS"]["dev_capturar_odds"] == "capturar_odds.py"
