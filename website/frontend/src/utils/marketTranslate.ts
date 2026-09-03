const MARKET_PT: Record<string, string> = {
  'match winner': 'Resultado Final (1X2)',
  'double chance': 'Dupla Chance',
  'double chance - 1st half': 'Dupla Chance - 1º Tempo',
  'first half winner': 'Vencedor do 1º Tempo',
  'asian handicap': 'Handicap Asiático',
  'cards asian handicap': 'Cartões Handicap Asiático',
  'cards european handicap': 'Cartões Handicap Asiático',
  'corners asian handicap': 'Escanteios Handicap Asiático',
  'corners european handicap': 'Escanteios Handicap Asiático',
  'both teams score': 'Ambas as Equipes Marcam',
  'both teams to score': 'Ambas as Equipes Marcam',
  'both teams score - first half': 'Ambas Marcam - 1º Tempo',
  'both teams to score - first half': 'Ambas Marcam - 1º Tempo',
  'both teams score first half': 'Ambas Marcam - 1º Tempo',
  'goals over/under': 'Gols Mais/Menos',
  'total goals': 'Gols Mais/Menos',
  'over/under': 'Gols Mais/Menos',
  'goals over/under first half': 'Gols Mais/Menos - 1º Tempo',
  'goals over/under - first half': 'Gols Mais/Menos - 1º Tempo',
  'goals over/under 1st half': 'Gols Mais/Menos - 1º Tempo',
  'goals over/under - second half': 'Gols Mais/Menos - 2º Tempo',
  'goals over/under second half': 'Gols Mais/Menos - 2º Tempo',
  'goals over/under 2nd half': 'Gols Mais/Menos - 2º Tempo',
  'total - home': 'Total de Gols Casa',
  'total - away': 'Total de Gols Visitante',
  'home team total goals': 'Total de Gols Casa',
  'away team total goals': 'Total de Gols Visitante',
  'home team total goals - 1st half': 'Total de Gols Casa (1º Tempo)',
  'away team total goals - 1st half': 'Total de Gols Visitante (1º Tempo)',
  'corners over under': 'Escanteios Mais/Menos',
  'corners over/under': 'Escanteios Mais/Menos',
  'total corners': 'Escanteios Mais/Menos',
  'corners 1x2': 'Escanteios 1x2',
  'home corners over/under': 'Escanteios Casa Mais/Menos',
  'away corners over/under': 'Escanteios Visitante Mais/Menos',
  'total corners (1st half)': 'Escanteios (1º Tempo)',
  'corners over/under - 1st half': 'Escanteios (1º Tempo)',
  'total corners (2nd half)': 'Escanteios (2º Tempo)',
  'corners over/under - 2nd half': 'Escanteios (2º Tempo)',
  'cards over/under': 'Cartões Mais/Menos',
  'home team total cards': 'Cartões Casa',
  'away team total cards': 'Cartões Visitante',
  'home team cards': 'Cartões Casa',
  'away team cards': 'Cartões Visitante',
  'ht/ft': 'Inter./Final',
  'exact score': 'Placar Exato',
  'correct score': 'Placar Exato',
  'first goal scorer': 'Primeiro Gol',
  'anytime goalscorer': 'Marcar a Qualquer Tempo',
  'result': 'Resultado',
  'home/away': '1X2',
  // "Odd/Even" nao tinha traducao nenhuma -- ia cru pro site em ingles, e
  // "Odd" (impar) colide visualmente com "odd" em portugues (coeficiente
  // da aposta), confundindo o usuario ("Odd/Even Odd @ 2.02").
  'odd/even': 'Par/Ímpar',
  'odd or even': 'Par/Ímpar',
  'corners odd/even': 'Escanteios Par/Ímpar',
  // Faltas -- nome cru da API vem "Fouls. Home/Away/[nada] Total".
  'fouls. home total': 'Faltas Casa Mais/Menos',
  'fouls. away total': 'Faltas Visitante Mais/Menos',
  'fouls. total': 'Faltas Mais/Menos',
  'fouls': 'Faltas Mais/Menos',
  // Defesas de goleiro (bet_id 267) -- prop de JOGADOR, nao over/under de
  // time: a linha ja vem com o nome do goleiro ("Fabio · 3 ou mais defesas").
  'goalkeeper saves': 'Defesas do goleiro',
  'goalkeeper saves over/under': 'Defesas do goleiro',
  'player saves': 'Defesas do goleiro',
  'saves': 'Defesas do goleiro',
  /* OS OUTROS MERCADOS DE JOGADOR (02/09).
   *
   * Defesas estava aqui desde que era motor próprio; os cinco métodos que
   * nasceram com o Player Stats em 27/08 não. A aba Jogadores não sentia,
   * porque lá o rótulo vem do MÉTODO (LABEL_DO_METODO em Picks.tsx), mas
   * fora dela o nome da casa vazava cru: "Player Shots on Target" em Minhas
   * Apostas, na banca, no histórico e no painel de detalhe.
   *
   * Só as chaves que trazem "player" ou "by player". As formas nuas
   * ("shots on target", "tackles") ficam de fora de propósito: elas também
   * existem como mercado de TIME, e traduzir pelo nome curto marcaria um
   * mercado de time como se fosse de jogador.
   *
   * Fonte dos nomes: services/player_stats_engine/methods.py, campo
   * `nomes_mercado`. */
  'player shots on target': 'Chutes no alvo',
  'player shots on goal': 'Chutes no alvo',
  'shots on target by player': 'Chutes no alvo',
  'player shots': 'Chutes do jogador',
  'player total shots': 'Chutes do jogador',
  'total shots by player': 'Chutes do jogador',
  'player fouls committed': 'Faltas do jogador',
  'fouls committed': 'Faltas do jogador',
  'player fouls': 'Faltas do jogador',
  'player tackles': 'Desarmes',
  'player tackles made': 'Desarmes',
  'player passes': 'Passes do jogador',
  'player total passes': 'Passes do jogador',
  'total passes by player': 'Passes do jogador',
  // Chutes e impedimentos · vinham CRUS pra tela ("Total Shots Over 23.5" na
  // Dica do Dia da Home, "Total ShotOnGoal" no histórico).
  'total shots': 'Finalizações Mais/Menos',
  'total shotongoal': 'Finalizações no Gol Mais/Menos',
  'total shots on goal': 'Finalizações no Gol Mais/Menos',
  'shots on goal': 'Finalizações no Gol Mais/Menos',
  'offsides home total': 'Impedimentos Casa Mais/Menos',
  'offsides away total': 'Impedimentos Visitante Mais/Menos',
  'offsides total': 'Impedimentos Mais/Menos',
  'total - home goals over/under': 'Total de Gols Casa',
  'total - away goals over/under': 'Total de Gols Visitante',
  'to qualify': 'Classificação',
  'to qualify - extra time': 'Classificação (Prorrogação)',
}

/*
 * Índice reverso: nome em português -> chave canônica (a inglesa do MARKET_PT).
 *
 * O motor grava em `picks.market` o nome JÁ TRADUZIDO, então a maioria dos
 * picks chega aqui como "Escanteios Mais/Menos", e não como "Corners Over
 * Under". `translateMarket` não sofria com isso (devolve o texto como veio),
 * mas TODO O RESTO sofria: `MARKET_EXPLAIN` e `regraDoMercado` são indexados
 * pela chave em inglês, então nenhum desses picks casava e todos caíam no
 * texto genérico "Dá GREEN conforme as condições do mercado X" · que é
 * exatamente a informação que não ajuda ninguém.
 *
 * Em 15/08/2026 isso valia para 232 dos 312 picks do histórico.
 *
 * A primeira chave vence de propósito: MARKET_PT tem vários sinônimos em
 * inglês para o mesmo nome em português ('total corners', 'corners over under'
 * e 'corners over/under' viram todos "Escanteios Mais/Menos"), e a primeira é
 * a que MARKET_EXPLAIN também usa.
 */
const PT_PARA_CHAVE: Record<string, string> = (() => {
  const idx: Record<string, string> = {}
  for (const [en, pt] of Object.entries(MARKET_PT)) {
    const k = pt.trim().toLowerCase()
    if (!(k in idx)) idx[k] = en
  }
  return idx
})()

/**
 * Chave em inglês para consultar MARKET_EXPLAIN, venha o mercado em inglês
 * (nome cru da API) ou em português (o que o motor grava hoje).
 */
export function chaveCanonica(market?: string): string {
  if (!market) return ''
  const key = market.trim().toLowerCase()
  if (MARKET_PT[key]) return key
  // Alguns nomes carregam a competição no fim · "Escanteios Casa Mais/Menos
  // (England)". O sufixo não muda a regra do mercado.
  const semSufixo = key.replace(/\s*\([^)]*\)\s*$/, '').trim()
  return PT_PARA_CHAVE[key] ?? PT_PARA_CHAVE[semSufixo] ?? key
}

export function translateMarket(m?: string): string {
  if (!m) return ''
  const key = m.trim().toLowerCase()
  if (MARKET_PT[key]) return MARKET_PT[key]
  const canon = chaveCanonica(m)
  if (MARKET_PT[canon]) return MARKET_PT[canon]
  for (const [k, v] of Object.entries(MARKET_PT)) {
    if (key.includes(k)) return v
  }
  return m
}

// Explicação curta de quando a aposta dá GREEN, em português simples. Ordem
// dos campos importa: entradas mais específicas (escanteios, cartões, times
// isolados) vêm antes das genéricas de gols/over-under, senão o match por
// substring (ex.: "corners over/under" contém "over/under") acertaria a
// explicação errada primeiro.
type OverUnderInfo = { dir: 'maior' | 'menor'; value: string } | null
/** `sujeito` só existe nos mercados de CONTAGEM · é ele que permite explicar a
 *  regra em número inteiro (ver regraDoMercado). */
type ExplainFn = ((lineTxt: string, ou: OverUnderInfo) => string) & { sujeito?: string }

const _ouOr = (subject: string): ExplainFn => {
  const fn: ExplainFn = (lineTxt, ou) =>
    ou
      ? `Dá GREEN se ${subject} for ${ou.dir} que ${ou.value}.`
      : `Dá GREEN se ${subject} bater com a linha ${lineTxt}.`
  // Carregado na própria função em vez de raspado do texto com regex: a
  // primeira versão fazia isso e trazia "o total de escanteios da partida for
  // maior que 0" junto, porque o corte parava só no ponto final.
  fn.sujeito = subject
  return fn
}

const MARKET_EXPLAIN: Record<string, ExplainFn> = {
  'match winner':          lineTxt => `Dá GREEN se o resultado da partida for: ${lineTxt}.`,
  'double chance':         lineTxt => `Dá GREEN se a partida terminar em um dos 2 resultados cobertos: ${lineTxt}. Reduz o risco, mas também reduz a odd.`,
  'first half winner':     lineTxt => `Dá GREEN se, ao final do 1º tempo, o resultado for: ${lineTxt}.`,
  'corners asian handicap': lineTxt => `Dá GREEN se, já somando a vantagem/desvantagem de escanteios aplicada, o resultado for: ${lineTxt}.`,
  'corners european handicap': lineTxt => `Dá GREEN se, já somando a vantagem/desvantagem de escanteios aplicada, o resultado for: ${lineTxt}.`,
  'cards asian handicap':  lineTxt => `Dá GREEN se, já somando a vantagem/desvantagem de cartões aplicada, o resultado for: ${lineTxt}.`,
  'cards european handicap': lineTxt => `Dá GREEN se, já somando a vantagem/desvantagem de cartões aplicada, o resultado for: ${lineTxt}.`,
  'corners over under':    _ouOr('o total de escanteios da partida'),
  'corners over/under':    _ouOr('o total de escanteios da partida'),
  'total corners':         _ouOr('o total de escanteios da partida'),
  'corners 1x2':           lineTxt => `Dá GREEN se a equipe com mais escanteios na partida for: ${lineTxt}.`,
  'home corners over/under': _ouOr('o total de escanteios só da equipe da casa'),
  'away corners over/under': _ouOr('o total de escanteios só da equipe visitante'),
  'cards over/under':      _ouOr('o total de cartões (amarelos + vermelhos) da partida'),
  'home team total cards': _ouOr('o total de cartões só da equipe da casa'),
  'away team total cards': _ouOr('o total de cartões só da equipe visitante'),
  'home team cards':       _ouOr('o total de cartões só da equipe da casa'),
  'away team cards':       _ouOr('o total de cartões só da equipe visitante'),
  'asian handicap':        lineTxt => `Dá GREEN se, já somando a vantagem/desvantagem de gols aplicada, o resultado for: ${lineTxt}.`,
  'both teams score':      () => 'Dá GREEN se as duas equipes marcarem pelo menos 1 gol cada uma na partida.',
  'both teams to score':   () => 'Dá GREEN se as duas equipes marcarem pelo menos 1 gol cada uma na partida.',
  'total - home':          _ouOr('o total de gols só da equipe da casa'),
  'total - away':          _ouOr('o total de gols só da equipe visitante'),
  'home team total goals': _ouOr('o total de gols só da equipe da casa'),
  'away team total goals': _ouOr('o total de gols só da equipe visitante'),
  'ht/ft':                 lineTxt => `Dá GREEN se a combinação intervalo/final for: ${lineTxt}.`,
  'exact score':           lineTxt => `Dá GREEN se o placar final da partida for exatamente: ${lineTxt}.`,
  'correct score':         lineTxt => `Dá GREEN se o placar final da partida for exatamente: ${lineTxt}.`,
  'first goal scorer':     () => 'Dá GREEN se esse jogador marcar o primeiro gol da partida.',
  'anytime goalscorer':    () => 'Dá GREEN se esse jogador marcar pelo menos 1 gol a qualquer momento da partida.',
  'home/away':             lineTxt => `Dá GREEN se o vencedor da partida (sem opção de empate) for: ${lineTxt}.`,
  'to qualify':            () => 'Dá GREEN se essa equipe avançar de fase. Não depende do placar desse jogo específico.',
  'result':                lineTxt => `Dá GREEN se o resultado da partida for: ${lineTxt}.`,
  'goals over/under':      _ouOr('o total de gols da partida'),
  'total goals':           _ouOr('o total de gols da partida'),
  'over/under':            _ouOr('o total da partida'),
  'corners odd/even':      lineTxt => `Dá GREEN se o total de escanteios da partida (somando os dois times) for um número ${lineTxt === 'Ímpar' ? 'ímpar' : 'par'}.`,
  'odd/even':              lineTxt => `Dá GREEN se o total de gols da partida (somando os dois times) for um número ${lineTxt === 'Ímpar' ? 'ímpar' : 'par'}. Não importa quem vence, só a contagem total.`,
  'fouls. home total':     _ouOr('o total de faltas cometidas só pela equipe da casa'),
  'fouls. away total':     _ouOr('o total de faltas cometidas só pela equipe visitante'),
  'fouls. total':          _ouOr('o total de faltas da partida (somando os dois times)'),
  'fouls':                 _ouOr('o total de faltas da partida (somando os dois times)'),
  // "N ou mais" -- nao e' over/under, entao nao usa _ouOr: da GREEN a partir
  // de N defesas, inclusive N (P(X >= N), ver goalkeeper_model.py).
  'total shots':           _ouOr('o total de finalizações da partida (somando os dois times, no gol ou fora)'),
  'total shotongoal':      _ouOr('o total de finalizações no gol da partida (só as que exigem defesa ou entram)'),
  'total shots on goal':   _ouOr('o total de finalizações no gol da partida (só as que exigem defesa ou entram)'),
  'shots on goal':         _ouOr('o total de finalizações no gol da partida (só as que exigem defesa ou entram)'),
  'offsides home total':   _ouOr('o total de impedimentos só da equipe da casa'),
  'offsides away total':   _ouOr('o total de impedimentos só da equipe visitante'),
  'offsides total':        _ouOr('o total de impedimentos da partida (somando os dois times)'),
  'total - home goals over/under': _ouOr('o total de gols só da equipe da casa'),
  'total - away goals over/under': _ouOr('o total de gols só da equipe visitante'),
  'goalkeeper saves':      () => 'Dá GREEN se esse goleiro fizer o número de defesas da linha ou mais. Vale só as defesas dele, não as do time inteiro.',
  'player saves':          () => 'Dá GREEN se esse goleiro fizer o número de defesas da linha ou mais.',
  'saves':                 () => 'Dá GREEN se esse goleiro fizer o número de defesas da linha ou mais.',
}

/**
 * O que o mercado conta, em uma frase, sem a linha.
 *
 * Sai de MARKET_EXPLAIN reaproveitando o sujeito que já está lá ("o total de
 * escanteios da partida"), então não existe segunda lista pra manter em dia.
 */
function sujeitoDoMercado(market: string): string {
  const fn = MARKET_EXPLAIN[market] ?? Object.entries(MARKET_EXPLAIN).find(([k]) => market.includes(k))?.[1]
  return fn?.sujeito ?? ''
}

/** Unidade contável do mercado, pro texto falar "escanteios" e não "unidades". */
/** [singular, plural] da unidade contada · '' quando o mercado não conta nada. */
function unidadeDoMercado(sujeito: string): readonly [string, string] {
  const s = sujeito.toLowerCase()
  for (const [chave, sing, plur] of [
    ['escanteio', 'escanteio', 'escanteios'],
    ['cart', 'cartão', 'cartões'],
    ['falta', 'falta', 'faltas'],
    ['finaliza', 'finalização', 'finalizações'],
    ['gol', 'gol', 'gols'],
    ['chute', 'chute', 'chutes'],
    ['defesa', 'defesa', 'defesas'],
    ['impedimento', 'impedimento', 'impedimentos'],
  ] as const) {
    if (s.includes(chave)) return [sing, plur]
  }
  return ['', '']
}

export interface RegraDoMercado {
  /** "Conta os escanteios dos dois times somados, no jogo inteiro." */
  oQueE: string
  /** Condição de GREEN, já em número inteiro. */
  green: string
  /** Condição de RED. Ausente quando o mercado não é de contagem. */
  red?: string
  /** Empate técnico devolve a aposta (linha cheia) ou metade dela (quarto). */
  devolve?: string
}

/**
 * Explicação da regra em número INTEIRO, pra quem não conhece o mercado.
 *
 * A linha vem com meio ponto ("Menos de 10.5") por um motivo técnico: meio
 * escanteio não existe, então a fração só serve pra impedir empate. Mas quem
 * lê "10.5 escanteios" pela primeira vez trava · o jogo nunca vai ter isso.
 *
 * Aqui a fração vira a contagem real do campo:
 *
 *   Menos de 10.5  ->  GREEN com 10 ou menos | RED com 11 ou mais
 *   Mais de 9.5    ->  GREEN com 10 ou mais  | RED com 9 ou menos
 *
 * Linha cheia (10.0) tem um terceiro caso que o texto antigo escondia: sair
 * exatamente 10 não é GREEN nem RED, devolve a aposta. E linha de quarto
 * (9.75) é meia aposta em cada linha vizinha, então pode pagar metade. Os dois
 * aparecem porque quem descobre isso só quando acontece acha que foi erro.
 */
export function regraDoMercado(market?: string, line?: string): RegraDoMercado | null {
  if (!market) return null
  // Canoniza antes de consultar: o mercado chega em português na maioria dos
  // picks, e o mapa de explicações é indexado em inglês.
  const key = chaveCanonica(market)
  const lineTxt = translateLine(line) || ''

  const ouMatch = lineTxt.match(/^(Mais de|Menos de)\s+([\d.,]+)$/)
  if (!ouMatch) return null

  const acima = ouMatch[1] === 'Mais de'
  const valor = parseFloat(ouMatch[2].replace(',', '.'))
  if (!Number.isFinite(valor)) return null

  const sujeito = sujeitoDoMercado(key)
  if (!sujeito) return null
  const [singular, plural] = unidadeDoMercado(sujeito)
  // Concordância de número: sem isto o texto saía "saírem 1 gols ou menos".
  const conta = (n: number) =>
    (plural ? `${n} ${Math.abs(n) === 1 ? singular : plural}` : String(n))

  const oQueE = `Conta ${sujeito}.`
  const frac = Math.round((valor % 1) * 100)

  // Meia linha (x.5): o caso comum. Não existe empate, só GREEN ou RED.
  if (frac === 50) {
    const corte = Math.floor(valor)
    return acima
      ? { oQueE, green: `Saírem ${conta(corte + 1)} ou mais.`, red: `Saírem ${conta(corte)} ou menos.` }
      : { oQueE, green: `Saírem ${conta(corte)} ou menos.`,   red: `Saírem ${conta(corte + 1)} ou mais.` }
  }

  // Linha cheia (x.0): bater o número exato devolve a aposta.
  if (frac === 0) {
    return {
      oQueE,
      green: acima ? `Saírem ${conta(valor + 1)} ou mais.` : `Saírem ${conta(valor - 1)} ou menos.`,
      red:   acima ? `Saírem ${conta(valor - 1)} ou menos.` : `Saírem ${conta(valor + 1)} ou mais.`,
      devolve: `Saírem exatamente ${conta(valor)}: a aposta volta pra você, sem ganho nem perda.`,
    }
  }

  /*
   * Quarto de linha (x.25 / x.75): a aposta é partida em duas metades, uma em
   * cada linha vizinha. Existe um número inteiro no meio onde uma metade
   * resolve e a outra empata · e QUAL metade muda conforme o quarto.
   *
   *   Mais de 9.75  -> metades em 9.5 e 10. Saindo 10: a de 9.5 ganha e a de
   *                    10 empata, então metade GANHA.
   *   Mais de 9.25  -> metades em 9 e 9.5. Saindo 9: a de 9 empata e a de 9.5
   *                    perde, então metade PERDE.
   *
   * Dizer só "paga metade" nos dois casos avisaria que volta dinheiro num
   * cenário em que metade some. É a diferença que o apostador só descobre
   * quando acontece, e aí parece erro do site.
   */
  const meio = Math.round(valor)
  const metadeGanha = acima ? frac === 75 : frac === 25
  return {
    oQueE,
    green: acima ? `Saírem ${conta(meio + 1)} ou mais.` : `Saírem ${conta(meio - 1)} ou menos.`,
    red:   acima ? `Saírem ${conta(meio - 1)} ou menos.` : `Saírem ${conta(meio + 1)} ou mais.`,
    devolve: metadeGanha
      ? `Saírem exatamente ${conta(meio)}: metade da aposta ganha e a outra metade volta.`
      : `Saírem exatamente ${conta(meio)}: metade da aposta perde e a outra metade volta.`,
  }
}

/** Explicação curta em português de quando essa aposta (mercado + linha) dá GREEN. */
export function explainMarket(market?: string, line?: string): string {
  if (!market) return ''
  const key = chaveCanonica(market)
  const lineTxt = translateLine(line) || 'valor definido pela IA'

  // Quando dá pra falar em número inteiro, é essa a versão que vale · ver
  // regraDoMercado. O texto com a linha fracionada fica de reserva.
  const regra = regraDoMercado(market, line)
  if (regra) return `${regra.oQueE} Dá GREEN se ${regra.green.charAt(0).toLowerCase()}${regra.green.slice(1)}`

  const ouMatch = lineTxt.match(/^(Mais de|Menos de)\s+([\d.,]+)$/)
  const ou: OverUnderInfo = ouMatch ? { dir: ouMatch[1] === 'Mais de' ? 'maior' : 'menor', value: ouMatch[2] } : null
  const fn = MARKET_EXPLAIN[key] ?? Object.entries(MARKET_EXPLAIN).find(([k]) => key.includes(k))?.[1]
  if (!fn) return `Dá GREEN conforme as condições do mercado "${translateMarket(market)}"${line ? `, linha ${lineTxt}` : ''}.`
  return fn(lineTxt, ou)
}

const LINE_PT: Record<string, string> = {
  'home': 'Casa',
  'away': 'Visitante',
  'draw': 'Empate',
  'yes': 'Sim',
  'no': 'Não',
  'odd': 'Ímpar',
  'even': 'Par',
}

// Traduz linha completa (ex.: "Away"), "Over/Under X.Y" (ex.: "Over 8.5" ->
// "Mais de 8.5") e combos tipo Dupla Chance no formato cru da API
// ("Home/Draw" -> "Casa/Empate", ver ai_result_checker_service.py que já
// entende esse mesmo formato pra grading).
export function translateLine(line?: string): string {
  if (!line) return ''
  /* PONTO DO MEIO NUNCA CHEGA NA TELA (02/09).
   *
   * O motor de jogador gravava a linha como "Fulano · 2 ou mais chutes", e
   * essa pontuação não é usada em lugar nenhum do site. O pipeline já grava com
   * vírgula, mas os picks gravados ANTES continuam no banco e continuam sendo
   * exibidos no histórico, então a limpeza mora aqui: é o funil por onde toda
   * linha passa antes de virar texto. */
  const trimmed = line.trim().replace(/\s*·\s*/g, ', ')
  const key = trimmed.toLowerCase()
  if (LINE_PT[key]) return LINE_PT[key]

  const overUnder = trimmed.match(/^(over|under)\s+([\d.,]+)$/i)
  if (overUnder) {
    const dir = overUnder[1].toLowerCase() === 'over' ? 'Mais de' : 'Menos de'
    return `${dir} ${overUnder[2]}`
  }

  const parts = trimmed.split('/')
  if (parts.length === 2) {
    const [a, b] = parts.map(p => LINE_PT[p.trim().toLowerCase()])
    if (a && b) return `${a}/${b}`
  }

  // `trimmed`, não `line`: é a versão já sem ponto do meio.
  return trimmed
}

/*
 * O NÚMERO QUE DECIDIU O PICK, escrito como se lê.
 *
 * A liquidação grava o contador que a folha do jogo publicou (`settled_value`),
 * e a tela mostrava só GREEN, RED ou PUSH. "Esse resultado está errado" era uma
 * frase que ninguém conseguia conferir: PUSH por empate técnico numa linha
 * cheia (12 escanteios numa linha de 12.0) e PUSH por anulação chegavam com a
 * mesma cara.
 *
 * Com o número na tela, a conferência não depende mais de nós: dá pra comparar
 * com a súmula. A unidade sai do próprio catálogo de mercados, então
 * escanteios não viram "12 unidades".
 */
export function valorLiquidado(market?: string, valor?: number | null): string {
  if (valor == null) return ''
  const [singular, plural] = unidadeDoMercado(sujeitoDoMercado(chaveCanonica(market)))
  const n = Number(valor)
  const inteiro = Number.isInteger(n) ? String(n) : n.toFixed(1).replace('.', ',')
  if (!plural) return inteiro
  return `${inteiro} ${Math.abs(n) === 1 ? singular : plural}`
}

/*
 * "MERCADO, LINHA" NUMA STRING SÓ.
 *
 * Metade das telas escrevia isso à mão, e cada uma de um jeito: umas com
 * vírgula, outras com espaço; umas traduzindo os dois campos, outras nenhum.
 * O resultado é que o MESMO pick saía "Chutes no alvo, Mais de 1.5" no card e
 * "Player Shots on Target Over 1.5" na lista de resultados.
 *
 * Aqui não há decisão de layout, só a frase. Quem precisa dos dois em caixas
 * separadas (o card, o painel de detalhe) continua chamando `translateMarket`
 * e `translateLine` direto · esta função é para os lugares em que a frase cabe
 * numa linha de texto.
 */
export function rotuloDoMercado(market?: string, line?: string): string {
  const m = translateMarket(market)
  const l = translateLine(line)
  /* LINHA DE JOGADOR SE EXPLICA SOZINHA.
   *
   * "Pedro, 2 ou mais chutes no alvo" já diz quem e o quê. Com o mercado na
   * frente vira "Chutes no alvo, Pedro, 2 ou mais chutes no alvo" · a mesma
   * contagem escrita duas vezes numa linha que ainda vai ser truncada no
   * celular.
   *
   * O limiar inclusivo ("N ou mais") é a assinatura desse formato: nenhum
   * mercado de partida é escrito assim, todos usam "Mais de X.5". */
  if (l && /\d+\s+ou\s+(mais|menos)\s+\S/i.test(l)) return l
  // "--" é o que o backend manda quando o mercado do dia ainda não existe.
  const partes = [m, l].filter(t => t && t !== '--')
  return partes.join(', ')
}

/*
 * A LINHA DE UM PICK DE JOGADOR, sozinha.
 *
 * O que o motor grava em `line` é a frase inteira: "Pedro, 2 ou mais chutes no
 * alvo". Ela serve ao compartilhamento e ao ledger, onde o pick aparece fora
 * de contexto e precisa se explicar numa linha só.
 *
 * No card é o contrário: o jogador tem a foto e o nome dele em cima, e o
 * mercado tem a linha própria logo acima -- repetir os dois aqui faz o card
 * dizer "chutes no alvo" três vezes. Com `lineValue` (a coluna `line_value`,
 * que é o número puro) sai o essencial: "2 ou mais". Sem ele, tira ao menos o
 * nome do jogador da frente.
 */
export function linhaDoJogador(line?: string, lineValue?: number | null,
                               player?: string | null): string {
  if (lineValue != null) return `${lineValue} ou mais`
  const texto = translateLine(line)
  if (player && texto.toLowerCase().startsWith(player.toLowerCase())) {
    return texto.slice(player.length).replace(/^[\s,]+/, '')
  }
  return texto
}

// Seleções nacionais (Copa do Mundo etc.) vêm da API-Football em inglês --
// times de clube ja usam o mesmo nome em PT/EN, entao passam direto (fallback).
const TEAM_PT: Record<string, string> = {
  'brazil': 'Brasil', 'argentina': 'Argentina', 'germany': 'Alemanha',
  'france': 'França', 'spain': 'Espanha', 'england': 'Inglaterra',
  'italy': 'Itália', 'netherlands': 'Holanda', 'portugal': 'Portugal',
  'belgium': 'Bélgica', 'croatia': 'Croácia', 'uruguay': 'Uruguai',
  'colombia': 'Colômbia', 'mexico': 'México', 'usa': 'Estados Unidos',
  'united states': 'Estados Unidos', 'canada': 'Canadá', 'japan': 'Japão',
  'south korea': 'Coreia do Sul', 'korea republic': 'Coreia do Sul',
  'morocco': 'Marrocos', 'senegal': 'Senegal', 'ghana': 'Gana',
  'nigeria': 'Nigéria', 'cameroon': 'Camarões', 'egypt': 'Egito',
  'tunisia': 'Tunísia', 'algeria': 'Argélia', 'ivory coast': 'Costa do Marfim',
  'switzerland': 'Suíça', 'denmark': 'Dinamarca', 'sweden': 'Suécia',
  'norway': 'Noruega', 'poland': 'Polônia', 'serbia': 'Sérvia',
  'austria': 'Áustria', 'scotland': 'Escócia', 'wales': 'País de Gales',
  'ukraine': 'Ucrânia', 'turkey': 'Turquia', 'czech republic': 'República Tcheca',
  'greece': 'Grécia', 'romania': 'Romênia', 'hungary': 'Hungria',
  'ecuador': 'Equador', 'chile': 'Chile', 'peru': 'Peru',
  'paraguay': 'Paraguai', 'venezuela': 'Venezuela', 'bolivia': 'Bolívia',
  'costa rica': 'Costa Rica', 'panama': 'Panamá', 'jamaica': 'Jamaica',
  'australia': 'Austrália', 'new zealand': 'Nova Zelândia',
  'saudi arabia': 'Arábia Saudita', 'qatar': 'Catar', 'iran': 'Irã',
  'iraq': 'Iraque', 'jordan': 'Jordânia', 'china': 'China',
  'south africa': 'África do Sul', 'dr congo': 'Congo RD', 'congo dr': 'Congo RD',
  'bosnia and herzegovina': 'Bósnia e Herzegovina', 'bosnia & herzegovina': 'Bósnia e Herzegovina',
  'slovenia': 'Eslovênia', 'slovakia': 'Eslováquia', 'finland': 'Finlândia',
  'iceland': 'Islândia', 'russia': 'Rússia', 'israel': 'Israel',
  'uzbekistan': 'Uzbequistão', 'india': 'Índia',
}

export function translateTeamName(name?: string): string {
  if (!name) return ''
  return TEAM_PT[name.trim().toLowerCase()] ?? name
}
