"""Casar o nome que a CASA publica com o jogador que a API gravou.

ORIGEM: este e' o resolvedor do antigo goleiros_pipeline, promovido a modulo
porque agora ele serve a seis metodos, nao a um. A logica esta' inteira, com
os casos reais que a produziram -- eles sao o motivo de ela nao ser um
`lower()` e uma comparacao:

  · 2026-08-05, Betano publicou "Weverton Pereira" (Palmeiras) e a base tinha
    "Weverton". Existe OUTRO "Weverton" (Gremio) na mesma base, jogando no
    mesmo dia. Casar so' por nome pegaria o do Gremio, leria o adversario
    errado e INVERTERIA a previsao -- pior que nao gerar pick;
  · fixture 1546848 (Fortaleza): a casa escreveu "Joao Ricardo" sem til e a
    API com til. Comparar cru descartava o jogador como desconhecido.

Dai as duas regras que definem o arquivo: o TIME faz parte da chave, e
ambiguidade nunca vira chute.

goleiros_pipeline.py continua com a copia dele no disco. Nao e' descuido: o
pipeline antigo fica como rollback (mesma politica dos pipelines de IA em
ai/*.py), e um rollback que depende de um modulo novo nao e' rollback.
"""
from __future__ import annotations

import re
import unicodedata

#: "Everson - 1" e "Everson - 1+" significam a mesma coisa ("N ou mais"), entao
#: o "+" e' notacao e nao muda a linha.
VALOR_RE = re.compile(r"^(?P<nome>.+?)\s*[-–]\s*(?P<n>\d+)\+?$")


def normalizar(nome: str) -> str:
    """Chave de comparacao: sem acento, sem caixa, sem espaco duplicado."""
    sem_acento = unicodedata.normalize("NFKD", nome or "")
    sem_acento = "".join(ch for ch in sem_acento if not unicodedata.combining(ch))
    return " ".join(sem_acento.lower().split())


def parse_valor(value_name: str) -> tuple | None:
    """('Everson', 1) a partir de 'Everson - 1'. None se o formato nao bater.

    Nunca adivinha: formato diferente do esperado devolve None e o candidato e'
    descartado, em vez de virar um pick com a linha errada.
    """
    m = VALOR_RE.match((value_name or "").strip())
    if not m:
        return None
    nome = m.group("nome").strip()
    if not nome:
        return None
    return nome, int(m.group("n"))


def resolver(nome_ofertado: str, jogadores: list, home_team_id: int,
             away_team_id: int) -> dict | None:
    """O jogador da oferta, procurado APENAS entre os dois times da partida.

    `jogadores` sao dicts com `player_id`, `player_name`, `team_id`. A chave de
    comparacao e' calculada aqui pra o chamador nao precisar pre-normalizar.

      1. nome normalizado identico vence;
      2. senao, aceita quando os tokens de um nome estao contidos nos do outro
         ("weverton" dentro de "weverton pereira");
      3. empate entre dois jogadores do jogo devolve None.
    """
    alvo = set(normalizar(nome_ofertado).split())
    if not alvo:
        return None

    do_jogo = [j for j in jogadores if j.get("team_id") in (home_team_id, away_team_id)]

    exatos = [j for j in do_jogo
              if set(normalizar(j.get("player_name")).split()) == alvo]
    if exatos:
        return exatos[0] if len(exatos) == 1 else None

    parciais = []
    for j in do_jogo:
        tokens = set(normalizar(j.get("player_name")).split())
        if tokens and (tokens <= alvo or alvo <= tokens):
            parciais.append(j)
    return parciais[0] if len(parciais) == 1 else None
