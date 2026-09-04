"""
funil_motor_ao_vivo.py · onde as partidas morrem no motor AO VIVO, por camada.

SOMENTE LEITURA. Nenhum INSERT/UPDATE/DELETE -- pode rodar contra PROD sem
efeito colateral.

Uso:
  DB_ENV=prod python src/scripts/funil_motor_ao_vivo.py
  DB_ENV=prod python src/scripts/funil_motor_ao_vivo.py --dias 3

O QUE ELE RESPONDE
------------------
"O motor ao vivo nao esta' gerando nada" tem sete respostas possiveis, uma por
camada, e elas exigem acoes opostas: interruptor desligado nao se conserta
mexendo em limiar, e limiar apertado nao se conserta ligando interruptor.
Este script diz em QUAL camada cada partida morreu, contando.

A fonte e' `engine_decisions` com `pipeline='LIVE_ENGINE'`, gravada pelo
`live_pipeline` desde 24/08/2026. Antes disso nao ha o que ler: o unico log do
motor ao vivo era o stdout da ULTIMA rodada, em memoria no processo do site.

POR QUE ISTO E' UM SCRIPT E NAO UMA CONSULTA SOLTA
--------------------------------------------------
As duas perguntas que importam moram em niveis diferentes da mesma tabela. O
funil de PARTIDAS esta' nas linhas `descartado`/`avaliado`; o custo de API e o
funil de RODADAS estao dentro do JSONB de `context` nas linhas `sem_pick`.
Responder "vale a pena mexer no limiar X" sem cruzar os dois leva a conclusao
errada -- e' possivel um gate parecer o vilao quando na verdade quase nenhuma
partida chega ate' ele.

O QUE ELE NAO RESPONDE
----------------------
Nada sobre QUALIDADE de pick. Isso e' `picks_live`, e enquanto o motor rodar em
dry run essa tabela fica vazia por construcao. Este script mede mecanica: onde
para, quanto custa, qual gate corta mais.
"""
import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db_utils import get_connection  # noqa: E402

PIPELINE = "LIVE_ENGINE"


def _ctx(linha) -> dict:
    bruto = linha[5]
    if isinstance(bruto, str):
        try:
            return json.loads(bruto)
        except ValueError:
            return {}
    return bruto or {}


def _cabecalho(texto: str) -> None:
    print("\n" + texto)
    print("-" * len(texto))


def rodadas(linhas) -> None:
    """Camadas 1 e 2: a rodada aconteceu, e chegou a olhar alguma partida?"""
    sem_pick = [l for l in linhas if l[3] == "sem_pick"]
    _cabecalho(f"RODADAS SEM PICK · {len(sem_pick)}")
    if not sem_pick:
        print("  nenhuma. Ou o motor nao rodou, ou toda rodada gerou pick.")
        return

    motivos = Counter(l[4] for l in sem_pick)
    for motivo, n in motivos.most_common():
        print(f"  {n:>5}  {motivo}")

    ctxs = [_ctx(l) for l in sem_pick]
    encontradas = sum(c.get("fixtures_encontradas") or 0 for c in ctxs)
    elegiveis = sum(c.get("fixtures_elegiveis") or 0 for c in ctxs)
    radar = sum(c.get("fixtures_no_radar") or 0 for c in ctxs)
    requisicoes = sum(c.get("requisicoes") or 0 for c in ctxs)
    secas = sum(1 for c in ctxs if not c.get("fixtures_elegiveis"))

    print(f"\n  fixtures ao vivo vistas : {encontradas}")
    print(f"  elegiveis               : {elegiveis}")
    print(f"  no radar (voltam depois): {radar}")
    # A rodada sem elegivel custa exatamente 1 requisicao (a varredura). E' a
    # conta que diz se o intervalo do laco esta' curto demais pro calendario.
    print(f"  rodadas sem elegivel    : {secas} de {len(sem_pick)}")
    print(f"\n  requisicoes de API      : {requisicoes}"
          f"   (media {requisicoes / len(sem_pick):.1f} por rodada)")

    descartes = Counter()
    for c in ctxs:
        for categoria, n in (c.get("descartes") or {}).items():
            descartes[categoria] += n
    if descartes:
        print("\n  partidas descartadas na SELECAO (custo zero de API):")
        for categoria, n in descartes.most_common():
            print(f"    {n:>6}  {categoria}")


def partidas(linhas) -> None:
    """Camadas 3 e 4: a partida foi analisada, e chegou a ver preco?"""
    descartadas = [l for l in linhas if l[3] == "descartado"]
    _cabecalho(f"PARTIDAS QUE MORRERAM ANTES DA AVALIACAO · {len(descartadas)}")
    if not descartadas:
        print("  nenhuma.")
        return
    for motivo, n in Counter(l[4] for l in descartadas).most_common():
        print(f"  {n:>5}  {motivo}")

    minutos = [(_ctx(l).get("minuto") or 0) for l in descartadas]
    if minutos:
        print(f"\n  minuto medio da morte: {sum(minutos) / len(minutos):.0f}'")


def candidatos(linhas) -> None:
    """Camadas 5 e 6: com a odd na mao, qual gate reprovou."""
    avaliadas = [l for l in linhas if l[3] == "avaliado"]
    _cabecalho(f"PARTIDAS AVALIADAS COM ODD · {len(avaliadas)}")
    if not avaliadas:
        print("  nenhuma. Nenhuma partida passou da triagem · o freio de API")
        print("  esta' cortando tudo antes de o preco ser consultado.")
        return

    desfechos = Counter(_ctx(l).get("desfecho") for l in avaliadas)
    for desfecho, n in desfechos.most_common():
        print(f"  {n:>5}  {desfecho}")

    total_cand = 0
    aprovados = 0
    gates = Counter()
    for l in avaliadas:
        for c in (l[6] or []):
            total_cand += 1
            if c.get("eligible"):
                aprovados += 1
            # TODOS os motivos, nao so' o primeiro: `avaliar()` nao faz
            # short-circuit de proposito, e um candidato que cai por EV *e* por
            # convergencia conta nos dois -- e' o que diz qual limiar mexer.
            for motivo in (c.get("motivos_reprovacao") or []):
                gates[motivo] += 1

    print(f"\n  mercados avaliados: {total_cand}   aprovados: {aprovados}")
    if gates:
        print("\n  gates que mais reprovaram:")
        for motivo, n in gates.most_common(12):
            print(f"    {n:>6}  {motivo}")


def picks_que_nao_foram_gravados(linhas) -> None:
    """A pergunta que so' o log responde enquanto o motor estiver em dry run."""
    teria = []
    for l in linhas:
        if l[3] != "avaliado":
            continue
        ctx = _ctx(l)
        if not ctx.get("dry_run"):
            continue
        for c in (l[6] or []):
            if c.get("is_best_pick"):
                teria.append((l[1], ctx.get("minuto"), c))

    _cabecalho(f"PICKS QUE O DRY RUN IMPEDIU DE GRAVAR · {len(teria)}")
    if not teria:
        print("  nenhum. Em dry run isto significa que o motor nao achou nada ·")
        print("  desligar o dry run, sozinho, nao faria pick aparecer.")
        return
    print("  (o motor aprovou estes e nao gravou porque dry_run estava ligado)")
    for quando, minuto, c in teria[:30]:
        print(f"    {quando:%d/%m %H:%M}  {minuto}'  {c.get('market_type')} "
              f"{c.get('line')} @ {c.get('odd')}  "
              f"p={(c.get('probability') or 0) * 100:.0f}% "
              f"ev={(c.get('ev') or 0) * 100:+.1f}%")
    if len(teria) > 30:
        print(f"    ... e mais {len(teria) - 30}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Funil do motor ao vivo, por camada (somente leitura).")
    parser.add_argument("--dias", type=int, default=1,
                        help="janela em dias (padrao: 1)")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT id, created_at, pipeline, status, reason, context, candidates
           FROM engine_decisions
           WHERE pipeline = %s AND created_at >= NOW() - (%s || ' days')::interval
           ORDER BY id""", (PIPELINE, args.dias))
    linhas = cur.fetchall()
    cur.close()
    conn.close()

    print("=" * 62)
    print(f"FUNIL DO MOTOR AO VIVO · ultimos {args.dias} dia(s) · "
          f"{len(linhas)} linha(s)")
    print("=" * 62)
    if not linhas:
        print("\nSem registro. Ou o motor nao rodou na janela, ou esta' numa")
        print("versao anterior a 24/08/2026, que nao gravava decisao nenhuma.")
        return

    rodadas(linhas)
    partidas(linhas)
    candidatos(linhas)
    picks_que_nao_foram_gravados(linhas)
    print()


if __name__ == "__main__":
    main()
