"""
medir_minutos_do_jogador.py · TODA participacao do jogador, com peso pelos
minutos, contra o historico atual (so' atuacoes de 60+ minutos).

SOMENTE LEITURA. Nenhum INSERT/UPDATE/DELETE -- roda contra PROD sem efeito.

Uso:
  DB_ENV=prod python src/scripts/medir_minutos_do_jogador.py
  DB_ENV=prod python src/scripts/medir_minutos_do_jogador.py --metodo shots_on

O PEDIDO (11/10/2026, usuario)
------------------------------
"Todas as participacoes dele em jogo o motor tem que considerar; se ele entrou
5 minutos, o peso daquela partida tem que ser baixo." Hoje o
`player_history.MIN_MINUTOS = 60` joga fora, alem do reserva, o TITULAR QUE
SAIU CEDO (lesao, expulsao, troca no intervalo) -- justamente os jogos em que
ele produziu pouco. A suspeita e' que isso empurra a media pra cima.

OS DOIS ESTIMADORES, NA MESMA ATUACAO ALVO
------------------------------------------
Alvo: cada atuacao de TITULAR (o motor so' aposta em titular provavel), com o
historico das atuacoes ANTERIORES da mesma liga e temporada. Nao olha o futuro.

  atual    -- `count_model.media_ponderada` das atuacoes de 60+ minutos, como
              o motor faz hoje.
  minutos  -- toda atuacao com minuto em campo entra. Taxa por minuto com o
              peso de recencia do motor:  soma(peso * valor) / soma(peso *
              minutos), vezes os minutos que ele costuma jogar quando COMECA
              (media das ultimas titularidades). Uma entrada de 5 minutos soma
              5 minutos de exposicao: pesa pouco, como pedido.

Os dois viram probabilidade pela MESMA funcao do motor
(`probability_model.prob_over`, com o phi medido), pras linhas 0.5/1.5/2.5.

O QUE ELE IMPRIME, POR METODO
-----------------------------
  · vies (media prevista - media real) e erro medio absoluto;
  · Brier de P(X >= N) por linha -- menor e' melhor;
  · o mesmo recortado em "titular que saiu antes dos 60'", onde a diferenca
    deve aparecer;
  · cobertura: quantas atuacoes so' o estimador por minutos consegue avaliar
    (o atual nao alcanca o piso de amostra).

Nao ha' veredito impresso de proposito: a decisao de ligar e' do usuario,
olhando a tabela (regra da casa: sinal so' entra no motor depois de medido).
"""
import argparse
import os
import sys
from collections import defaultdict

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from services.pick_engine import probability_model as pm  # noqa: E402
from services.player_stats_engine import count_model  # noqa: E402
from services.player_stats_engine import methods as cat  # noqa: E402
from services.player_stats_engine import player_history  # noqa: E402

DIAS = 240
LINHAS = (0.5, 1.5, 2.5)
#: Quantas titularidades anteriores dizem "quantos minutos ele joga quando
#: comeca". Dez cobre a fase atual sem arrastar outra temporada.
TITULARIDADES_PRO_REGIME = 10
PESO_RECENTE = 1.6


def _pesos(n: int) -> list:
    """Mesmo decaimento linear de `count_model.media_ponderada` (recente primeiro)."""
    if n == 1:
        return [1.0]
    return [PESO_RECENTE - (PESO_RECENTE - 1.0) * (i / (n - 1)) for i in range(n)]


def previsao_atual(historico: list, min_atuacoes: int) -> float | None:
    """`historico` do mais recente pro mais antigo. Como o motor: so' 60+."""
    serie = [float(a["valor"]) for a in historico
             if (a.get("minutes") or 0) >= player_history.MIN_MINUTOS]
    serie = serie[:player_history.LIMITE_ATUACOES]
    if len(serie) < min_atuacoes:
        return None
    return count_model.media_ponderada(serie)


def minutos_de_titular(historico: list) -> float | None:
    mins = [float(a["minutes"]) for a in historico
            if not a.get("is_substitute") and (a.get("minutes") or 0) > 0]
    mins = mins[:TITULARIDADES_PRO_REGIME]
    return sum(mins) / len(mins) if mins else None


def previsao_por_minutos(historico: list, min_atuacoes: int) -> float | None:
    """Toda atuacao com minuto em campo; cada uma pesa pelos minutos."""
    usadas = [a for a in historico if (a.get("minutes") or 0) > 0]
    usadas = usadas[:player_history.LIMITE_ATUACOES]
    if len(usadas) < min_atuacoes:
        return None
    regime = minutos_de_titular(historico)
    if not regime:
        return None
    pesos = _pesos(len(usadas))
    exposicao = sum(p * float(a["minutes"]) for p, a in zip(pesos, usadas))
    if exposicao <= 0:
        return None
    taxa = sum(p * float(a["valor"]) for p, a in zip(pesos, usadas)) / exposicao
    return round(taxa * regime, 3)


def caminhar(folhas: list, metodo: cat.Metodo) -> list:
    """Um registro por atuacao alvo de titular. Sem olhar o futuro.

    `folhas` em ordem cronologica, com player_id/league_id/season/minutes/
    is_substitute/valor.
    """
    por_serie: dict = defaultdict(list)
    for f in folhas:
        por_serie[(f["player_id"], f["league_id"], f["season"])].append(f)

    registros = []
    for serie in por_serie.values():
        anteriores: list = []
        for atual in serie:
            if not atual.get("is_substitute") and (atual.get("minutes") or 0) > 0:
                historico = list(reversed(anteriores))
                registros.append({
                    "real": float(atual["valor"]),
                    "minutos": int(atual["minutes"]),
                    "atual": previsao_atual(historico, metodo.min_atuacoes),
                    "minutos_est": previsao_por_minutos(historico, metodo.min_atuacoes),
                })
            anteriores.append(atual)
    return registros


def _brier(pares: list) -> float | None:
    return round(sum((p - y) ** 2 for p, y in pares) / len(pares), 4) if pares else None


def resumo(registros: list, phi: float) -> dict:
    """As duas previsoes comparadas SO' onde as duas existem (mesma amostra)."""
    ambos = [r for r in registros if r["atual"] is not None and r["minutos_est"] is not None]
    saida = {"n": len(ambos),
             "so_minutos": sum(1 for r in registros
                               if r["atual"] is None and r["minutos_est"] is not None)}
    if not ambos:
        return saida
    real = sum(r["real"] for r in ambos) / len(ambos)
    saida["media_real"] = round(real, 3)
    for nome in ("atual", "minutos_est"):
        prev = [r[nome] for r in ambos]
        saida[nome] = {
            "vies": round(sum(prev) / len(prev) - real, 3),
            "erro_medio": round(sum(abs(r[nome] - r["real"]) for r in ambos) / len(ambos), 3),
            "brier": {},
        }
        for linha in LINHAS:
            pares = []
            for r in ambos:
                p = pm.prob_over(linha, r[nome], phi) if r[nome] and r[nome] > 0 else 0.0
                pares.append((float(p or 0.0), 1.0 if r["real"] > linha else 0.0))
            saida[nome]["brier"][linha] = _brier(pares)
    return saida


def _imprimir(titulo: str, s: dict) -> None:
    print(f"\n  {titulo}: {s['n']} atuacoes de titular com as duas previsoes"
          + (f" (media real {s['media_real']})" if s.get("media_real") is not None else ""))
    if not s.get("media_real") and s.get("media_real") != 0:
        return
    print(f"    {'':14}{'vies':>8}{'erro medio':>12}"
          + "".join(f"{'Brier ' + format(l, 'g') + '+':>12}" for l in LINHAS))
    for nome, rotulo in (("atual", "60+ (hoje)"), ("minutos_est", "por minutos")):
        m = s[nome]
        print(f"    {rotulo:14}{m['vies']:>8}{m['erro_medio']:>12}"
              + "".join(f"{(m['brier'][l] if m['brier'][l] is not None else '-'):>12}" for l in LINHAS))


def _folhas(cur, metodo: cat.Metodo, dias: int) -> list:
    from utils.db_utils import linhas_dict
    cur.execute(f"""
        SELECT player_id, league_id, season, match_date, minutes, is_substitute,
               {metodo.coluna} AS valor
          FROM player_match_stats
         WHERE {metodo.coluna} IS NOT NULL
           AND COALESCE(minutes, 0) > 0
           AND match_date >= CURRENT_DATE - %s
      ORDER BY player_id, league_id, season, match_date
    """, (dias,))
    return linhas_dict(cur)


def main() -> None:
    from utils.db_utils import get_connection

    ap = argparse.ArgumentParser()
    ap.add_argument("--metodo", help="slug de um metodo so' (ex.: shots_on)")
    ap.add_argument("--dias", type=int, default=DIAS)
    args = ap.parse_args()

    metodos = [cat.de(args.metodo)] if args.metodo else list(cat.METODOS)
    conn = get_connection()
    cur = conn.cursor()
    try:
        print(f"Minutos do jogador · {args.dias} dias · alvo: atuacoes de titular")
        print("Brier menor e' melhor. Vies positivo = previsao acima do real.")
        for metodo in metodos:
            if metodo is None:
                continue
            phi = float(count_model.medir_dispersao(cur, metodo).get("phi") or metodo.phi_congelado)
            registros = caminhar(_folhas(cur, metodo, args.dias), metodo)
            print(f"\n== {metodo.label} ({metodo.slug}) · phi {phi:.2f} ==")
            geral = resumo(registros, phi)
            _imprimir("Todas", geral)
            _imprimir("Titular que saiu antes dos 60'",
                      resumo([r for r in registros if r["minutos"] < 60], phi))
            print(f"    So' o estimador por minutos alcanca o piso de amostra em "
                  f"{geral['so_minutos']} atuacoes a mais.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
