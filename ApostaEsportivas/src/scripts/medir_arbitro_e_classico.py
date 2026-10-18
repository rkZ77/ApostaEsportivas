"""
medir_arbitro_e_classico.py · o arbitro e o classico mudam o cartao ALEM do
que os dois times ja' dizem? (18/10/2026, pedido do usuario: "vai que e'
classico e o arbitro e' rigoroso, o motor precisa saber disso").

SOMENTE LEITURA. Pode rodar contra PROD.

Uso:
  DB_ENV=prod python src/scripts/medir_arbitro_e_classico.py

O QUE MEDE
----------
Pra cada jogo encerrado com folha, so' com o que se sabia ANTES dele:
  esperado   media de pontos de cartao (amarelo + 2x vermelho) dos jogos
             anteriores dos dois times
  perfil     o arbitro contra a media da liga (arbitro_no_contexto: rigoroso,
             leniente, na media) com todas as grafias da mesma pessoa
  confronto  pontos nos confrontos diretos anteriores contra o esperado
             (rivalry_model: rivalidade_alta, confronto_frio, normal)
e olha o RESIDUO: cartao real menos o esperado pelos times. Se o perfil do
arbitro separa o residuo (rigoroso acima, leniente abaixo), ele diz algo que os
times nao dizem. Se o classico com arbitro rigoroso fica acima dos dois
sozinhos, a combinacao importa.

Descoberta x confirmacao: a amostra e' cortada na data do meio. O veredito so'
diz "separa" quando as DUAS metades apontam pro mesmo lado.

O que este script NAO faz: ligar nada. Hoje o arbitro no contexto vai so' pro
dossie da IA (services/pick_engine/arbitro_no_contexto.py); a decisao de levar
pra probabilidade e' do usuario, com estes numeros na mao.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYTHONUNBUFFERED", "1")

from utils.db_utils import get_connection
from utils.arbitro import chave_do_arbitro, chaves_equivalentes
from services.pick_engine import arbitro_no_contexto as ac
from services.pick_engine.rivalry_model import EXCESSO_RELEVANTE, MIN_CONFRONTOS

MIN_JOGOS_TIME = 5
MIN_JOGOS_LIGA = 30
TEMPORADA_MINIMA = 2025
#: Residuo medio a partir do qual o grupo "separa" (meio ponto de cartao).
SEPARA = 0.4
MIN_N_VEREDITO = 60


def pessoa_de_cada_chave(chaves: set) -> dict:
    """{chave: pessoa} juntando as grafias. Agrupa por letra inicial, que e' o
    universo de chaves_equivalentes (nome curto, longo e abreviacao comecam
    igual) · sem isso seria n^2 sobre mil grafias."""
    por_letra = defaultdict(set)
    for c in chaves:
        por_letra[c[:1]].add(c)
    pessoa = {}
    for grupo in por_letra.values():
        for c in sorted(grupo):
            if c in pessoa:
                continue
            for m in chaves_equivalentes(c, grupo):
                pessoa.setdefault(m, c)
    return pessoa


def carregar(cur):
    cur.execute("""
        SELECT fixture_id, match_date, league_id, home_team_id, away_team_id, referee,
               total_yellow_cards + 2 * COALESCE(total_red_cards, 0) AS pontos
          FROM match_statistics
         WHERE status IN ('FT', 'AET', 'PEN') AND season >= %s
           AND total_yellow_cards IS NOT NULL
         ORDER BY match_date, fixture_id
    """, (TEMPORADA_MINIMA,))
    return cur.fetchall()


def medir(jogos):
    chaves = {chave_do_arbitro(j[5]) for j in jogos if j[5]}
    chaves.discard(None)
    pessoa = pessoa_de_cada_chave(chaves)

    por_time = defaultdict(list)
    por_liga = defaultdict(list)
    por_arbitro = defaultdict(list)
    por_par = defaultdict(list)
    linhas = []
    for fid, data, liga, casa, fora, referee, pontos in jogos:
        pontos = float(pontos)
        quem = pessoa.get(chave_do_arbitro(referee)) if referee else None
        hc, hf, hl = por_time[casa], por_time[fora], por_liga[liga]
        if len(hc) >= MIN_JOGOS_TIME and len(hf) >= MIN_JOGOS_TIME and len(hl) >= MIN_JOGOS_LIGA:
            esperado = (sum(hc) / len(hc) + sum(hf) / len(hf)) / 2
            media_liga = sum(hl) / len(hl)
            ha = por_arbitro.get(quem) or []
            perfil = ac.perfil_do_arbitro(len(ha), sum(ha) / len(ha) if ha else None, media_liga)
            h2h = por_par[frozenset((casa, fora))]
            if len(h2h) >= MIN_CONFRONTOS:
                excesso = sum(h2h) / len(h2h) - esperado
                confronto = ("rivalidade_alta" if excesso >= EXCESSO_RELEVANTE
                             else "confronto_frio" if excesso <= -EXCESSO_RELEVANTE else "normal")
            else:
                confronto = "desconhecido"
            linhas.append({"data": data, "perfil": perfil or "sem_arbitro", "confronto": confronto,
                           "temperatura": ac.temperatura(perfil, confronto) or "sem_leitura",
                           "real": pontos, "esperado": esperado, "residuo": pontos - esperado})
        hc.append(pontos)
        hf.append(pontos)
        hl.append(pontos)
        if quem:
            por_arbitro[quem].append(pontos)
        por_par[frozenset((casa, fora))].append(pontos)
    return linhas


def tabela(linhas, campo):
    grupos = defaultdict(list)
    for l in linhas:
        grupos[l[campo]].append(l)
    saida = {}
    for nome, ls in grupos.items():
        n = len(ls)
        saida[nome] = {
            "n": n,
            "real": sum(l["real"] for l in ls) / n,
            "esperado": sum(l["esperado"] for l in ls) / n,
            "residuo": sum(l["residuo"] for l in ls) / n,
            "over_4_5": 100 * sum(1 for l in ls if l["real"] > 4.5) / n,
        }
    return saida


def imprimir(titulo, t):
    print(f"\n{titulo}")
    print(f"  {'grupo':<44}{'n':>6}{'real':>8}{'esper.':>8}{'residuo':>9}{'>4,5':>7}")
    for nome, v in sorted(t.items(), key=lambda kv: -kv[1]["n"]):
        print(f"  {nome:<44}{v['n']:>6}{v['real']:>8.2f}{v['esperado']:>8.2f}"
              f"{v['residuo']:>+9.2f}{v['over_4_5']:>6.0f}%")


def veredito(t1, t2, grupo, lado):
    a, b = t1.get(grupo), t2.get(grupo)
    if not a or not b or a["n"] < MIN_N_VEREDITO or b["n"] < MIN_N_VEREDITO:
        return f"{grupo}: amostra curta pra veredito"
    ok = all((v["residuo"] >= SEPARA) if lado > 0 else (v["residuo"] <= -SEPARA) for v in (a, b))
    return (f"{grupo}: {'SEPARA' if ok else 'nao separa'} "
            f"(descoberta {a['residuo']:+.2f} n={a['n']}, confirmacao {b['residuo']:+.2f} n={b['n']})")


def main():
    conn = get_connection()
    cur = conn.cursor()
    try:
        jogos = carregar(cur)
    finally:
        cur.close()
        conn.close()
    linhas = medir(jogos)
    print(f"Jogos com folha desde {TEMPORADA_MINIMA}: {len(jogos)} · com historico suficiente: {len(linhas)}")
    if not linhas:
        return
    meio = sorted(l["data"] for l in linhas)[len(linhas) // 2]
    desc = [l for l in linhas if l["data"] < meio]
    conf = [l for l in linhas if l["data"] >= meio]
    for campo, titulo in (("perfil", "PERFIL DO ARBITRO (contra a media da liga)"),
                          ("confronto", "CONFRONTO DIRETO (cartoes nos encontros anteriores)"),
                          ("temperatura", "TEMPERATURA (arbitro + confronto)")):
        imprimir(f"{titulo} · tudo", tabela(linhas, campo))
    t1, t2 = tabela(desc, "perfil"), tabela(conf, "perfil")
    t3, t4 = tabela(desc, "temperatura"), tabela(conf, "temperatura")
    print("\nVEREDITO (as duas metades no mesmo lado, residuo de pelo menos "
          f"{SEPARA} ponto, n >= {MIN_N_VEREDITO} em cada)")
    print("  " + veredito(t1, t2, "rigoroso", +1))
    print("  " + veredito(t1, t2, "leniente", -1))
    print("  " + veredito(t3, t4, "confronto_quente_com_arbitro_rigoroso", +1))
    print("  " + veredito(t3, t4, "confronto_quente", +1))


if __name__ == "__main__":
    main()
