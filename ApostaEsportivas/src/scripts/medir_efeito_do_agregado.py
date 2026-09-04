"""
medir_efeito_do_agregado.py · refaz, com a base de hoje, a medicao de
2026-08-19 que definiu as constantes de `pick_engine/tie_effect.py`.

SOMENTE LEITURA. Nenhum INSERT/UPDATE/DELETE -- pode rodar contra PROD sem
efeito colateral.

Uso:
  DB_ENV=prod python src/scripts/medir_efeito_do_agregado.py
  DB_ENV=prod python src/scripts/medir_efeito_do_agregado.py --janela 45

POR QUE REFAZER
---------------
A tabela `_MEDIDO` do tie_effect saiu de 11 confrontos de volta, e as celulas
assimetricas ("atras" / "na_frente") de apenas 4 -- e' o que
`AMOSTRA_ASSIMETRICA = 4` declara. Com 4 jogos, "corners +1.98 (ep 1.18)" e
1.7 erros-padrao: o efeito pode ser metade disso, ou zero.

O modulo aplica esses numeros a TODA copa que o motor avaliar, encolhidos por
erro-padrao e ainda cortados pela metade em `FATOR_DE_EXTRAPOLACAO`. Os dois
descontos existem exatamente porque a amostra e' pequena. Mais amostra e' o
unico caminho que remove desconto sem inventar numero.

O QUE ESTE SCRIPT RESPONDE
--------------------------
Para cada familia e cada papel no agregado (atras / na_frente / empatado),
quanto o lado se desloca da PROPRIA media, e com que erro-padrao. Sai no mesmo
formato da tabela `_MEDIDO`, pra a comparacao ser direta.

METODOLOGIA -- IGUAL A DE 19/08, DE PROPOSITO
---------------------------------------------
Mudar metodo E amostra ao mesmo tempo produziria uma tabela nova que nao da'
pra comparar com a antiga, e a pergunta aqui e' justamente "o efeito medido
mudou?".

  1. Confronto de volta = dois jogos entre os MESMOS times, na MESMA
     competicao e temporada, com o mando INVERTIDO, dentro de `--janela` dias.
     A inversao de mando e' a prova de que e' ida-e-volta e nao dois encontros
     quaisquer -- mesmo criterio de match_context_model.encontrar_jogo_de_ida.

  2. Papel de cada lado na volta, pelo placar da ida (agregado simples, como na
     medicao original): quem perdeu a ida esta' `atras`, quem ganhou esta'
     `na_frente`, 'empatado' quando a ida terminou igual.

  3. O deslocamento de cada lado e' medido contra a media dele NO MESMO MANDO
     (casa contra casa, fora contra fora). Sem esse casamento, "esta atras" se
     confunde com "esta jogando em casa", que e' o efeito mais forte do
     futebol e contaminaria a tabela inteira.

  4. So' jogos ANTERIORES a data da volta entram na media -- sem lookahead,
     mesma regra dos outros scripts de medicao.

  5. Folha incompleta nao entra: reusa `stats_model._tem_folha_da_familia`, o
     mesmo criterio do motor. Sem isso, "a API nao publicou escanteio" viraria
     "aconteceram zero escanteios" e o deslocamento sairia negativo de mentira.

COMO LER A SAIDA
----------------
`n` e' o numero de LADOS medidos, nao de confrontos: cada volta contribui com
dois lados (um atras, um na frente) ou dois empatados.

A coluna `sigma` e' media/erro-padrao. Abaixo de 2 o efeito nao se sustenta --
e' o criterio que deixou `cards`, `saves` e `shots_on_target` fora da tabela
`_MEDIDO` na medicao original.
"""
import os
import sys
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.db_utils import get_connection
from services.pick_engine import competition_profile as cp
from services.pick_engine import stats_model


#: Familias medidas e de onde sai a contagem de cada lado. Mesma lista da
#: medicao de 19/08 -- inclusive as tres que ficaram de fora da tabela final
#: (`cards`, `saves`, `shots_on_target`), porque "continua sem efeito" e'
#: resultado tao util quanto o contrario.
FAMILIAS = {
    "corners":         ("home_corners", "away_corners"),
    "shots":           ("home_total_shots", "away_total_shots"),
    "shots_on_target": ("home_shots_on", "away_shots_on"),
    "goals":           ("home_goals", "away_goals"),
    "fouls":           ("home_fouls", "away_fouls"),
    "saves":           ("home_goalkeeper_saves", "away_goalkeeper_saves"),
    "cards":           (None, None),   # pontos de cartao, ver _valor_do_lado
}

#: Amostra minima de jogos proprios no mesmo mando pra a media do time valer.
#: Abaixo disso o "deslocamento" seria medido contra ruido.
MIN_JOGOS_PROPRIOS = 4

#: Janela padrao entre ida e volta, em dias. Mata-mata continental joga com
#: 7 a 21 dias de intervalo; 45 cobre com folga sem deixar entrar dois
#: encontros de fases diferentes da mesma competicao.
JANELA_PADRAO = 45


def _cartao_pontos(jogo, lado):
    """Amarelo=1, vermelho=2 -- mesma convencao de stats_model._cards_points e
    da graduacao real do resultado."""
    amarelo = jogo.get(f"{lado}_yellow_cards")
    vermelho = jogo.get(f"{lado}_red_cards")
    if amarelo is None or vermelho is None:
        return None
    return float(amarelo) + 2.0 * float(vermelho)


def _valor_do_lado(jogo, familia, lado):
    """Contagem daquela familia para `lado` ('home'/'away'), ou None quando a
    folha nao cobre."""
    if not stats_model._tem_folha_da_familia(jogo, familia):
        return None
    if familia == "cards":
        return _cartao_pontos(jogo, lado)
    campo = FAMILIAS[familia][0 if lado == "home" else 1]
    valor = jogo.get(campo)
    return None if valor is None else float(valor)


def carregar_jogos(cur):
    """Todos os jogos FT com folha, mais novos primeiro nao importa -- a ordem
    e' resolvida em memoria."""
    cur.execute("""
        SELECT match_date, league_id, season,
               home_team_id, away_team_id,
               home_goals, away_goals,
               home_corners, away_corners,
               home_total_shots, away_total_shots,
               home_shots_on, away_shots_on,
               home_fouls, away_fouls,
               home_goalkeeper_saves, away_goalkeeper_saves,
               home_yellow_cards, away_yellow_cards,
               home_red_cards, away_red_cards
        FROM match_statistics
        WHERE status = 'FT'
        ORDER BY match_date
    """)
    colunas = [d[0] for d in cur.description]
    return [dict(zip(colunas, linha)) for linha in cur.fetchall()]


def achar_confrontos_de_volta(jogos, janela_dias):
    """Pares (ida, volta) de mata-mata, provados pela inversao de mando.

    So' competicao que NAO e' pontos corridos: em liga, o returno tambem
    inverte o mando, e ali a inversao nao significa agregado nenhum. E' o mesmo
    recorte que competitive_pressure.vale_para_a_competicao faz do outro lado.
    """
    por_par = defaultdict(list)
    for j in jogos:
        perfil = cp.get_profile(j["league_id"])
        if perfil.type == "LEAGUE":
            continue
        par = tuple(sorted((j["home_team_id"], j["away_team_id"])))
        por_par[(par, j["league_id"], j["season"])].append(j)

    confrontos = []
    for encontros in por_par.values():
        encontros.sort(key=lambda j: j["match_date"])
        # Um jogo pertence a NO MAXIMO um confronto: ao fechar um par, os dois
        # jogos sao consumidos e o laco pula pra depois deles.
        #
        # Sem isso, tres encontros do mesmo par de times -- fase de grupos
        # ida-e-volta e depois um mata-mata, que acontece em Libertadores e
        # Sul-Americana -- formariam (A,B) e (B,C), com B entrando como volta
        # de um e ida do outro. A mesma partida contaria duas vezes e o
        # erro-padrao sairia estreito de mentira, que numa medicao de amostra
        # curta e' o erro que mais engana: a tabela pareceria mais confiavel
        # justamente onde ha' menos evidencia.
        i = 0
        while i < len(encontros) - 1:
            ida, volta = encontros[i], encontros[i + 1]
            # Mando invertido: e' isto que prova ida-e-volta.
            if ida["home_team_id"] != volta["away_team_id"]:
                i += 1
                continue
            dias = (volta["match_date"] - ida["match_date"]).days
            if not (0 < dias <= janela_dias):
                i += 1
                continue
            confrontos.append((ida, volta))
            i += 2
    return confrontos


def papeis_na_volta(ida):
    """{team_id: papel} pelo placar da ida, agregado simples.

    Gol fora de casa NAO entra: a medicao original nao usou, e o regulamento
    varia por competicao (competition_rules_store). Misturar as duas coisas
    numa amostra deste tamanho mediria o regulamento, nao o agregado.
    """
    if ida["home_goals"] is None or ida["away_goals"] is None:
        return None
    if ida["home_goals"] > ida["away_goals"]:
        return {ida["home_team_id"]: "na_frente", ida["away_team_id"]: "atras"}
    if ida["home_goals"] < ida["away_goals"]:
        return {ida["home_team_id"]: "atras", ida["away_team_id"]: "na_frente"}
    return {ida["home_team_id"]: "empatado", ida["away_team_id"]: "empatado"}


def media_propria(jogos, team_id, familia, lado, antes_de):
    """Media do time naquela familia, NO MESMO MANDO, so' com jogos anteriores.

    `lado` e' o mando que o time tem no jogo que esta' sendo medido: um time
    que joga a volta em casa e' comparado com as proprias partidas em casa.
    """
    valores = []
    for j in jogos:
        if j["match_date"] >= antes_de:
            continue
        if lado == "home" and j["home_team_id"] != team_id:
            continue
        if lado == "away" and j["away_team_id"] != team_id:
            continue
        v = _valor_do_lado(j, familia, lado)
        if v is not None:
            valores.append(v)
    if len(valores) < MIN_JOGOS_PROPRIOS:
        return None, len(valores)
    return sum(valores) / len(valores), len(valores)


def medir(jogos, confrontos):
    """{familia: {papel: [deslocamentos]}} e o mesmo para o total do jogo."""
    por_lado = defaultdict(lambda: defaultdict(list))
    por_total = defaultdict(list)

    for ida, volta in confrontos:
        papeis = papeis_na_volta(ida)
        if not papeis:
            continue
        for familia in FAMILIAS:
            deslocamentos_do_jogo = []
            for lado in ("home", "away"):
                team_id = volta[f"{lado}_team_id"]
                papel = papeis.get(team_id)
                if papel is None:
                    continue
                atual = _valor_do_lado(volta, familia, lado)
                if atual is None:
                    continue
                base, _ = media_propria(
                    jogos, team_id, familia, lado, volta["match_date"])
                if base is None:
                    continue
                delta = atual - base
                por_lado[familia][papel].append(delta)
                deslocamentos_do_jogo.append(delta)
            # O total do jogo so' vale quando os DOIS lados entraram: a
            # pergunta ali e' se os efeitos se cancelam, e meia soma nao
            # responde isso.
            if len(deslocamentos_do_jogo) == 2:
                por_total[familia].append(sum(deslocamentos_do_jogo))
    return por_lado, por_total


def resumo(valores):
    """(media, erro_padrao, n). Erro-padrao amostral: desvio/raiz(n)."""
    n = len(valores)
    if n == 0:
        return None, None, 0
    media = sum(valores) / n
    if n == 1:
        return media, None, 1
    var = sum((v - media) ** 2 for v in valores) / (n - 1)
    return media, (var ** 0.5) / (n ** 0.5), n


def _linha(rotulo, valores):
    media, ep, n = resumo(valores)
    if n == 0:
        return f"  {rotulo:<18} {'sem amostra':>28}"
    if ep is None or ep == 0:
        return f"  {rotulo:<18} {media:+6.2f}  (ep    n/a)  n={n:<3}"
    sigma = abs(media) / ep
    marca = "  <-- sustenta" if sigma >= 2 else ""
    return (f"  {rotulo:<18} {media:+6.2f}  (ep {ep:5.2f})  n={n:<3} "
            f"sigma={sigma:4.1f}{marca}")


def imprimir(por_lado, por_total, confrontos):
    print()
    print("=" * 78)
    print("EFEITO DO AGREGADO POR LADO -- remedicao de tie_effect._MEDIDO")
    print("=" * 78)
    print(f"Confrontos de volta encontrados: {len(confrontos)}")
    print("(a medicao de 2026-08-19 tinha 11, com 4 nas celulas assimetricas)")
    print()
    print("Um efeito so' se sustenta com sigma >= 2 -- foi esse criterio que")
    print("deixou cards, saves e shots_on_target fora da tabela do modulo.")

    for familia in FAMILIAS:
        print()
        print(f"{familia}")
        for papel in ("atras", "na_frente", "empatado"):
            _valores = por_lado[familia][papel]
            print(_linha(papel, _valores))
        print(_linha("TOTAL do jogo", por_total[familia]))

    print()
    print("-" * 78)
    print("COMO USAR ESTE RESULTADO")
    print("-" * 78)
    print("Se uma celula ganhou amostra e MANTEVE o sinal, o desconto de")
    print("FATOR_DE_EXTRAPOLACAO (hoje 0.50) pode subir -- ele existe porque a")
    print("medicao saiu de 11 confrontos de tres competicoes so'.")
    print("Se uma celula mudou de sinal ou caiu abaixo de sigma 2, ela sai da")
    print("tabela: e' o mesmo criterio que ja' manteve tres familias fora.")
    print("Nenhuma constante deve ser editada sem esta saida em maos.")
    print()


def run():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--janela", type=int, default=JANELA_PADRAO,
                    help=f"dias entre ida e volta (padrao {JANELA_PADRAO})")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()
    try:
        jogos = carregar_jogos(cur)
    finally:
        cur.close()
        conn.close()

    print(f"[MEDICAO] {len(jogos)} jogos FT carregados.")
    confrontos = achar_confrontos_de_volta(jogos, args.janela)
    print(f"[MEDICAO] {len(confrontos)} confrontos de ida-e-volta identificados "
          f"(janela de {args.janela} dias).")
    if not confrontos:
        print("[MEDICAO] Nenhum confronto: nada a medir.")
        return

    por_lado, por_total = medir(jogos, confrontos)
    imprimir(por_lado, por_total, confrontos)


if __name__ == "__main__":
    run()
