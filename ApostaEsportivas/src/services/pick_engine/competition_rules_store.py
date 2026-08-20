"""Regulamento de mata-mata vindo do banco, para competicao que o motor nao
conhece de cabeca.

POR QUE ISTO NAO E' UMA CHAMADA DE IA NO CAMINHO DO PICK
--------------------------------------------------------
O pedido foi "chamar a IA pra entender o contexto do jogo antes de ir pro
motor, algo que nao gaste muito". A parte de CONTEXTO DO JOGO ja' esta
resolvida sem IA nenhuma e nao deve voltar a depender dela: formato, perna,
agregado, quem precisa do resultado e quanto isso desloca cada mercado saem de
dado que ja' esta no banco, com efeito medido (ver tie_effect.py). Trocar isso
por um parecer de modelo custaria token por partida e, pior, trocaria um numero
auditavel por uma opiniao que muda entre duas chamadas iguais.

Sobra UMA pergunta que o banco nao responde e que a IA responde bem:

    "Nesta competicao, esta fase e' de ida e volta? Vale gol fora?
     Tem prorrogacao? Tem penaltis?"

E ela tem tres propriedades que a tornam o lugar certo pra gastar token:

  1. E' por COMPETICAO E TEMPORADA, nao por partida. Uma resposta serve pra
     todos os jogos daquela fase, o ano inteiro.
  2. E' ESTAVEL. Regulamento nao muda no meio do campeonato; quando muda, muda
     uma vez e a linha e' reescrita.
  3. E' VERIFICAVEL. A resposta e' um punhado de booleanos que a realidade
     confirma ou desmente em poucos jogos -- e `formato_origem` continua
     dizendo de onde veio, entao um regulamento errado aparece no rastro em
     vez de sumir dentro de uma probabilidade.

Ou seja: o custo e' uma chamada por competicao POR TEMPORADA, feita fora do
horario de pick por `scripts/descobrir_regulamento.py`, e nunca no laco de
geracao. O motor so' LE esta tabela.

A ORDEM DE AUTORIDADE NAO MUDA
------------------------------
Evidencia continua ganhando de regulamento, e regulamento cadastrado a mao
continua ganhando de IA:

    rotulo da API  >  confronto anterior  >  _REGRAS (mao)  >  esta tabela  >  DESCONHECIDO

Isso importa: se a IA disser "ida e volta" e o confronto mostrar que nao ha
jogo anterior com mando invertido, quem manda e' o confronto. A IA entra
exatamente onde hoje o motor devolve DESCONHECIDO e para de analisar.
"""
from __future__ import annotations

from services.pick_engine.competition_profile import RegrasDeMataMata

_TABELA = "competition_rules"

#: Cache de processo. O motor le' isto uma vez por execucao de pipeline; sem
#: ele, cada fixture faria uma consulta pra descobrir a mesma coisa.
_cache: dict | None = None


def criar_tabela(cur) -> None:
    """Auto-provisiona, mesmo padrao dos engine_pipelines. `fonte` guarda
    quem respondeu (ia:<modelo> | manual) porque um regulamento errado precisa
    poder ser rastreado ate quem o afirmou."""
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {_TABELA} (
            league_id            INTEGER NOT NULL,
            season               INTEGER NOT NULL,
            two_legged_default   BOOLEAN,
            fases_de_jogo_unico  TEXT,
            away_goals           BOOLEAN,
            prorrogacao          BOOLEAN,
            penaltis             BOOLEAN,
            fonte                TEXT,
            observacao           TEXT,
            updated_at           TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (league_id, season)
        )
    """)


def _linha_para_regras(row) -> RegrasDeMataMata:
    fases = (row[1] or "").strip()
    return RegrasDeMataMata(
        two_legged_default=row[0],
        fases_de_jogo_unico=frozenset(f for f in fases.split(",") if f),
        away_goals=row[2],
        prorrogacao=row[3],
        penaltis=row[4],
    )


def carregar(cur, season=None) -> dict:
    """{league_id: RegrasDeMataMata} do banco. Nunca levanta: regulamento e'
    camada auxiliar, e um SELECT que falha nao pode derrubar a geracao de pick
    -- sem ele o motor volta a devolver DESCONHECIDO, que e' o comportamento
    correto de antes."""
    global _cache
    try:
        criar_tabela(cur)
        if season is None:
            cur.execute(f"""
                SELECT DISTINCT ON (league_id) league_id, two_legged_default,
                       fases_de_jogo_unico, away_goals, prorrogacao, penaltis
                  FROM {_TABELA} ORDER BY league_id, season DESC
            """)
        else:
            cur.execute(f"""
                SELECT league_id, two_legged_default, fases_de_jogo_unico,
                       away_goals, prorrogacao, penaltis
                  FROM {_TABELA} WHERE season = %s
            """, (season,))
        _cache = {r[0]: _linha_para_regras(r[1:]) for r in cur.fetchall()}
    except Exception as e:
        # ROLLBACK OBRIGATORIO, e nao e' zelo: no psycopg2 um erro deixa a
        # transacao ABORTADA, e toda consulta seguinte na mesma conexao falha
        # com "current transaction is aborted". Sem esta linha, uma tabela
        # ausente nesta camada auxiliar derrubaria a rodada inteira de picks --
        # exatamente o oposto do que a docstring promete.
        try:
            cur.connection.rollback()
        except Exception:
            pass
        print(f"[REGULAMENTO] Tabela indisponivel, seguindo sem ela: {e}")
        _cache = {}
    return _cache


def regras_do_banco(league_id):
    """RegrasDeMataMata desta liga, ou None. None e' o caso normal (a maioria
    das competicoes nunca vai precisar de linha aqui) e nunca um erro."""
    return (_cache or {}).get(league_id)


def limpar_cache() -> None:
    global _cache
    _cache = None


def gravar(cur, league_id: int, season: int, regras: RegrasDeMataMata,
           fonte: str, observacao: str | None = None) -> None:
    """Grava/atualiza o regulamento de uma competicao. Usado por
    scripts/descobrir_regulamento.py, nunca pelo caminho de geracao de pick."""
    criar_tabela(cur)
    cur.execute(f"""
        INSERT INTO {_TABELA} (league_id, season, two_legged_default,
                               fases_de_jogo_unico, away_goals, prorrogacao,
                               penaltis, fonte, observacao, updated_at)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (league_id, season) DO UPDATE SET
            two_legged_default  = EXCLUDED.two_legged_default,
            fases_de_jogo_unico = EXCLUDED.fases_de_jogo_unico,
            away_goals          = EXCLUDED.away_goals,
            prorrogacao         = EXCLUDED.prorrogacao,
            penaltis            = EXCLUDED.penaltis,
            fonte               = EXCLUDED.fonte,
            observacao          = EXCLUDED.observacao,
            updated_at          = NOW()
    """, (league_id, season, regras.two_legged_default,
          ",".join(sorted(regras.fases_de_jogo_unico)) or None,
          regras.away_goals, regras.prorrogacao, regras.penaltis,
          fonte, observacao))
