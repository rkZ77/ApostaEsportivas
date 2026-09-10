import { useEffect, useState } from 'react'
import api from '../services/api'

/*
 * A ODD DE AGORA, PARA TODOS OS CARDS DE UMA VEZ.
 *
 * O card mostrava a odd da PUBLICAÇÃO, e a odd corrente só aparecia depois do
 * clique em "Pegar bilhete", dentro do modal. Quem estava decidindo via um
 * número que podia ter mudado horas antes, e descobria a mudança no pior
 * momento: com a decisão já tomada.
 *
 * UMA CHAMADA PARA A TELA INTEIRA, e não uma por card. Cada card pedindo a
 * própria odd seria uma requisição à casa por pick e por visita, e é assim que
 * se estoura a cota da API (foi o que aconteceu em 01/08 e custou o agendador
 * do projeto). A rota devolve o mapa inteiro em lote e guarda a leitura em
 * cache no servidor, então a centésima visita do dia não custa nada.
 *
 * O MÓDULO TAMBÉM SEGURA A SUA CÓPIA. Cinco componentes usam este hook na
 * mesma tela; sem isto seriam cinco requisições iguais no mesmo segundo.
 */

export interface OddAgora {
  odd: number
  odd_pick: number | null
  variacao: number
  casa: string | null
}

/** Uma requisição por sessão de tela, compartilhada por todos os cards. */
let promessa: Promise<Record<string, OddAgora>> | null = null
let cache: { ts: number; dados: Record<string, OddAgora> } | null = null

/* O servidor já guarda a leitura por 15 minutos. Aqui a validade é menor de
   propósito: quem deixa a aba aberta a tarde inteira volta a perguntar de vez
   em quando, e a resposta sai do cache do servidor quando não há nada novo. */
const VALIDADE_MS = 5 * 60 * 1000

function buscar(): Promise<Record<string, OddAgora>> {
  if (cache && Date.now() - cache.ts < VALIDADE_MS) return Promise.resolve(cache.dados)
  if (promessa) return promessa
  promessa = api.get('/suggestions/odds-agora')
    .then(r => {
      const dados = (r.data?.picks ?? {}) as Record<string, OddAgora>
      cache = { ts: Date.now(), dados }
      return dados
    })
    /* Falhou: o card segue com a odd da publicação, que é o comportamento de
       sempre. Odd de vitrine nunca pode derrubar a tela. */
    .catch(() => ({} as Record<string, OddAgora>))
    .finally(() => { promessa = null })
  return promessa
}

/**
 * Odd corrente de um pick, ou null quando não há leitura para ele.
 *
 * `congelado` desliga a busca: depois que a pessoa pega o bilhete, a odd dela
 * está registrada e ficar mexendo naquele número seria mentir sobre a aposta
 * que ela tem. Dali em diante quem continua andando na tela é a leitura do
 * jogo, não o preço.
 */
export function useOddAgora(
  pickType: string | null | undefined,
  pickId: number | null | undefined,
  congelado = false,
): OddAgora | null {
  const [odd, setOdd] = useState<OddAgora | null>(null)
  const chave = pickType && pickId != null ? `${pickType}:${pickId}` : null

  useEffect(() => {
    if (!chave || congelado) { setOdd(null); return }
    let vivo = true
    buscar().then(m => { if (vivo) setOdd(m[chave] ?? null) })
    return () => { vivo = false }
  }, [chave, congelado])

  return odd
}
