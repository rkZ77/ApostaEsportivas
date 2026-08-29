"""Ferramentas do agente que leem o BANCO DO SITE, e nao a API-Football.

O agente nasceu sabendo tudo de futebol e nada do Pick IA. As 17 ferramentas
anteriores falam com a API-Football -- jogo, odd, tabela, escalacao -- entao ele
respondia "como o Palmeiras vem jogando?" e travava em "que picks sairam hoje?",
que e' a pergunta que a pessoa foi fazer.

O que existia era um TEXTO pre-cozido injetado no prompt (chat.py::
_get_site_context) com banca e desempenho do mes. Serve pra uma pergunta so', a
que alguem previu. Ferramenta serve pra pergunta que ninguem previu: "e em
julho?", "quantos reds seguidos ja' tivemos?", "quais picks eu segui e deram
green?".

TRES REGRAS QUE VALEM PRA TODAS AS FUNCOES DESTE ARQUIVO

1. SO' LEITURA. Nenhuma escreve. O agente responde perguntas, nao opera a conta
   -- e uma ferramenta de escrita exposta a texto livre e' superficie de ataque
   por injecao de prompt, nao conveniencia.

2. O ESCOPO E' O USUARIO DA SESSAO, sempre por parametro de consulta. O
   `user_id` vem do token no chat.py e NUNCA do texto da conversa: quem pede
   "veja os picks do usuario 42" tem que continuar vendo os proprios.

3. CONTEUDO DE PICK RESPEITA O PAYWALL. Mercado e linha so' saem pra quem tem
   plano ativo. Hoje o agente ja' e' exclusivo de VIP/trial/admin (ver
   routers/chat.py), entao a checagem e' redundante -- e fica de proposito: se
   um dia o agente abrir pro free, o vazamento nao pode depender de alguem
   lembrar deste arquivo.
"""
import logging
from datetime import date

from database import get_connection

logger = logging.getLogger(__name__)

#: Planos que enxergam mercado e linha de pick pago.
_PLANOS_PAGOS = ("vip", "admin", "trial")

#: Teto de linhas por consulta. O resultado vira texto no prompt do modelo, e
#: uma temporada inteira de picks estouraria a janela sem responder melhor.
_LIMITE = 50


def _pago(plano: str | None) -> bool:
    return (plano or "free").lower() in _PLANOS_PAGOS


def _consulta(sql: str, params: tuple = ()) -> list[dict]:
    """Uma consulta curta, conexao devolvida sempre.

    `try/finally` e nao `with`: o pool de database.py devolve um proxy cujo
    .close() DEVOLVE a conexao, e vazar um slot aqui tira capacidade do site
    inteiro (o pool tem 10).
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


# ──────────────────────────────────────────────────────────────────────────
# CATALOGO DE PRODUTOS
# ──────────────────────────────────────────────────────────────────────────
#
# O agente lia picks_vip e picks_free e mais nada. Entao "que picks sairam
# hoje?" respondia por dois dos nove produtos, e a pessoa concluia que os
# outros sete nao existiam -- num assistente que e' exclusivo de assinante,
# essa e' a resposta mais cara que ele podia dar.
#
# `select` normaliza cada tabela pras MESMAS colunas (tipo/casa/fora/market/
# line/odd/result/match_date), que e' o que permite juntar tudo num UNION so'
# e responder a pergunta que a pessoa fez ("o que saiu hoje") em vez da que a
# tabela sabia responder.
#
# `opcional` marca a tabela que vem do MOTOR e nao das migracoes do site
# (picks_live): onde ela nao existe, a fonte sai do UNION em vez de derrubar a
# resposta inteira.
_PRODUTOS: tuple = (
    ("vip",          "picks_vip",
     "home_team_name AS casa, away_team_name AS fora, market, line, odd", False),
    ("free",         "picks_free",
     "home_team AS casa, away_team AS fora, market, line, odd", False),
    ("faltas",       "picks_faltas",
     "home_team AS casa, away_team AS fora, market, line, odd", False),
    ("goleiros",     "picks_goleiros",
     "home_team AS casa, away_team AS fora, market, line, odd", False),
    ("player_stats", "picks_player_stats",
     "home_team AS casa, away_team AS fora, market, line, odd", False),
    ("boost",        "picks_boost",
     "home_team AS casa, away_team AS fora, market, line, odd", False),
    ("multipla",     "picks_multiplas",
     "CONCAT('Multipla · ', JSONB_ARRAY_LENGTH(games::jsonb), ' selecoes') AS casa,"
     " NULL AS fora, 'Multipla' AS market, NULL AS line, total_odd AS odd", False),
    ("alavancagem",  "picks_alavancagem",
     "home_team_1 AS casa, away_team_1 AS fora, market_1 AS market,"
     " line_1 AS line, odd_combined AS odd", False),
    ("live",         "picks_live",
     "home_team_name AS casa, away_team_name AS fora, market, line, odd", True),
)


def _jogo(p: dict) -> str:
    """"Casa x Fora", ou so' a descricao quando nao ha' dois times.

    A multipla nao tem partida propria (as pernas ficam num JSON) e entra no
    UNION com `fora` nulo · sem isto o agente escrevia "Multipla · 3 selecoes
    x None" no meio da resposta.
    """
    casa, fora = p.get("casa"), p.get("fora")
    return f"{casa} x {fora}" if fora else str(casa or "—")


def _tabela_existe(tabela: str) -> bool:
    try:
        linhas = _consulta("SELECT to_regclass(%s) IS NOT NULL AS existe",
                           (f"public.{tabela}",))
        return bool(linhas and linhas[0]["existe"])
    except Exception:
        return False


def _produtos(tipo: str | None = None) -> list:
    """Os produtos consultaveis. `tipo` restringe a um deles."""
    ativos = [p for p in _PRODUTOS if not p[3] or _tabela_existe(p[1])]
    if tipo:
        alvo = tipo.strip().lower()
        alvo = {"multiplas": "multipla", "dica": "free",
                "defesas": "goleiros", "jogador": "player_stats",
                "ao vivo": "live"}.get(alvo, alvo)
        escolhido = [p for p in ativos if p[0] == alvo]
        if escolhido:
            return escolhido
    return ativos


# ──────────────────────────────────────────────────────────────────────────
# PICKS PUBLICADOS
# ──────────────────────────────────────────────────────────────────────────
def picks_publicados(dia: str | None, plano: str | None) -> str:
    """Picks de um dia, com resultado quando ja' resolvido.

    `dia` no formato YYYY-MM-DD. Omitido, e' hoje.

    Junta TODOS os produtos numa consulta so' com UNION ALL porque a pergunta
    da pessoa e' "o que saiu hoje", nao "o que saiu hoje em cada tabela".
    """
    alvo = (dia or date.today().isoformat())[:10]
    produtos = _produtos(None)
    uniao = ("\n            UNION ALL\n").join(
        f"            SELECT '{tipo}' AS tipo, {select}, result, match_date"
        f"              FROM {tabela} WHERE match_date = %s"
        for tipo, tabela, select, _opc in produtos
    )
    try:
        linhas = _consulta(f"""
{uniao}
             ORDER BY tipo, casa
             LIMIT %s
        """, tuple([alvo] * len(produtos)) + (_LIMITE,))
    except Exception as e:
        logger.warning("[AGENTE] picks_publicados falhou: %s", e)
        return "Nao consegui ler os picks agora."

    if not linhas:
        return f"Nenhum pick publicado em {alvo}."

    saida = [f"Picks de {alvo} ({len(linhas)}):"]
    for p in linhas:
        jogo = _jogo(p)
        # O paywall vive aqui e nao na formatacao: quem chama nao pode
        # esquecer de mascarar.
        if _pago(plano):
            linha = f" {p['line']}" if p.get("line") is not None else ""
            mercado = f"{p['market']}{linha} @ {p['odd']}"
        else:
            mercado = "mercado exclusivo de assinante"
        resultado = p["result"] or "aguardando"
        saida.append(f"  [{p['tipo'].upper()}] {jogo} · {mercado} · {resultado}")
    return "\n".join(saida)


# ──────────────────────────────────────────────────────────────────────────
# DESEMPENHO DA IA
# ──────────────────────────────────────────────────────────────────────────
def desempenho_da_ia(mes: str | None, tipo: str | None) -> str:
    """Acerto, lucro em unidades e ROI dos picks ja' resolvidos.

    `mes` no formato YYYY-MM restringe o periodo; `tipo` restringe a vip ou
    free. Sem nenhum dos dois, e' o historico inteiro.

    Conta so' o que TEM resultado. Pick pendente entrando no denominador
    afundaria o acerto sozinho, e a pergunta "quanto a IA acerta" e' sobre o
    que ja' fechou.
    """
    filtros, params = ["result IS NOT NULL"], []
    if mes:
        filtros.append("TO_CHAR(match_date, 'YYYY-MM') = %s")
        params.append(mes[:7])
    onde = " AND ".join(filtros)

    # Antes so' respondia por VIP e Free · o agente anunciava "o desempenho da
    # IA" descrevendo dois dos nove motores que o site publica.
    escolhidas = [(p[0], p[1]) for p in _produtos(tipo)]

    saida = [f"Desempenho{' de ' + mes[:7] if mes else ' (historico completo)'}:"]
    for rotulo, tabela in escolhidas:
        try:
            linha = _consulta(f"""
                SELECT COUNT(*)                                  AS total,
                       COUNT(*) FILTER (WHERE result = 'GREEN')  AS greens,
                       COUNT(*) FILTER (WHERE result = 'RED')    AS reds,
                       COALESCE(SUM(profit), 0)::float           AS lucro
                  FROM {tabela} WHERE {onde}
            """, tuple(params))
        except Exception as e:
            logger.warning("[AGENTE] desempenho %s falhou: %s", rotulo, e)
            continue
        d = linha[0] if linha else {}
        total = d.get("total") or 0
        if not total:
            saida.append(f"  {rotulo.upper()}: nenhum pick resolvido nesse recorte.")
            continue
        greens = d.get("greens") or 0
        acerto = round(greens / total * 100, 1)
        lucro = round(float(d.get("lucro") or 0), 2)
        saida.append(
            f"  {rotulo.upper()}: {total} resolvidos · {greens} green / "
            f"{d.get('reds') or 0} red · acerto {acerto}% · lucro {lucro:+.2f}u"
        )
    return "\n".join(saida)


# ──────────────────────────────────────────────────────────────────────────
# O QUE ESTE USUARIO SEGUIU
# ──────────────────────────────────────────────────────────────────────────
def meus_picks(user_id: int, apenas_pendentes: bool, plano: str | None) -> str:
    """Picks que ESTA conta seguiu, com resultado.

    `user_id` vem do token da sessao e nunca do texto da conversa · e' o que
    impede "me mostre os picks do usuario 42" de funcionar.
    """
    if not user_id:
        return "Sem sessao identificada, nao da' pra listar os picks seguidos."

    # Lia so' picks_vip: quem seguiu Free, multipla, alavancagem, mercado
    # proprio, Player Stats, Pick Boost ou ao vivo ouvia "voce ainda nao seguiu
    # nenhum pick" com a banca cheia. Um UNION por produto seguido resolve, com
    # o mesmo catalogo que o resto do arquivo usa.
    filtro_pendente = "AND t.result IS NULL" if apenas_pendentes else ""
    produtos = _produtos(None)
    uniao = ("\n            UNION ALL\n").join(
        f"            SELECT '{tipo}' AS tipo, id, {select}, result, match_date"
        f"              FROM {tabela}"
        for tipo, tabela, select, _opc in produtos
    )
    try:
        linhas = _consulta(f"""
            SELECT t.tipo, t.casa, t.fora, t.market, t.line, t.odd,
                   t.result, t.match_date
              FROM user_followed_picks uf
              JOIN (
{uniao}
              ) t ON t.id = uf.pick_id AND t.tipo = uf.pick_type
             WHERE uf.user_id = %s {filtro_pendente}
             ORDER BY t.match_date DESC
             LIMIT %s
        """, (user_id, _LIMITE))
    except Exception as e:
        logger.warning("[AGENTE] meus_picks falhou: %s", e)
        return "Nao consegui ler os seus picks agora."

    if not linhas:
        return ("Voce ainda nao seguiu nenhum pick."
                if not apenas_pendentes else "Voce nao tem pick pendente.")

    saida = [f"Picks que voce seguiu ({len(linhas)}):"]
    for p in linhas:
        data = str(p["match_date"])[:10]
        jogo = _jogo(p)
        mercado = (f"{p['market']}{' ' + str(p['line']) if p.get('line') is not None else ''} @ {p['odd']}"
                   if _pago(plano) else "mercado exclusivo de assinante")
        saida.append(f"  {data} · {jogo} · {mercado} · "
                     f"{p['result'] or 'aguardando'}")
    return "\n".join(saida)


# ──────────────────────────────────────────────────────────────────────────
# COBERTURA
# ──────────────────────────────────────────────────────────────────────────
def ligas_cobertas() -> str:
    """Ligas que a IA analisa hoje.

    Separa as encerradas de proposito: elas continuam no banco sustentando o
    historico (a Copa do Mundo 2026 sozinha responde por boa parte do ledger de
    calibracao), mas prometer analise delas seria mentira.
    """
    try:
        linhas = _consulta(
            "SELECT name, season, COALESCE(ativa, TRUE) AS ativa "
            "FROM leagues ORDER BY ativa DESC, name")
    except Exception as e:
        logger.warning("[AGENTE] ligas_cobertas falhou: %s", e)
        return "Nao consegui ler as ligas agora."

    ativas = [f"{l['name']} ({l['season']})" for l in linhas if l["ativa"]]
    historico = [l["name"] for l in linhas if not l["ativa"]]
    saida = ["Ligas analisadas agora: " + (", ".join(ativas) or "nenhuma")]
    if historico:
        saida.append("So' historico (nao geram pick): " + ", ".join(historico))
    return "\n".join(saida)
