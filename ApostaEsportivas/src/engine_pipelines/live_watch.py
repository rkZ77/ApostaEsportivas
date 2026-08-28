"""Acompanhamento ao vivo: rodadas sucessivas do Motor Live, SO' EM DEV.

POR QUE ISTO EXISTE
-------------------
`live_pipeline.py` faz UMA passada e termina, de proposito. Mas uma passada
sozinha nao e' o motor funcionando: /fixtures/statistics devolve so' acumulado,
entao "escanteios nos ultimos 10 minutos" nao existe no feed -- existe na
diferenca entre duas leituras nossas (ver rhythm_model, docstring do modulo).
Na primeira rodada sobre uma partida o motor nao tem janela nem tendencia, e
nao finge ter. Sao a segunda e a terceira que fazem o modelo de ritmo valer
alguma coisa.

Este arquivo e' o supervisor que dispara essas rodadas dentro da janela dos
jogos. Ele NAO e' um scheduler: nao se instala, nao sobe com o servico, nao
sobrevive ao terminal. E' um processo que voce comeca quando os jogos comecam e
que para sozinho quando a janela fecha, o orcamento acaba ou nao ha mais jogo.
O scheduler do projeto foi deletado em 2026-08-01 por queimar cota da API, e a
diferenca que importa e' essa: aqui existe um teto de requisicoes declarado na
linha de comando e um humano que viu o processo comecar.

TRAVA DE AMBIENTE (REMOVIDA EM 2026-08-28)
------------------------------------------
O modulo CRAVAVA `DB_ENV=dev` antes de qualquer import que abrisse conexao, e
recusava a valvula `LIVE_ENGINE_ALLOW_PROD` com um argumento que continua bom:
rodada unica com a valvula aberta e' uma decisao, um laco com a valvula aberta
e' um acidente que se repete a cada 8 minutos.

O que mudou nao foi o argumento, foi o alvo. O Live virou produto publicado, as
variaveis dele sairam do Railway, e nao ha' mais um banco de DEV pra onde
cravar -- um laco preso em DEV hoje nao protege producao, so' escreve pick que
ninguem le'.

O QUE SEGURA O ACIDENTE NO LUGAR DA TRAVA, e por que ainda e' suficiente pra um
laco: o `--orcamento` e' um teto de requisicoes da SESSAO inteira, declarado na
linha de comando; `--ate` e' um horario de parada; e `--ocioso-para` desliga
sozinho depois de N rodadas sem jogo elegivel. O laco morre por conta propria
de tres jeitos diferentes. O que a trava impedia era a rodada 30 alcancar o
banco errado -- hoje so' existe um banco, o do ambiente de quem chamou.

ORCAMENTO
---------
Duas contas independentes:

    LIVE_MAX_API_REQUESTS_PER_RUN   teto POR rodada  (live_feed.LiveFeed)
    --orcamento                     teto DA SESSAO   (este arquivo)

A rodada para na primeira; a sessao inteira para na segunda. Rodada sem jogo
elegivel custa exatamente 1 requisicao (a varredura /fixtures?live=all), e por
isso a espera ociosa e' mais longa que a espera util -- ver `--intervalo` e
`--intervalo-ocioso`.

USO
---
    python engine_pipelines/live_watch.py --ate 20:30
    python engine_pipelines/live_watch.py --intervalo 8 --orcamento 120
    python engine_pipelines/live_watch.py --dry-run     # nao grava pick
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# Log de processo longo tem que aparecer ENQUANTO acontece. Quando a saida vai
# pra arquivo ou pipe (que e' como um acompanhamento de 3 horas costuma ser
# rodado), o Python segura o stdout em bloco e o log so' aparece no fim --
# acompanhar jogo ao vivo com log que chega depois do apito final nao serve.
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:  # pragma: no cover - Python antigo
    pass

TZ_BR = ZoneInfo("America/Sao_Paulo")


def _cravar_dev() -> None:
    """NAO CRAVA MAIS NADA (2026-08-28) · ver o topo do modulo.

    A funcao e a chamada ficam porque a razao original merece ser encontrada
    aqui, e nao num `git log`: `utils/db_utils.get_connection()` le' DB_ENV no
    momento da chamada e cai no `.env.prod` quando ela esta' vazia. Era esse
    detalhe que exigia cravar no TOPO, antes de qualquer import que conecte --
    e ele continua verdadeiro pra qualquer trava futura que alguem queira por
    aqui.

    Hoje o laco herda o ambiente de quem o chamou, como o resto do projeto.
    """
    return



_cravar_dev()

from engine_pipelines.live_pipeline import run_live_engine  # noqa: E402
from services.pick_engine_live.config import LiveEngineConfig  # noqa: E402


def _agora() -> datetime:
    return datetime.now(TZ_BR)


def _hora(texto: str | None) -> datetime | None:
    """"20:30" -> hoje as 20:30 em Brasilia. Horario ja passado vira amanha,
    pra `--ate 00:30` num jogo que comeca 22:00 significar o que parece."""
    if not texto:
        return None
    try:
        hora, minuto = (int(p) for p in texto.strip().split(":"))
    except ValueError:
        raise SystemExit(f"[LIVE-WATCH] Horario invalido: {texto!r}. Use HH:MM.")
    alvo = _agora().replace(hour=hora, minute=minuto, second=0, microsecond=0)
    if alvo <= _agora():
        alvo += timedelta(days=1)
    return alvo


def _motivo_de_parada(sessao: dict, orcamento: int, ate: datetime | None,
                      max_rodadas: int, espera_min: int = 0) -> str | None:
    """Por que a sessao deve encerrar agora, ou None pra continuar.

    `espera_min` e' o que a proxima espera custaria. Chamando com ele depois de
    cada rodada, a sessao encerra ANTES de dormir 8 minutos pra so' entao
    descobrir que ja tinha acabado -- que era como o resumo chegava depois do
    apito final.
    """
    if ate and _agora() + timedelta(minutes=espera_min) >= ate:
        return f"Horario de parada ({ate.strftime('%H:%M')}) alcancado."
    if sessao["rodadas"] >= max_rodadas:
        return f"Teto de {max_rodadas} rodadas alcancado."
    if orcamento - sessao["requisicoes"] < 1:
        return f"Orcamento da sessao esgotado ({orcamento} requisicoes)."
    return None


def _dormir(segundos: int, ate: datetime | None) -> bool:
    """Espera em fatias de 1s pra o Ctrl+C responder na hora. Devolve False
    quando o horario de parada chegou durante a espera."""
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        if ate and _agora() >= ate:
            return False
        time.sleep(1)
    return True


def acompanhar(intervalo: int = 10, intervalo_ocioso: int = 15, orcamento: int = 120,
               ate: datetime | None = None, max_rodadas: int = 40, ocioso_para: int = 4,
               dry_run: bool = False, max_partidas: int | None = None) -> dict:
    """O laco. Devolve o resumo da sessao.

    O intervalo padrao acompanha a JANELA DO MODELO, nao o relogio: 10 minutos
    e' a primeira das `config.janelas_minutos`, entao duas leituras seguidas
    fecham exatamente a janela que o ritmo usa. Varrer mais rapido que isso nao
    traz leitura nova -- traz a mesma leitura de novo, com um decimo do
    orcamento a menos.

    RODADA NAO PRECISA GERAR PICK. A varredura le' todas as partidas elegiveis
    e pode terminar com zero picks, e isso e' o comportamento correto: o motor
    so' publica quando o jogo se afasta do esperado E a odd paga por isso.
    """
    config = LiveEngineConfig.do_ambiente()
    if not config.habilitado:
        raise SystemExit(
            "[LIVE-WATCH] LIVE_ENGINE_ENABLED=false. O motor foi desligado neste\n"
            "             ambiente de proposito (o padrao e' LIGADO desde 28/08),\n"
            "             entao o laco so' gastaria relogio. Tire a variavel ou\n"
            "             ponha =true antes de acompanhar."
        )

    sessao = {"rodadas": 0, "requisicoes": 0, "picks": [], "erros": [],
              "ociosas": 0, "inicio": _agora()}
    ociosas_seguidas = 0

    print("\n" + "#" * 62)
    print("LIVE WATCH · acompanhamento ao vivo")
    print(f"  banco:     {(os.getenv('DB_ENV') or 'prod').upper()} (herdado do ambiente)")
    print(f"  gravacao:  {'NAO (dry run)' if dry_run else 'SIM, grava em picks_live'}")
    print(f"  intervalo: {intervalo} min com jogo · {intervalo_ocioso} min sem jogo")
    print(f"  orcamento: {orcamento} requisicoes na sessao inteira")
    print(f"  ate:       {ate.strftime('%H:%M') if ate else 'sem horario de parada'}")
    print(f"  para se:   {ocioso_para} rodadas seguidas sem jogo elegivel")
    print("#" * 62)

    try:
        while True:
            parada = _motivo_de_parada(sessao, orcamento, ate, max_rodadas)
            if parada:
                print(f"\n[LIVE-WATCH] {parada}")
                break

            restante = orcamento - sessao["requisicoes"]
            sessao["rodadas"] += 1
            print(f"\n\n{'=' * 62}\nRODADA {sessao['rodadas']} · {_agora().strftime('%H:%M:%S')} BR "
                  f"· {restante} requisicao(oes) de orcamento restante\n{'=' * 62}")

            relatorio = run_live_engine(dry_run=dry_run, max_partidas=max_partidas)
            sessao["requisicoes"] += int(relatorio.get("requisicoes") or 0)
            sessao["erros"].extend(relatorio.get("erros") or [])
            for pick in relatorio.get("picks_criados") or []:
                sessao["picks"].append({**pick, "rodada": sessao["rodadas"],
                                        "hora": _agora().strftime("%H:%M")})

            elegiveis = int(relatorio.get("fixtures_elegiveis") or 0)
            # Jogo das nossas ligas que ainda pode virar pick nesta partida:
            # tipicamente um que esta no minuto 10' e entra na janela daqui a
            # pouco. Ate 2026-08-16 este numero nao existia no relatorio (o
            # campo estava so' num comentario do live_pipeline), entao a rodada
            # que enxergava um jogo prestes a comecar contava como OCIOSA e
            # esperava o intervalo longo -- justamente atravessando a entrada
            # dele na janela. Contar no radar nao gera pick sozinho; so' escolhe
            # a espera curta e impede o encerramento prematuro da sessao.
            no_radar = int(relatorio.get("fixtures_no_radar") or 0)
            if elegiveis or no_radar:
                ociosas_seguidas = 0
            else:
                ociosas_seguidas += 1
                sessao["ociosas"] += 1
                if ociosas_seguidas >= ocioso_para:
                    print(f"\n[LIVE-WATCH] {ociosas_seguidas} rodadas seguidas sem jogo "
                          f"elegivel nem no radar. Encerrando -- a janela de hoje fechou.")
                    break

            espera = intervalo if (elegiveis or no_radar) else intervalo_ocioso
            parada = _motivo_de_parada(sessao, orcamento, ate, max_rodadas, espera)
            if parada:
                print(f"\n[LIVE-WATCH] {parada}")
                break

            print(f"\n[LIVE-WATCH] Sessao: {sessao['rodadas']} rodada(s) · "
                  f"{sessao['requisicoes']}/{orcamento} requisicoes · "
                  f"{len(sessao['picks'])} pick(s). "
                  f"Proxima em {espera} min ({(_agora() + timedelta(minutes=espera)).strftime('%H:%M')}).")
            if not _dormir(espera * 60, ate):
                print(f"\n[LIVE-WATCH] Horario de parada alcancado durante a espera.")
                break
    except KeyboardInterrupt:
        print("\n\n[LIVE-WATCH] Interrompido no teclado.")

    _resumo(sessao, dry_run)
    return sessao


def _resumo(sessao: dict, dry_run: bool) -> None:
    duracao = int((_agora() - sessao["inicio"]).total_seconds() // 60)
    print("\n" + "#" * 62)
    print("RESUMO DA SESSAO")
    print(f"  duracao:      {duracao} min ({sessao['inicio'].strftime('%H:%M')} "
          f"-> {_agora().strftime('%H:%M')})")
    print(f"  rodadas:      {sessao['rodadas']}  ({sessao['ociosas']} sem jogo elegivel)")
    print(f"  requisicoes:  {sessao['requisicoes']}")
    print(f"  picks:        {len(sessao['picks'])}"
          + ("  (dry run · nada gravado)" if dry_run else ""))
    for p in sessao["picks"]:
        alvo = f"#{p['pick_id']}" if p.get("pick_id") else "(dry run)"
        print(f"    {p['hora']} rodada {p['rodada']} {alvo} · fixture {p['fixture_id']} · "
              f"{p['market']} {p['line']} @ {p['odd']:.2f} "
              f"ev={p['ev']:+.1%} conf={p['confidence']*100:.0f}%")
    if sessao["erros"]:
        print(f"  erros:        {len(sessao['erros'])}")
        for e in sessao["erros"][:5]:
            print(f"    - {e}")
    print("#" * 62 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Acompanha os jogos ao vivo disparando rodadas do Motor Live (DEV)")
    parser.add_argument("--intervalo", type=int, default=10,
                        help="minutos entre rodadas quando ha jogo elegivel (padrao 10, "
                             "que e' a largura da janela principal do modelo de ritmo "
                             "-- ver config.janelas_minutos)")
    parser.add_argument("--intervalo-ocioso", type=int, default=15,
                        help="minutos entre rodadas quando nao ha jogo (padrao 15)")
    parser.add_argument("--orcamento", type=int, default=120,
                        help="teto de requisicoes da SESSAO inteira (padrao 120)")
    parser.add_argument("--ate", default=None,
                        help="horario de parada em Brasilia, HH:MM (ex: 20:30)")
    parser.add_argument("--max-rodadas", type=int, default=40)
    parser.add_argument("--ocioso-para", type=int, default=4,
                        help="encerra apos N rodadas seguidas sem jogo elegivel (padrao 4)")
    parser.add_argument("--max", type=int, default=None,
                        help="teto de partidas por rodada (sobrescreve LIVE_MAX_MATCHES)")
    parser.add_argument("--dry-run", action="store_true",
                        help="calcula e loga sem gravar pick. O padrao e' GRAVAR: "
                             "este arquivo existe pra fazer o motor rodar de verdade em DEV")
    args = parser.parse_args()

    acompanhar(
        intervalo=args.intervalo,
        intervalo_ocioso=args.intervalo_ocioso,
        orcamento=args.orcamento,
        ate=_hora(args.ate),
        max_rodadas=args.max_rodadas,
        ocioso_para=args.ocioso_para,
        dry_run=args.dry_run,
        max_partidas=args.max,
    )
