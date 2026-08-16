from utils.db_utils import get_connection
from decimal import Decimal

from services import settlement


_ALLOWED_CHECKER_TABLES = frozenset({"picks_vip", "picks_free", "picks_alavancagem"})


class AIResultCheckerService:

    def __init__(self, table_name="picks_vip"):
        if table_name not in _ALLOWED_CHECKER_TABLES:
            raise ValueError(f"Tabela não permitida: {table_name!r}. Use: {_ALLOWED_CHECKER_TABLES}")
        self.table = table_name

    ##########################################################################
    # BUSCA ESTATÍSTICAS
    ##########################################################################
    def get_fixture_result(self, fixture_id, cur):

        # SELECT * + mapa por NOME em vez de lista fixa lida por indice: a
        # lista posicional obrigava a recontar 25 posicoes a cada coluna nova
        # (uma inserida no meio desloca todas as seguintes em silencio, e o
        # erro so' aparece como estatistica trocada), e quebrava com
        # ProgrammingError quando uma coluna nova ainda nao existia no banco
        # -- o que acontece sempre entre o merge e a migracao em PROD.
        cur.execute("SELECT * FROM match_statistics WHERE fixture_id = %s LIMIT 1;",
                    (fixture_id,))

        row = cur.fetchone()

        if not row:
            return None

        col = {d[0]: i for i, d in enumerate(cur.description)}

        def g(nome):
            i = col.get(nome)
            return row[i] if i is not None else None

        # NULL aqui significa "o provedor ainda nao publicou esse numero" e
        # segue como None ate' o fim: `or 0` transformava ausencia em zero e
        # era isso que gradeava um Over como RED com o jogo inteiro por
        # contar (ver services/settlement.py, invariante 1). Gols sao a
        # excecao legitima: vem do proprio /fixtures (placar), nao da folha
        # de estatistica, e a linha so' existe pra jogo ja encerrado.
        hy, hr = g("home_yellow_cards"), g("home_red_cards")
        ay, ar = g("away_yellow_cards"), g("away_red_cards")
        hg_ht  = g("home_goals_ht")
        ag_ht  = g("away_goals_ht")
        h_off, a_off = g("home_offsides"), g("away_offsides")
        h_corn, a_corn = g("home_corners"), g("away_corners")

        def _sum(*parts):
            """Soma que respeita ausencia: se qualquer parcela e' desconhecida,
            o total tambem e'."""
            return None if any(p is None for p in parts) else sum(parts)

        return {
            "home_goals":    g("home_goals") or 0,
            "away_goals":    g("away_goals") or 0,
            "total_goals":   g("total_goals") or 0,
            # Placar dos 90 minutos (score.fulltime da API). So' difere do
            # placar acima em jogo decidido na prorrogacao -- e' o numero pelo
            # qual a casa liquida. None em jogo antigo, coletado antes desta
            # coluna existir: nesse caso o mercado nao e' liquidado.
            "home_goals_90": g("home_goals_90"),
            "away_goals_90": g("away_goals_90"),
            "total_goals_90": _sum(g("home_goals_90"), g("away_goals_90")),
            "home_corners":  h_corn,
            "away_corners":  a_corn,
            "total_corners": (g("total_corners") if g("total_corners") is not None
                              else _sum(h_corn, a_corn)),
            "home_yellow":   hy,
            "away_yellow":   ay,
            "home_red":      hr,
            "away_red":      ar,
            # cartao vermelho vale 2 pontos (mesma convencao usada pra
            # calcular a taxa historica em stats_model._cards_points --
            # gradear com uma regra e prever com outra deixaria a
            # confidence do pick sem relacao com o que de fato decide o
            # resultado real. "home_yellow"/"away_yellow"/"total_yellow"
            # acima continuam contagem pura, pros mercados so' de amarelo).
            "home_cards":    None if None in (hy, hr) else hy + 2 * hr,
            "away_cards":    None if None in (ay, ar) else ay + 2 * ar,
            "status":        g("status"),
            "total_cards":   (None if None in (hy, hr, ay, ar)
                              else hy + 2 * hr + ay + 2 * ar),
            # PISO de cartoes: o total contando ZERO vermelho.
            #
            # A folha da API omite "Red Cards" quando ninguem foi expulso, e o
            # coletor grava NULL -- certo, porque ausencia nunca vira zero.
            # So' que isso deixava 21,3% das partidas encerradas (40 de 66 em
            # agosto/2026) com todo mercado de cartao impossivel de liquidar,
            # inclusive uma alavancagem presa desde 13/08.
            #
            # O piso nao afirma que houve zero vermelho: afirma que o total e'
            # PELO MENOS os amarelos, o que e' verdade sempre. Quem decide se
            # isso basta e' settlement.settle_over_under_com_piso -- e ele so'
            # liquida quando o numero que falta nao pode mais mudar a resposta.
            "home_cards_min":  None if hy is None else hy,
            "away_cards_min":  None if ay is None else ay,
            "total_cards_min": _sum(hy, ay),
            "total_yellow":  _sum(hy, ay),
            "total_red":     _sum(hr, ar),
            "home_goals_ht": hg_ht,
            "away_goals_ht": ag_ht,
            "total_goals_ht": _sum(hg_ht, ag_ht),
            "home_offsides": h_off,
            "away_offsides": a_off,
            "total_offsides": _sum(h_off, a_off),
            # Faltas/chutes/defesas ja' estavam em match_statistics e nao eram
            # lidos aqui: o pick de faltas (picks_faltas) e qualquer perna
            # desses mercados no picks_ledger ficavam com result NULL pra
            # sempre, porque so' o caminho ao vivo sabia resolve-los.
            "home_fouls":     g("home_fouls"),
            "away_fouls":     g("away_fouls"),
            "total_fouls":    _sum(g("home_fouls"), g("away_fouls")),
            "home_shots_on":  g("home_shots_on"),
            "away_shots_on":  g("away_shots_on"),
            "total_shots_on": _sum(g("home_shots_on"), g("away_shots_on")),
            "home_shots":     g("home_total_shots"),
            "away_shots":     g("away_total_shots"),
            "total_shots":    _sum(g("home_total_shots"), g("away_total_shots")),
            "home_saves":     g("home_goalkeeper_saves"),
            "away_saves":     g("away_goalkeeper_saves"),
            "total_saves":    _sum(g("home_goalkeeper_saves"), g("away_goalkeeper_saves")),
        }

    ##########################################################################
    # PARSE DE LINHA
    ##########################################################################
    def parse_line(self, line):
        """(op, valor). Delega em services/settlement.py::parse_line -- a
        leitura da linha e' a mesma pro job em lote e pro caminho ao vivo."""
        parsed = settlement.parse_line(line)
        return parsed["op"], parsed["value"]

    ##########################################################################
    # DETECTA SE É MERCADO DE 1° TEMPO
    ##########################################################################
    @staticmethod
    def _is_first_half(market_name: str) -> bool:
        n = market_name.lower()
        return any(k in n for k in [
            "1° tempo", "1º tempo", "primeiro tempo",
            "1st half", "first half", "halftime", "half time",
            "ht -", "- ht", "(ht)", "[ht]",
        ])

    ##########################################################################
    # DETECTA MERCADO
    # Retorna tipo base (sem sufixo _ht); use _is_first_half() separado.
    ##########################################################################
    # market_type gravado no banco -> familia base deste checker. So' e' usado
    # quando o TEXTO do mercado nao decide nada: existe pick em producao com
    # market_type='goals' e market='Escanteios Mais/Menos', e nesse conflito
    # quem tem razao e' o texto. Mesma precedencia do caminho ao vivo
    # (website/backend/routers/live.py::_stat_for_market), pra os dois motores
    # nunca classificarem o mesmo pick de formas diferentes.
    _MARKET_TYPE_HINTS = {
        "corners": "corners", "handicap_corners": "corners",
        "cards": "cards", "handicap_cards": "cards",
        "goals": "goals", "handicap_goals": "goals", "handicap": "goals",
        "offsides": "offsides",
        "fouls": "fouls",
        "saves": "saves",
        "shots": "shots",
        "shots_on_target": "shots_on_target",
        "btts": "btts",
        "result": "result_1x2", "outcome": "result_1x2", "result_1x2": "result_1x2",
        "double_chance": "double_chance",
        "to_qualify": "to_qualify",
    }

    _HANDICAP_KEYWORDS = ("handicap", "handi", "h.a.", " ha ")

    def _is_handicap(self, market_name: str, market_type: str | None = None) -> bool:
        if (market_type or "").lower().startswith("handicap"):
            return True
        return any(k in (market_name or "").lower() for k in self._HANDICAP_KEYWORDS)

    def detect_market_type(self, market_name, market_type=None):
        name = (market_name or "").lower()

        # Remove qualificadores de tempo para não confundir keywords
        for strip in ["1° tempo", "1º tempo", "primeiro tempo", "1st half",
                      "first half", "halftime", "half time", "2° tempo", "2º tempo"]:
            name = name.replace(strip, "")

        # Cartões (antes de corner para evitar "red card")
        if any(w in name for w in ["cart", "card", "amarelo", "yellow", "vermelho"]):
            return "cards"

        # Escanteios
        if any(w in name for w in ["canto", "escanteio", "corner", " esc", "asian handicap corner"]):
            return "corners"

        # BTTS
        if any(w in name for w in ["btts", "ambas marcam", "ambas as equipes", "ambas", "both teams"]):
            return "btts"

        # Faltas / defesas / chutes vem ANTES de gols, porque varios nomes
        # dessas familias contem a palavra "goal": "Total ShotOnGoal" (chutes
        # no alvo), "Shots on Goal", "Goalkeeper Saves". Com gols na frente,
        # "Total ShotOnGoal" era classificado como mercado de GOLS e liquidado
        # contra o placar -- e' o mesmo par de familias que ja tinha causado um
        # RED errado no caminho ao vivo (pick #114, fixture 1520774).
        if any(w in name for w in ["falta", "foul"]):
            return "fouls"
        if any(w in name for w in ["defesa", "save", "goleiro", "goalkeeper"]):
            return "saves"
        no_space = name.replace(" ", "")
        if any(w in no_space for w in ["shotontarget", "shotsontarget",
                                        "shotongoal", "shotsongoal"]) \
                or any(w in name for w in ["chute no alvo", "chutes no alvo",
                                            "finalizacao no alvo", "finalização no alvo",
                                            "chute a gol"]):
            return "shots_on_target"
        if any(w in name for w in ["chute", "shot", "finaliza"]):
            return "shots"

        # Gols
        if any(w in name for w in ["gol", "goal", "total de gol"]):
            return "goals"

        # Impedimentos (achado rodando o motor deterministico contra jogos
        # reais: o motor sugere esse mercado -- pick_engine.classify_market()
        # ja suporta -- mas nada aqui sabia resolver o resultado real, o pick
        # ficava pra sempre com result=NULL)
        if any(w in name for w in ["impediment", "offside"]):
            return "offsides"

        # Dupla Chance  (1X / X2 / 12 / "Casa ou Empate" etc.)
        dc_kws = ["dupla chance", "double chance",
                  "casa ou empate", "empate ou casa", "empate ou visit",
                  "visit ou empate", "casa ou visit", "visit ou casa",
                  "1x2x", "1x ", "x2 ", " 1x", " x2", "(1x)", "(x2)", "(12)"]
        if any(w in name for w in dc_kws):
            return "double_chance"

        # Classificação (mata-mata) · quem avança de fase (90min + prorrogação + pênaltis)
        if any(w in name for w in ["classificaç", "classificacao", "to qualify", "qualify", "passagem de fase"]):
            return "to_qualify"

        # Resultado / 1X2
        if any(w in name for w in ["resultado", "1x2", "vencedor", "moneyline",
                                    "match winner", "full time result"]):
            return "result_1x2"

        # Handicap asiático / europeu
        if any(w in name for w in ["handicap", "handi", "h.a.", " ha "]):
            return "handicap"

        # market_type gravado no banco entra so' aqui, depois de o texto nao
        # ter decidido nada -- ver _MARKET_TYPE_HINTS.
        hint = self._MARKET_TYPE_HINTS.get((market_type or "").lower())
        if hint:
            return hint

        # Over/Under genérico → trata como gols se nada mais encaixou
        if any(w in name for w in ["over", "under", "acima", "abaixo", "mais de", "menos de"]):
            return "goals"

        return "unknown"

    ##########################################################################
    # DETECTA LADO (CASA / VISITANTE / TOTAL)
    ##########################################################################
    def detect_side(self, market_name, home_team=None, away_team=None):
        name = market_name.lower()

        if any(w in name for w in ["casa", "home", "mandante"]):
            return "home"
        if any(w in name for w in ["visitante", "away", "fora", "visita"]):
            return "away"

        if home_team and home_team.lower() in name:
            return "home"
        if away_team and away_team.lower() in name:
            return "away"

        return "total"

    ##########################################################################
    # ENGINE ASIÁTICA
    ##########################################################################
    def evaluate_asian(self, value, line, op):
        """Over/Under asiatico. Estatistica ausente, linha fora da grade ou op
        que nao seja over/under devolvem (None, 0) -- "nao sei resolver" --
        em vez do RED que a versao anterior devolvia no fim da funcao.

        Aquele RED final era alcancavel de tres jeitos silenciosos: linha
        negativa (`Decimal("-9.5") % 1` da' -0.5, nunca 0.5), linha fora da
        grade asiatica, e op=None (mercado de cartoes chamava esta funcao sem
        checar op, e o `else` de cada bloco tratava "sem operador" como
        UNDER). Ver services/settlement.py."""
        return settlement.settle_over_under(value, line, op)

    ##########################################################################
    # RESULTADO 1X2  (aceita também variantes de dupla chance na linha)
    ##########################################################################
    def evaluate_result_1x2(self, hg, ag, raw_line, market="",
                            home_team=None, away_team=None):
        """hg/ag: gols casa/fora. raw_line: '1', 'X', '2', '1X', 'Casa ou Empate', etc.

        `market` continua na assinatura pra nao quebrar quem chama, mas nao
        entra mais na decisao: procurar as chaves de dupla chance dentro do
        nome do mercado fazia "Resultado Final (1X2)" casar com a chave "1x"
        e virar um "1 ou X" -- todo pick de 1X2 dava GREEN em empate. A
        selecao vem so' da linha (ver services/settlement.py::settle_outcome).
        """
        return settlement.settle_outcome(hg, ag, raw_line, home_team, away_team)

    ##########################################################################
    # DUPLA CHANCE
    ##########################################################################
    def evaluate_double_chance(self, hg, ag, raw_line, market="",
                               home_team=None, away_team=None):
        return self.evaluate_result_1x2(hg, ag, raw_line, market, home_team, away_team)

    ##########################################################################
    # HANDICAP ASIÁTICO (resultado)
    ##########################################################################
    def evaluate_handicap(self, hg, ag, raw_line, val, side, home_team=None, away_team=None):
        """Handicap Asiatico (linha inteira/meia/quarto-de-bola).

        Bug real encontrado com pick em producao (Handicap Asiatico, linha
        "Home +0.25"): a linha inteira era jogada direto no Decimal(), o
        parse estourava excecao e a pick caia sempre em RED, mercado nenhum
        resolvido de fato -- corrigido usando o `val` ja extraido em
        parse_line() (so o numero) em vez de reparsear o texto cru aqui.

        O lado (casa/fora) normalmente vem embutido no proprio texto da
        linha ("Home +0.25"), nao no nome do mercado -- extrai daqui, com o
        `side` de detect_side(market, ...) so como ultimo fallback (usado
        pelas chamadas de handicap de escanteios/gols, onde raw_line e so o
        numero sem indicacao de lado).

        Tambem cobre quarto-de-bola (.25/.75), que a versao anterior nao
        suportava: divide em duas metades de meia-bola e combina os dois
        resultados em HALF-WIN/HALF-LOSS quando aplicavel.
        """
        if val is None or hg is None or ag is None:
            return (None, Decimal("0"))

        parsed = settlement.parse_line(raw_line, home_team, away_team)
        resolved_side = parsed["side"] or side
        return settlement.settle_asian_handicap(resolved_side, val, hg, ag)

    ##########################################################################
    # RESOLVE STAT_VAL para mercados over/under
    ##########################################################################
    # familia -> (chave casa, chave visitante, chave total) em get_fixture_result().
    # Uma tabela em vez de uma cadeia de ifs: mercado novo entra aqui e passa a
    # ser resolvido nos tres recortes (casa/fora/total) de uma vez.
    _STAT_KEYS = {
        "goals":           ("home_goals", "away_goals", "total_goals"),
        "goals_ht":        ("home_goals_ht", "away_goals_ht", "total_goals_ht"),
        "goals_90":        ("home_goals_90", "away_goals_90", "total_goals_90"),
        "corners":         ("home_corners", "away_corners", "total_corners"),
        "cards":           ("home_cards", "away_cards", "total_cards"),
        "yellow":          ("home_yellow", "away_yellow", "total_yellow"),
        "offsides":        ("home_offsides", "away_offsides", "total_offsides"),
        "fouls":           ("home_fouls", "away_fouls", "total_fouls"),
        "saves":           ("home_saves", "away_saves", "total_saves"),
        "shots":           ("home_shots", "away_shots", "total_shots"),
        "shots_on_target": ("home_shots_on", "away_shots_on", "total_shots_on"),
    }

    def _stat_family(self, mt, market="", is_ht=False, prorrogacao=False):
        """Familia de estatistica efetiva do mercado: resolve 1° tempo, o
        recorte so'-amarelo dos mercados de cartao, e os 90 minutos quando o
        jogo foi pra prorrogacao."""
        if mt == "goals":
            if is_ht:
                return "goals_ht"
            if prorrogacao:
                return "goals_90"
            return "goals"
        if mt == "cards" and any(k in (market or "").lower() for k in ("amarelo", "yellow")):
            return "yellow"
        return mt

    #: Familias cujo total tem um PISO conhecido quando a parcela que falta so'
    #: pode SOMAR. Hoje so' cartoes (amarelos conhecidos, vermelhos omitidos
    #: pela API) -- ver get_fixture_result e settlement.settle_over_under_com_piso.
    _STAT_KEYS_MIN = {
        "cards": ("home_cards_min", "away_cards_min", "total_cards_min"),
    }

    def _resolve_overunder(self, stats, mt, side, is_ht=False, market="", prorrogacao=False):
        """Valor observado do mercado, ou None se o provedor nao publicou.

        None aqui NUNCA vira 0: quem chama e' obrigado a devolver
        "nao liquidado" (ver services/settlement.py, invariante 1)."""
        keys = self._STAT_KEYS.get(self._stat_family(mt, market, is_ht, prorrogacao))
        if not keys:
            return None
        home_key, away_key, total_key = keys
        key = home_key if side == "home" else away_key if side == "away" else total_key
        return stats.get(key)

    def _resolve_overunder_min(self, stats, mt, side, is_ht=False, market="", prorrogacao=False):
        """Piso do valor observado, ou None quando a familia nao tem piso.

        Piso NAO e' estimativa do valor: e' um limite inferior garantido. Ele
        so' liquida quando ja' decide sozinho -- ver settle_over_under_com_piso.
        """
        keys = self._STAT_KEYS_MIN.get(self._stat_family(mt, market, is_ht, prorrogacao))
        if not keys:
            return None
        home_key, away_key, total_key = keys
        key = home_key if side == "home" else away_key if side == "away" else total_key
        return stats.get(key)

    def _resolve_side_pair(self, stats, mt, is_ht=False, market="", prorrogacao=False):
        """(valor casa, valor visitante) da familia -- o que o handicap precisa.
        None se qualquer um dos lados for desconhecido."""
        keys = self._STAT_KEYS.get(self._stat_family(mt, market, is_ht, prorrogacao))
        if not keys:
            return None
        home_val, away_val = stats.get(keys[0]), stats.get(keys[1])
        if home_val is None or away_val is None:
            return None
        return home_val, away_val

    ##########################################################################
    # AVALIA UM PICK COMPLETO
    # Retorna (None, Decimal("0")) quando não é possível determinar o resultado.
    ##########################################################################
    _STAT_MARKETS = ("goals", "corners", "cards", "offsides",
                     "fouls", "saves", "shots", "shots_on_target")

    def _pendente(self, motivo: str):
        """Marca POR QUE o pick nao foi liquidado e devolve UNRESOLVED.

        O log dizia sempre a mesma frase -- "sem estatistica publicada, mercado
        nao reconhecido ou linha ilegivel" -- pras tres causas juntas, e elas
        pedem acoes opostas: folha faltando espera o collector, mercado
        desconhecido e bug do checker, linha ilegivel e dado ruim na geracao.
        Com uma frase so, descobrir qual era exigia reproduzir o caso na mao.

        O motivo fica no objeto em vez de virar terceiro item da tupla porque
        `evaluate_pick` e chamada em varios lugares que desempacotam 2 valores.
        """
        self._ultimo_motivo = motivo
        return (None, Decimal("0"))

    def evaluate_pick(self, market, line, odd, stats, home_team=None, away_team=None,
                      market_type=None):
        mt     = self.detect_market_type(market, market_type)
        is_ht  = self._is_first_half(market)
        side   = self.detect_side(market, home_team, away_team)
        parsed = settlement.parse_line(line, home_team, away_team)
        op, val = parsed["op"], parsed["value"]

        # ── Prorrogacao ─────────────────────────────────────────────────────
        # Casa de aposta liquida TUDO pelos 90 minutos; gol e escanteio do
        # tempo extra nao contam. Mercado de 1° tempo nunca e' afetado (HT e'
        # tempo normal por definicao).
        #
        # Gols: da' pra liquidar certo, porque score.fulltime da API traz o
        # placar dos 90 minutos separado (Belgium x Senegal: 3x2 no total,
        # 2x2 nos 90) -- e' o que home_goals_90/away_goals_90 guardam.
        #
        # Escanteio/cartao/falta/chute/impedimento: /fixtures/statistics NAO
        # separa por periodo, entao o numero dos 90 minutos simplesmente nao
        # existe pra nos. O pick NAO e' liquidado -- fica pendente pra
        # conferencia. A versao anterior devolvia PUSH aqui, o que e' uma
        # afirmacao financeira ("stake devolvida") que ninguem verificou:
        # 6 picks VIP e 3 free em producao seriam anulados por isso, entre
        # eles um RED que estava certo (pick #1452, Belgium x Senegal, 6
        # escanteios contra uma linha Over 8.5 -- perdida com ou sem
        # prorrogacao).
        prorrogacao = stats.get("status") in ("AET", "PEN")

        if is_ht:
            hg = stats.get("home_goals_ht")
            ag = stats.get("away_goals_ht")
            if hg is None or ag is None:
                return self._pendente("placar do 1o tempo ainda nao coletado")
        elif prorrogacao:
            hg = stats.get("home_goals_90")
            ag = stats.get("away_goals_90")
            if hg is None or ag is None:
                return self._pendente("placar dos 90min ainda nao coletado (jogo teve prorrogacao)")
            if mt in self._STAT_MARKETS and mt != "goals":
                return self._pendente("contador dos 90min nao existe na API (jogo teve prorrogacao)")
        else:
            hg = stats.get("home_goals")
            ag = stats.get("away_goals")

        # ── Handicap asiatico de qualquer familia (gols/escanteios/cartoes) ──
        # Uma so' porta pra todos: antes o handicap de gols e o de escanteios
        # tinham caminhos separados e o de CARTOES nao tinha nenhum -- caia no
        # ramo de over/under com op=None e era liquidado como se fosse Under.
        if mt in self._STAT_MARKETS and self._is_handicap(market, market_type):
            pair = self._resolve_side_pair(stats, mt, is_ht, market, prorrogacao)
            if pair is None:
                return self._pendente(f"handicap {mt}: contador nao publicado na folha")
            resolved_side = parsed["side"] or (side if side in ("home", "away") else None)
            return settlement.settle_asian_handicap(resolved_side, val, pair[0], pair[1])

        if mt in self._STAT_MARKETS:
            stat_val = self._resolve_overunder(stats, mt, side, is_ht, market, prorrogacao)
            stat_min = self._resolve_overunder_min(stats, mt, side, is_ht, market, prorrogacao)
            # As duas causas abaixo saiam por dentro do settlement, que devolve
            # UNRESOLVED sem dizer nada -- e' o que fazia picks com folha
            # completa cairem na frase generica e ninguem saber qual dos dois
            # problemas era. Checar ANTES nao muda o veredito, so' o nomeia.
            if op is None:
                return self._pendente(f"linha ilegivel: {line!r} (mercado {market!r})")
            if stat_val is None and stat_min is None:
                return self._pendente(
                    f"contador de {mt} ausente na folha do jogo "
                    f"(mercado {market!r}, lado {side!r})")
            return settlement.settle_over_under_com_piso(stat_val, val, op, stat_min)

        if mt == "btts":
            if hg is None or ag is None:
                return self._pendente("placar ausente na folha (mercado de ambas marcam)")
            if op is None:
                return self._pendente(f"linha ilegivel em ambas marcam: {line!r}")
            return settlement.settle_btts(hg, ag, op)

        if mt == "to_qualify":
            # Lado vem do campo line ("Casa"/"Visitante"/"Home"/"Away"), não do nome do mercado.
            # Se o placar (90min+prorrogação) está empatado, o jogo foi decidido nos pênaltis ·
            # essa informação não é capturada em match_statistics hoje, então não arriscamos
            # um GREEN/RED errado e deixamos pendente para conferência manual.
            if hg is None or ag is None or hg == ag:
                return (None, Decimal("0"))
            side_line = settlement.parse_line(line, home_team, away_team)["side"]
            if side_line == "home":
                return ("GREEN", Decimal("1")) if hg > ag else ("RED", Decimal("-1"))
            if side_line == "away":
                return ("GREEN", Decimal("1")) if ag > hg else ("RED", Decimal("-1"))
            return (None, Decimal("0"))

        if mt in ("result_1x2", "double_chance"):
            return settlement.settle_outcome(hg, ag, line, home_team, away_team)

        if mt == "handicap":
            return self.evaluate_handicap(hg, ag, line, val, side, home_team, away_team)

        return self._pendente(f"mercado nao reconhecido: {market!r}")

    ##########################################################################
    # CALCULA PROFIT
    ##########################################################################
    def calculate_profit(self, factor, odd):
        """Lucro por 1 unidade apostada, ou None se o fator/odd nao forem
        numeros validos. Stake real e' calculado por usuario via Kelly.

        None em vez de -1: um fator ilegivel nao e' uma aposta perdida."""
        return settlement.profit_units(factor, odd)

    ##########################################################################
    # EXECUÇÃO PRINCIPAL (picks_vip)
    ##########################################################################
    def check_all_results(self):

        print(f"[CHECKER] Processando tabela: {self.table}")

        conn = get_connection()
        cur  = conn.cursor()

        cur.execute(f"""
            SELECT id, fixture_id, market, line, odd,
                   home_team_name, away_team_name
            FROM {self.table}
            WHERE result IS NULL;
        """)

        rows = cur.fetchall()

        if not rows:
            print("[CHECKER] Nada pendente.")
            cur.close()
            conn.close()
            return 0

        processed = 0

        for (sid, fixture_id, market, line, odd,
             home_team, away_team) in rows:

            odd = Decimal(str(odd))

            stats = self.get_fixture_result(fixture_id, cur)
            if not stats:
                print(f"[CHECKER] Sem stats para fixture_id={fixture_id} (id={sid}) · aguardando sync.")
                continue

            result, factor = self.evaluate_pick(market, line, float(odd), stats,
                                                home_team, away_team)

            if result is None:
                # O motivo vem de self._pendente. Quando `evaluate_pick` sai
                # por dentro de settlement (linha fora da grade asiatica, ou
                # contador ausente na folha) nenhum motivo foi marcado, e a
                # frase generica antiga continua sendo a resposta honesta.
                motivo = getattr(self, "_ultimo_motivo", None) or (
                    "estatistica do mercado ausente na folha ou linha ilegivel")
                print(f"[CHECKER] id={sid}: {motivo} - segue pendente.")
                self._ultimo_motivo = None
                continue

            profit = self.calculate_profit(factor, odd)
            if profit is None:
                print(f"[CHECKER] id={sid}: fator/odd invalidos ({factor!r}/{odd!r}) - segue pendente.")
                continue

            mt   = self.detect_market_type(market)
            side = self.detect_side(market, home_team, away_team)
            side_label = {"home": "CASA", "away": "VISIT", "total": "TOTAL"}.get(side, "TOTAL")
            print(f"[{sid}] {market} | {mt} | {side_label} | {result}")

            try:
                cur.execute(f"""
                    UPDATE {self.table}
                    SET result = %s,
                        profit = %s
                    WHERE id = %s;
                """, (result, profit, sid))
                conn.commit()
            except Exception as e:
                print(f"[CHECKER] Erro ao salvar id={sid}: {e} · reconectando...")
                try: conn.rollback()
                except Exception: pass
                conn = get_connection()
                cur  = conn.cursor()
                cur.execute(f"""
                    UPDATE {self.table}
                    SET result = %s,
                        profit = %s
                    WHERE id = %s;
                """, (result, profit, sid))
                conn.commit()

            processed += 1

        cur.close()
        conn.close()

        print(f"[CHECKER] Finalizado. Processados: {processed}")

        return processed
