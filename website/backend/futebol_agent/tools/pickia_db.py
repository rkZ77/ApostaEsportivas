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
# PICKS PUBLICADOS
# ──────────────────────────────────────────────────────────────────────────
def picks_publicados(dia: str | None, plano: str | None) -> str:
    """Picks de um dia, com resultado quando ja' resolvido.

    `dia` no formato YYYY-MM-DD. Omitido, e' hoje.

    Junta VIP e Free numa consulta so' com UNION ALL porque a pergunta da
    pessoa e' "o que saiu hoje", nao "o que saiu hoje em cada tabela".
    """
    alvo = (dia or date.today().isoformat())[:10]
    try:
        linhas = _consulta("""
            SELECT 'vip' AS tipo, home_team_name AS casa, away_team_name AS fora,
                   market, line, odd, result, match_date
              FROM picks_vip  WHERE match_date = %s
            UNION ALL
            SELECT 'free', home_team, away_team,
                   market, line, odd, result, match_date
              FROM picks_free WHERE match_date = %s
             ORDER BY tipo, casa
             LIMIT %s
        """, (alvo, alvo, _LIMITE))
    except Exception as e:
        logger.warning("[AGENTE] picks_publicados falhou: %s", e)
        return "Nao consegui ler os picks agora."

    if not linhas:
        return f"Nenhum pick publicado em {alvo}."

    saida = [f"Picks de {alvo} ({len(linhas)}):"]
    for p in linhas:
        jogo = f"{p['casa']} x {p['fora']}"
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

    tabelas = {"vip": "picks_vip", "free": "picks_free"}
    escolhidas = ({tipo.lower(): tabelas[tipo.lower()]}
                  if tipo and tipo.lower() in tabelas else tabelas)

    saida = [f"Desempenho{' de ' + mes[:7] if mes else ' (historico completo)'}:"]
    for rotulo, tabela in escolhidas.items():
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

    filtro_pendente = "AND pv.result IS NULL" if apenas_pendentes else ""
    try:
        linhas = _consulta(f"""
            SELECT pv.home_team_name AS casa, pv.away_team_name AS fora,
                   pv.market, pv.line, pv.odd, pv.result, pv.match_date
              FROM user_followed_picks uf
              JOIN picks_vip pv ON pv.id = uf.pick_id AND uf.pick_type = 'vip'
             WHERE uf.user_id = %s {filtro_pendente}
             ORDER BY pv.match_date DESC
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
        mercado = (f"{p['market']}{' ' + str(p['line']) if p.get('line') is not None else ''} @ {p['odd']}"
                   if _pago(plano) else "mercado exclusivo de assinante")
        saida.append(f"  {data} · {p['casa']} x {p['fora']} · {mercado} · "
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
