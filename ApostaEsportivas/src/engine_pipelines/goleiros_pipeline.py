"""Picks de DEFESAS DE GOLEIRO via motor deterministico (goalkeeper_model).

E' PROP DE JOGADOR, NAO OVER/UNDER DE TIME
------------------------------------------
Achado com coleta real (Bet365 e Betano, 2026-08-01): o mercado bet_id 267
"Goalkeeper Saves" vem com value_name no formato "<goleiro> - <N>" --
"Everson - 1", "Leo Jardim - 3". Significa "N ou mais defesas DESSE goleiro".
Nao existe linha de time nesse mercado. Por isso este pipeline grava
player_id/player_name em picks_goleiros, e nao um Over/Under de equipe.

"N ou mais" e' P(X >= N), que no goalkeeper_model.prob_over (definido como
P(X > line)) vira prob_over(N - 0.5). Passar N direto contaria uma defesa a
menos e superestimaria o pick.

DE QUE DADO ELE DEPENDE
-----------------------
O sinal forte do modelo e' o volume ofensivo do ADVERSARIO (correlacao 0.88
entre defesas e chutes no alvo sofridos), e esse numero ja existe em
match_statistics. O historico pessoal do goleiro e' opcional -- entra como
segundo sinal quando disponivel, via player_match_stats.saves.

O que NAO e' opcional e' saber por qual time o goleiro joga: sem isso nao da'
pra escolher de qual adversario pegar a media de chutes no alvo, e usar o
lado errado inverte a previsao. Esse vinculo vem de player_match_stats
(posicao G). Enquanto essa tabela estiver vazia o pipeline avisa e nao grava
nada -- e' silencio proposital, nao bug: rodar `python main.py player_stats`
algumas vezes forma o historico.

FREQUENCIA: defesas apareceram em 0.86% das atuacoes medidas, contra 62% das
faltas. Este pipeline naturalmente gera pick em poucos dias -- nao e' sinal de
que esta quebrado.
"""
import json
import re
import unicodedata

from utils.db_utils import get_connection
from utils.data_br import HOJE_BR
from services.match_stats_service import MatchStatsService
from services.pick_engine import competition_profile as cp
from services.pick_engine.config import DEFAULT_CONFIG
from services.odds_service import OddsService
from services.pick_engine.goalkeeper_model import (
    MIN_OPPONENT_SAMPLE,
    analyze_saves_market,
)
from services.pick_engine.market_pick_score import faixa_config, pick_score
from services.pick_engine.saves_calibration import recalibrar as recalibrar_saves
from services.pick_engine.staking import calculate_stake
from services.pick_engine.ai_review import review_gate
from services.pick_engine import context_gate, tie_effect
from engine_pipelines.decision_log import (
    MOTIVO_ERRO, MOTIVO_SEM_CANDIDATO,
    log_decision, log_run, log_skip,
)

# FAIXA DE ODD [1.10, 2.00], reposta em 2026-08-16 a pedido do usuario.
#
# HISTORICO, que importa pra nao repetir o erro: era [1.35, 2.00], herdada dos
# pipelines de over/under de TIME, e foi removida em 2026-08-07 porque nos jogos
# daquele dia TODA linha dentro dela tinha edge negativo -- as unicas que
# passavam o EDGE_MIN estavam fora e do lado ALTO (Vagner 5+ @ 5.70 com edge
# +0.070 e 6+ @ 10.50 com +0.063). Sem faixa, o pipeline passou a achar valor so'
# na cauda, e em 08/08 gerou "Everson 6 ou mais defesas" @ 11.00 com 15.4% de
# probabilidade: um pick que perde 6 vezes a cada 7.
#
# O QUE MUDOU ENTRE 07/08 E HOJE e' o PROB_MIN abaixo. Aquela medicao de 07/08
# descreve um pipeline SEM piso de probabilidade, onde a unica coisa que
# sobrevivia era a cauda -- por isso a faixa parecia estar matando o pipeline
# inteiro. Com o piso, a cauda ja' nao gera candidato, entao a faixa nao volta a
# zerar nada pelo mesmo motivo de antes: ela agora corta o que o piso ja'
# cortou, e passa a valer como rede contra dado ruim.
#
# O PISO DESCE DE 1.35 PRA 1.10 porque e' ali que mora o pick que este modelo
# realmente sustenta: com mu perto da media da liga (2.54 defesas), "1 ou mais"
# da' ~85% de probabilidade, que e' pick de odd baixa, nao de cauda.
#
# ATENCAO ao combinar os dois cortes -- edge >= EDGE_MIN exige probabilidade >=
# 1/odd + EDGE_MIN, ou seja 96.9% em odd 1.10, 89.3% em 1.20 e 82.9% em 1.30.
# Na pratica o trecho 1.10-1.27 da faixa e' inalcancavel, e quem limita ali e' o
# EDGE_MIN, nao o piso.
ODD_MIN = 1.10
ODD_MAX = 2.00

# Margem minima pra gravar. Mais exigente que faltas (0.04) porque aqui a
# amostra por goleiro e' pequena e a distribuicao e' superdispersa: erro de
# estimativa da media custa mais caro.
EDGE_MIN = 0.06

# PISO DE PROBABILIDADE (2026-08-08). O RISCO ASSUMIDO descrito acima deixou de
# ser hipotetico: em 08/08 este pipeline gerou "Everson - 6 ou mais defesas" a
# odd 11.00 com probabilidade de 15.4%. Passou no EDGE_MIN pela aritmetica
# (0.154 * 11.00 - 1 = +0.69) sem o modelo ter dito nada a favor -- e' um pick
# que perde 6 vezes a cada 7. Pedido do usuario no mesmo dia, em uma frase:
# "quero picks que ganham estatisticamente, nao achar onde tem valor de odd".
#
# O numero nao e' novo: e' o mesmo PickEngineConfig.min_taxa que ranking.py ja
# aplica em VIP, free, multipla e alavancagem desde sempre. Faltas e goleiros
# nunca passaram por aquele caminho (pipeline proprio, ver docstring do modulo),
# entao herdaram o EDGE_MIN e nenhum piso -- a assimetria era acidente de
# arquitetura, nao decisao. Importado em vez de redigitado pra continuar
# existindo UM lugar que define o que e' probabilidade aceitavel.
#
# Efeito conhecido: este pipeline ja gera pouco pick (defesas aparecem em 0.86%
# das atuacoes) e vai gerar bem menos. O modelo acha valor na cauda, e a cauda
# e' justamente o que este piso corta.
PROB_MIN = DEFAULT_CONFIG.min_taxa

# Ordenacao dos candidatos aprovados (2026-08-16). Antes disto tudo era decidido
# por MAIOR EDGE -- ver a docstring de market_pick_score pro numero medido que
# derrubou esse criterio no motor generico em 14/08. Os cortes nao mudaram.
SCORE_CONFIG = faixa_config(ODD_MIN, ODD_MAX)

# Satura em 10 jogos do adversario no mando certo. O minimo do modelo e' 5
# (MIN_OPPONENT_SAMPLE) e o pool por mando fica na casa de 7-8 jogos, mesma
# ordem de grandeza que pool_and_field mediu no motor generico -- saturar em 10
# mantem a diferenca entre 5 e 8 jogos visivel sem premiar historico gigante.
AMOSTRA_SATURACAO = 10

NOMES_MERCADO = ("goalkeeper saves", "saves", "player saves")

# "Everson - 1" / "Jandrei Chitolina - 2" / "Joao Ricardo - 3+".
# O "+" opcional no fim e' a notacao da Bet365 pro MESMO produto que a Betano
# escreve sem sinal -- achado real 2026-08-05 comparando as duas casas no
# mesmo jogo: "Weverton Pereira - 2" a 1.31 (Betano) e "Weverton - 2+" a 1.40
# (Bet365). Sem aceitar o "+", a regex antiga (que exigia digito no fim da
# string) descartava em silencio TODA a oferta da Bet365: 5 das 13 linhas
# dentro da faixa de odd util naquele dia.
_VALOR_RE = re.compile(r"^(?P<nome>.+?)\s*-\s*(?P<n>\d+)\s*\+?$")


def _parse_valor(value_name: str) -> tuple[str, int] | None:
    """('Everson', 1) a partir de 'Everson - 1' ou 'Everson - 1+'.

    As duas grafias significam a mesma coisa ("N ou mais defesas"), entao o
    "+" e' so' notacao e nao muda a linha. Nunca adivinha: formato diferente
    do esperado devolve None e o candidato e' descartado, em vez de virar um
    pick com linha errada.
    """
    m = _VALOR_RE.match((value_name or "").strip())
    if not m:
        return None
    nome = m.group("nome").strip()
    if not nome:
        return None
    return nome, int(m.group("n"))


def _normalizar_nome(nome: str) -> str:
    """Chave de comparacao de nome de jogador, sem acento e sem caixa.

    A casa de aposta escreve "Joao Ricardo" e a API-Football grava "Joao
    Ricardo" com til -- comparar cru descartava o goleiro como desconhecido.
    Achado na validacao com dado real (fixture 1546848, Fortaleza).
    """
    sem_acento = unicodedata.normalize("NFKD", nome or "")
    sem_acento = "".join(ch for ch in sem_acento if not unicodedata.combining(ch))
    return " ".join(sem_acento.lower().split())


def _resolver_goleiro(nome_ofertado: str, goleiros: list,
                      home_team_id: int, away_team_id: int) -> dict | None:
    """Goleiro da oferta, procurado APENAS entre os dois times da partida.

    A casa de aposta e a API-Football nem sempre escrevem o nome igual: em
    2026-08-05 a Betano publicou "Weverton Pereira" (Palmeiras) enquanto a base
    tinha "Weverton" -- e existe OUTRO "Weverton" (Gremio) na mesma base, que
    inclusive jogava no mesmo dia. Casar so' por nome pegaria o do Gremio,
    leria o adversario errado e INVERTERIA a previsao, que e' pior que nao
    gerar pick nenhuma.

    Por isso o time entra como parte da chave, nao como conferencia posterior:
      1. nome normalizado identico vence;
      2. senao, aceita quando os tokens de um nome estao contidos nos do outro
         ("weverton" dentro de "weverton pereira");
      3. empate entre dois goleiros do jogo devolve None -- ambiguidade nunca
         vira chute.
    """
    alvo = set(_normalizar_nome(nome_ofertado).split())
    if not alvo:
        return None

    do_jogo = [g for g in goleiros if g["team_id"] in (home_team_id, away_team_id)]

    exatos = [g for g in do_jogo if set(g["nome_norm"].split()) == alvo]
    if exatos:
        return exatos[0] if len(exatos) == 1 else None

    parciais = []
    for g in do_jogo:
        tokens = set(g["nome_norm"].split())
        if tokens and (tokens <= alvo or alvo <= tokens):
            parciais.append(g)
    return parciais[0] if len(parciais) == 1 else None


def _goleiros_conhecidos(cur) -> list:
    """Goleiros com vinculo jogador->time, um item por goleiro.

    Lista e nao dicionario por nome: dois goleiros podem normalizar pro MESMO
    nome (o "Weverton" do Gremio e o "Weverton Pereira" do Palmeiras), e um
    dict por nome faria o segundo sobrescrever o primeiro em silencio. Quem
    resolve a ambiguidade e' _resolver_goleiro, usando os times do jogo.

    NAO exige saves IS NOT NULL: o que este mapa resolve, e que e'
    obrigatorio, e' o vinculo goleiro->time (sem ele nao da' pra saber de qual
    adversario pegar o volume ofensivo). A media de defesas e' opcional no
    modelo -- entra como segundo sinal quando existe. Exigir saves aqui
    reduzia 112 goleiros conhecidos pra 49, descartando por falta de um dado
    que o modelo nem precisa.

    A media, quando existe, so' conta atuacao com minutos: goleiro reserva que
    nao entrou apareceria com 0 e afundaria o numero.
    """
    cur.execute("""
        SELECT player_id,
               MAX(player_name)                                          AS player_name,
               MAX(team_id)                                              AS team_id,
               MAX(team_name)                                            AS team_name,
               AVG(saves) FILTER (WHERE saves IS NOT NULL
                                    AND COALESCE(minutes, 0) > 0)::numeric(10,3) AS saves_avg,
               COUNT(*)   FILTER (WHERE saves IS NOT NULL
                                    AND COALESCE(minutes, 0) > 0)        AS jogos_com_defesa
        FROM player_match_stats
        WHERE position = 'G'
        GROUP BY player_id
    """)
    out = []
    for r in cur.fetchall():
        nome = _normalizar_nome(r[1])
        if not nome:
            continue
        out.append({
            "player_id": r[0], "player_name": r[1],
            "team_id": r[2], "team_name": r[3],
            "saves_avg": float(r[4]) if r[4] is not None else None,
            "jogos": int(r[5] or 0),
            "nome_norm": nome,
        })
    return out


def _historico(match_stats: MatchStatsService, fixture: dict, team_id: int) -> list:
    """Historico do time, respeitando o perfil da competicao.

    Mesma correcao do pipeline de faltas: em jogo de copa, filtrar so' pela
    liga do fixture devolvia 1 jogo de historico -- abaixo do minimo de 5 que
    o modelo exige, entao nenhum candidato passava.
    """
    since = match_stats.get_structural_change_date(team_id)
    if cp.uses_all_competitions_history(fixture["league_id"]):
        return match_stats.get_last_n_all_competitions(team_id, since_date=since)
    return match_stats.get_all_matches_full(
        team_id, fixture["season"], fixture["league_id"], since_date=since)


def _media_chutes_no_alvo(historico: list, team_id: int,
                          mando: str) -> tuple[float | None, int]:
    """Chutes no alvo que o time PRODUZ por jogo NO MANDO em que ele vai jogar
    hoje (o que o goleiro adversario vai ter que defender).

    MANDO (2026-08-16). Ate' aqui esta funcao somava os jogos do time em casa e
    fora no mesmo balde, e a media saia de uma mistura de dois mandos. E' o
    MESMO erro que o motor generico corrigiu em 2026-08-08 em
    stats_model.pool_and_field, com diferenca medida em producao naquele dia:

        Serie A 2026:  5.62 escanteios do mandante x 4.41 do visitante (+27%)
        Serie B 2026:  5.78 x 4.25 (+36%)

    A correcao nunca chegou aqui porque este pipeline nao passa por
    pool_and_field (motor proprio, ver docstring do modulo). O efeito e' direto
    na previsao: um time que chuta muito em casa e pouco fora inflava a
    expectativa de defesas do goleiro adversario quando o jogo era FORA, que e'
    exatamente o caso que o usuario levantou.

    Efeito colateral aceito, o mesmo que pool_and_field aceitou: o pool cai
    aproximadamente pela metade. Com MIN_OPPONENT_SAMPLE de 5, time com
    historico curto no mando certo deixa de gerar candidato -- e' o numero
    honesto, e o balde misturado de antes era grande por incluir jogo que nao
    respondia a pergunta.
    """
    if mando not in ("home", "away"):
        raise ValueError(f"mando invalido: {mando!r}")

    campo = "home_shots_on" if mando == "home" else "away_shots_on"
    chave_time = "home_team_id" if mando == "home" else "away_team_id"

    valores = []
    for jogo in historico:
        if jogo.get(chave_time) != team_id:
            continue
        v = jogo.get(campo)
        if v is not None and v > 0:
            valores.append(float(v))
    if not valores:
        return None, 0
    return round(sum(valores) / len(valores), 3), len(valores)


def _fixtures_de_hoje(cur) -> list:
    cur.execute(f"""
        SELECT DISTINCT
            f.fixture_id, f.league_id, f.season,
            f.home_team_id, f.away_team_id, f.home_team, f.away_team,
            f.match_datetime, l.name
        FROM fixtures f
        JOIN odds_values ov ON ov.fixture_id = f.fixture_id
        LEFT JOIN leagues l ON l.league_id = f.league_id
        WHERE f.match_datetime::date = {HOJE_BR}
          AND f.status IN ('NS', 'TBD')
        ORDER BY f.match_datetime
    """)
    return [
        {
            "fixture_id": r[0], "league_id": r[1], "season": r[2],
            "home_team_id": r[3], "away_team_id": r[4],
            "home_team": r[5], "away_team": r[6], "match_datetime": r[7],
            "league_name": r[8],
        }
        for r in cur.fetchall()
    ]


def melhor_por_goleiro(candidatos: list) -> list:
    """UM candidato por goleiro, em DOIS passos: melhor preco, depois melhor
    linha.

    As linhas do mesmo goleiro sao a mesma aposta em graus diferentes (6+
    implica 5+ implica 4+), e a MESMA linha ainda reaparece quando duas casas
    cotam o jogo -- este pipeline le odd RAW, entao nao tem o "melhor preco por
    linha" que _odds_over_faltas faz no de faltas.

    Enquanto existiu teto de odd 2.00 isso nunca apareceu, porque nenhum
    candidato passava. Assim que o teto saiu (2026-08-07), a medicao dos jogos
    do dia devolveu QUATRO candidatos do mesmo goleiro: 4+ @ 3.75, 5+ @ 7.00,
    5+ @ 5.70 (outra casa) e 6+ @ 10.50. Publicar os quatro e' publicar a mesma
    aposta quatro vezes, gastar quatro revisoes de IA e multiplicar por quatro a
    exposicao real do assinante num goleiro so'.

    POR QUE DOIS PASSOS, E NAO UM SO' COMO ANTES (2026-08-16)
    --------------------------------------------------------
    Ate' aqui um unico criterio (maior edge) resolvia os dois casos de uma vez,
    porque entre duas casas na MESMA linha a de odd maior tem edge maior. Com o
    score isso deixa de valer, e no sentido perigoso: o termo de seguranca
    premia odd baixa, entao comparar duas casas na mesma linha pelo score
    escolheria o PIOR preco pra exatamente a mesma aposta.

    Os dois passos separam perguntas que sao mesmo diferentes:

      1. MESMA aposta em casas diferentes -> so' o preco decide, maior odd vence.
      2. Apostas diferentes no mesmo goleiro -> decide o score (probabilidade,
         seguranca do preco, amostra e edge), igual ao resto do motor.

    A reducao e' por GOLEIRO e nao por jogo: os dois goleiros da partida sao
    apostas distintas e ambos podem sair.
    """
    # 1. Mesma linha em casas diferentes: fica a de melhor preco.
    melhor_preco: dict = {}
    for c in candidatos:
        chave = (c["goleiro"]["player_id"], c["n_defesas"])
        atual = melhor_preco.get(chave)
        if atual is None or c["odd"] > atual["odd"]:
            melhor_preco[chave] = c

    # 2. Linhas diferentes do mesmo goleiro: fica a de melhor score.
    melhor: dict = {}
    for c in melhor_preco.values():
        player_id = c["goleiro"]["player_id"]
        atual = melhor.get(player_id)
        if atual is None or c["pick_score"] > atual["pick_score"]:
            melhor[player_id] = c
    return list(melhor.values())


def _avaliar_fixture(fixture: dict, goleiros: dict,
                     match_stats: MatchStatsService,
                     odds_service: OddsService,
                     constantes: dict | None = None) -> list:
    """Candidatos de defesas pra um jogo (pode haver um por goleiro)."""
    # RAW pelo mesmo motivo do pipeline de faltas: load_odds_structured
    # agrupa por line_value e descarta o que nao parear como Over/Under.
    # "Everson - 1" nao e' par de nada e sairia fora.
    structured = odds_service.load_odds_by_fixture(fixture["fixture_id"])
    if not structured:
        return []

    # Media de chutes no alvo de cada lado, calculada uma vez por jogo.
    hist_casa = _historico(match_stats, fixture, fixture["home_team_id"])
    hist_fora = _historico(match_stats, fixture, fixture["away_team_id"])
    # Cada lado no mando em que ele vai jogar HOJE: o mandante produz chutes
    # como mandante, o visitante como visitante. Ver _media_chutes_no_alvo.
    chutes_casa, n_casa = _media_chutes_no_alvo(
        hist_casa, fixture["home_team_id"], mando="home")
    chutes_fora, n_fora = _media_chutes_no_alvo(
        hist_fora, fixture["away_team_id"], mando="away")

    # Contexto de confronto (2026-08-20). Aqui ele NAO desloca a
    # probabilidade por direcao, e a razao e' medicao, nao esquecimento: nos
    # jogos de volta reais da base, defesas de goleiro deram +0.79 (ep 1.22)
    # pro lado que precisa reverter e +0.01 (ep 0.89) pro que administra --
    # zero nos dois. A historia de que "o time com vantagem se fecha e o
    # goleiro do outro lado nem trabalha" nao aparece nos numeros; quem
    # administra contra-ataca contra uma defesa adiantada.
    #
    # O que sobra, e que importa, e' o DESCONTO DE REGIME: a media de chutes
    # no alvo do adversario sai dos jogos normais dele, e uma volta de
    # mata-mata com o agregado aberto nao pertence aquela distribuicao. Isso e'
    # incerteza sobre a estimativa, e vira desconto de probabilidade.
    contexto = context_gate.build_for_fixture(match_stats, fixture)

    candidatos = []
    for o in structured:
        nome_mercado = (o.get("market_name") or "").strip().lower()
        if nome_mercado not in NOMES_MERCADO:
            continue
        odd = float(o.get("odd") or 0)
        if (ODD_MIN is not None and odd < ODD_MIN) or (ODD_MAX is not None and odd > ODD_MAX):
            continue

        parsed = _parse_valor(o.get("value_name"))
        if not parsed:
            continue
        nome_goleiro, n_defesas = parsed

        info = _resolver_goleiro(
            nome_goleiro, goleiros, fixture["home_team_id"], fixture["away_team_id"])
        if not info:
            # Goleiro que ainda nao aparece em player_match_stats por nenhum
            # dos dois times, ou nome ambiguo entre eles: sem o vinculo certo
            # nao da' pra saber de qual adversario pegar o volume ofensivo.
            # Descarta em vez de chutar o lado.
            continue

        # De qual lado ele esta -> quem chuta contra ele, e em que mando esse
        # adversario joga hoje (goleiro da casa enfrenta o visitante jogando
        # como visitante, e vice-versa).
        if info["team_id"] == fixture["home_team_id"]:
            adversario_chutes, adversario_n, adversario_mando = chutes_fora, n_fora, "away"
        elif info["team_id"] == fixture["away_team_id"]:
            adversario_chutes, adversario_n, adversario_mando = chutes_casa, n_casa, "home"
        else:
            continue

        analise = analyze_saves_market(
            opponent_shots_on_avg=adversario_chutes,
            keeper_saves_avg=info["saves_avg"],
            sample_size=adversario_n,
            # Os DOIS numeros de amostra, que sao de coisas diferentes:
            # `sample_size` conta os jogos do ADVERSARIO (de onde sai o volume
            # de chutes no alvo) e `keeper_sample` conta as aparicoes DO
            # GOLEIRO. Ate' 2026-08-20 so' o primeiro chegava ao modelo, e a
            # media de defesas de quem tinha uma unica aparicao entrava crua.
            keeper_sample=info.get("jogos"),
            odd=odd,
            # "N ou mais" = P(X >= N) = prob_over(N - 0.5). Ver docstring.
            line=n_defesas - 0.5,
            constantes=constantes,
        )
        if not analise:
            continue
        # ANTES dos cortes: o desconto de regime tem que poder reprovar o pick.
        # `escopo` e' o lado do GOLEIRO -- tie_effect inverte sozinho pra ler a
        # pressao do adversario (ver _lado_do_escopo), que e' quem chuta nele.
        analise = tie_effect.aplicar_em_analise(
            analise, contexto, familia="saves",
            escopo=("home" if info["team_id"] == fixture["home_team_id"] else "away"),
            direcao="over", linha=n_defesas - 0.5,
            lambda_esperado=analise.get("expected_saves"))
        if analise.get("probability", 0) < PROB_MIN:
            continue
        if analise.get("edge", 0) < EDGE_MIN:
            continue

        analise["pick_score"] = pick_score(
            probability=analise["probability"], odd=odd, edge=analise["edge"],
            amostra=adversario_n, amostra_saturacao=AMOSTRA_SATURACAO,
            config=SCORE_CONFIG,
        )

        candidatos.append({
            **analise,
            "fixture": fixture,
            "goleiro": info,
            "n_defesas": n_defesas,
            "adversario_chutes": adversario_chutes,
            "adversario_n": adversario_n,
            "adversario_mando": adversario_mando,
            "bookmaker": o.get("bookmaker_name") or o.get("bookmaker"),
            "market_id": o.get("market_id"),
            # PT primeiro, igual ao orchestrator do pre-jogo e ao pipeline de
            # faltas. Sem isto "Goalkeeper Saves" iria CRU pra
            # picks_goleiros.market e pra tela. Ainda nao houve pick de goleiro
            # publicado em producao, entao aqui a correcao e' preventiva -- o
            # mesmo defeito ja tinha chegado ao usuario via faltas.
            "market_name": (o.get("market_pt") or o.get("market_name")
                            or "Defesas do goleiro"),
        })

    return melhor_por_goleiro(candidatos)


def _explicar(c: dict) -> str:
    g = c["goleiro"]
    onde = "jogando em casa" if c.get("adversario_mando") == "home" else "jogando fora"
    partes = [
        f"{g['player_name']} enfrenta um adversário que produz "
        f"{c['adversario_chutes']} chutes no alvo por jogo {onde} "
        f"({c['adversario_n']} jogos nesse mando)."
    ]
    if g.get("saves_avg"):
        partes.append(
            f"Ele faz {g['saves_avg']} defesas por jogo em {g['jogos']} atuações."
        )
    partes.append(f"Defesas esperadas: {c['expected_saves']}.")
    partes.append(
        f"Probabilidade de {c['n_defesas']} ou mais: {c['probability'] * 100:.1f}% "
        f"(odd justa {c['fair_odd']} contra {c['odd']} oferecida, "
        f"margem de {c['edge'] * 100:+.1f}%)."
    )
    return " ".join(partes)


def _salvar(cur, c: dict) -> None:
    f, g = c["fixture"], c["goleiro"]
    stake_pct, stake_units = calculate_stake(
        confidence=c["probability"], odd=c["odd"], ev=c["ev"], pick_type="free",
    )
    engine_debug = json.dumps({
        "modelo": "goalkeeper_model/binomial_negativa",
        "expected_saves": c["expected_saves"],
        "adversario_chutes_no_alvo": c["adversario_chutes"],
        "adversario_amostra": c["adversario_n"],
        "adversario_mando": c.get("adversario_mando"),
        "goleiro_saves_avg": g.get("saves_avg"),
        "goleiro_jogos": g.get("jogos"),
        "lift_vs_base": c.get("lift_vs_base"),
        "fair_odd": c["fair_odd"], "edge": c["edge"], "ev": c["ev"],
        "pick_score": c.get("pick_score"),
        # De quais constantes saiu esta probabilidade. Sem isto, um pick de hoje
        # e um de dois meses atras com a mesma entrada e saidas diferentes
        # ficariam inexplicaveis.
        "calibragem": c.get("calibragem"),
        "ai_review": c.get("ai_review"),
    }, default=str, ensure_ascii=False)

    cur.execute(f"""
        INSERT INTO picks_goleiros
            (fixture_id, match_date, home_team, away_team,
             home_team_id, away_team_id, league_id, league_name,
             player_id, player_name, team_id, team_name,
             market, market_type, line, line_value, odd, bet_house, market_id,
             confidence, prob_real, edge, reasoning,
             stake_pct, stake_units, engine_debug)
        VALUES (%s, {HOJE_BR}, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, 'saves', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_date, fixture_id, player_id) DO NOTHING
    """, (
        f["fixture_id"], f["home_team"], f["away_team"],
        f["home_team_id"], f["away_team_id"], f["league_id"], f.get("league_name"),
        g["player_id"], g["player_name"], g["team_id"], g["team_name"],
        c["market_name"],
        f"{g['player_name']} · {c['n_defesas']} ou mais defesas", c["n_defesas"],
        c["odd"], c["bookmaker"], c["market_id"],
        c["probability"], c["probability"], c["edge"], _explicar(c),
        stake_pct, stake_units, engine_debug,
    ))


def run_goleiros_engine():
    conn = get_connection()
    cur = conn.cursor()

    goleiros = _goleiros_conhecidos(cur)
    if not goleiros:
        print("[GOLEIROS_ENGINE] player_match_stats nao tem nenhum goleiro ainda.")
        print("[GOLEIROS_ENGINE] Sem esse vinculo goleiro->time nao da' pra saber "
              "de qual adversario pegar o volume ofensivo, e chutar o lado "
              "inverteria a previsao. Rode `python main.py player_stats 50` "
              "algumas vezes pra formar o historico.")
        cur.close()
        conn.close()
        return

    fixtures = _fixtures_de_hoje(cur)
    if not fixtures:
        print("[GOLEIROS_ENGINE] Nenhum jogo de hoje com odds coletadas.")
        cur.close()
        conn.close()
        return

    print(f"[GOLEIROS_ENGINE] Avaliando {len(fixtures)} jogo(s) contra "
          f"{len(goleiros)} goleiro(s) conhecidos "
          f"(minimo {MIN_OPPONENT_SAMPLE} jogos do adversario)...")

    # RECALIBRAGEM A CADA RODADA (2026-08-16, mesmo pedido que colocou isto no
    # pipeline de faltas). Remede a relacao chute-no-alvo -> defesa, a media da
    # liga e a dispersao contra as atuacoes que existem hoje, em vez de usar pra
    # sempre os tres numeros medidos em 01/08. Amostra curta ou falha de banco
    # devolve as congeladas -- ver saves_calibration.
    constantes, calibragem = recalibrar_saves(cur)
    print(f"[GOLEIROS_ENGINE] Constantes {calibragem['origem']}: "
          f"{calibragem['atuacoes']} atuacoes"
          + (f", var/media {calibragem['variancia_sobre_media']}"
             if calibragem.get("variancia_sobre_media") else "") + ".")
    if calibragem.get("erro"):
        print(f"[GOLEIROS_ENGINE] Recalibragem falhou ({calibragem['erro']}); "
              f"seguindo com as constantes congeladas.")
    for troca in calibragem.get("trocadas", []):
        print(f"[GOLEIROS_ENGINE]   {troca}")

    match_stats = MatchStatsService()
    odds_service = OddsService()

    candidatos = []
    for fixture in fixtures:
        try:
            do_fixture = _avaliar_fixture(fixture, goleiros, match_stats,
                                          odds_service, constantes=constantes)
        except Exception as e:
            print(f"[GOLEIROS_ENGINE] Erro no fixture {fixture['fixture_id']}: {e}")
            log_skip("GOLEIROS_ENGINE", fixture, f"{MOTIVO_ERRO}: {e}")
            continue
        if do_fixture:
            candidatos.extend(do_fixture)
        else:
            # Este pipeline e' o que mais precisa do registro do jogo vazio:
            # defesa aparece em 0.86% das atuacoes, entao o dia sem pick e' o
            # caso NORMAL. Sem esta linha nao dava pra separar "avaliou os
            # jogos e nenhum goleiro qualificou" de "o pipeline nem rodou".
            log_skip("GOLEIROS_ENGINE", fixture, MOTIVO_SEM_CANDIDATO)

    if not candidatos:
        motivo = ("nenhum candidato passou (defesas aparecem em 0.86% das atuacoes "
                  "medidas -- dia sem pick e' o normal desse mercado, nao falha)")
        print(f"[GOLEIROS_ENGINE] {motivo.capitalize()}.")
        log_run("GOLEIROS_ENGINE", motivo)
        cur.close()
        conn.close()
        return

    # Maior score primeiro (era maior edge ate' 2026-08-16): esta e' a fila que
    # a revisao de IA percorre e a que define o que o dia publica.
    candidatos.sort(key=lambda c: c["pick_score"], reverse=True)

    gate = review_gate("goleiros")
    salvos = 0
    for c in candidatos:
        # Mesma marcacao do pipeline de faltas: candidato unico e ja' escolhido.
        log_decision("GOLEIROS_ENGINE", c["fixture"], [{**c, "is_best_pick": True}], [c])
        aprovado = gate.apply([c], "goleiros", c["fixture"])
        if not aprovado:
            print(f"[GOLEIROS_ENGINE] {c['goleiro']['player_name']} vetado pela revisao de IA.")
            continue
        _salvar(cur, {**c, "ai_review": aprovado[0].get("ai_review"),
                      "calibragem": calibragem})
        salvos += 1
        print(f"[GOLEIROS_ENGINE] Salvo: {c['goleiro']['player_name']} "
              f"({c['goleiro']['team_name']}) · {c['n_defesas']}+ defesas @ {c['odd']} "
              f"(prob={c['probability'] * 100:.1f}%, margem={c['edge'] * 100:+.1f}%)")

    conn.commit()
    cur.close()
    conn.close()
    print(f"[GOLEIROS_ENGINE] {salvos} pick(s) de defesas gravado(s).")


if __name__ == "__main__":
    run_goleiros_engine()
