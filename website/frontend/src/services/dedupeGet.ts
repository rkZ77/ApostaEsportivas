/*
 * Uma requisição GET igual à outra, ao mesmo tempo, vira UMA.
 *
 * O QUE ESTAVA ACONTECENDO
 * ------------------------
 * Uma visita à Minha Banca disparava, num intervalo de segundos:
 * `/banca/monthly-closes` 4 vezes, `/banca/monthly-close` 4 vezes, `/banca` 2,
 * `/banca/alavancagem-serie` 2, `/notifications` 3, `/live/my-picks` 3,
 * `/suggestions/latest-pick` 3. Não é um defeito de uma tela: são componentes
 * diferentes que precisam do mesmo dado (o modal do fechamento, a seção do
 * fechamento, a página de Fechamentos), cada um buscando o seu, mais o remonte
 * de quem navega entre as sub-páginas.
 *
 * POR QUE ISSO VIRA UM ALERTA VERMELHO
 * ------------------------------------
 * O custo de uma consulta aqui não é a consulta: é ABRIR A CONEXÃO. Medido no
 * projeto, a query roda em 0,4ms e o handshake com o Supabase leva perto de 1s.
 * Vinte e cinco requisições concorrentes viram fila, a fila estoura o timeout
 * de 15s do axios, e o interceptor mostra "O servidor demorou para responder"
 * -- enquanto o log do servidor mostra 200 em tudo, porque ele de fato
 * respondeu, só que tarde. O alerta não era falso, era o sintoma.
 *
 * O QUE ESTA CAMADA FAZ, E O QUE ELA NÃO FAZ
 * ------------------------------------------
 * Só GET, e só o que está EM VOO ou acabou de terminar (JANELA_MS). Não é
 * cache de dados: passada a janela, a próxima chamada vai à rede normalmente,
 * então nenhuma tela passa a mostrar número velho por causa daqui.
 *
 * A janela é curta de propósito. Ela cobre exatamente o caso que existe (vários
 * componentes montando na mesma tela, ou o remonte ao trocar de aba) e não
 * cobre "o usuário voltou depois de um minuto", que é quando ele QUER o número
 * atualizado.
 *
 * NUNCA entra aqui o que muda estado (POST/PUT/PATCH/DELETE) nem o que é
 * escrito para ser único por chamada. Só leitura, onde duas respostas iguais
 * no mesmo segundo são, por construção, a mesma resposta.
 */
import type { AxiosResponse } from 'axios'

/** Quanto tempo uma resposta continua servindo a chamadas idênticas. */
const JANELA_MS = 1500

type Entrada = { promessa: Promise<AxiosResponse>; em: number }

const emVoo = new Map<string, Entrada>()

export function chaveDoGet(url?: string, params?: unknown): string | null {
  if (!url) return null
  let p = ''
  try {
    // `JSON.stringify` de undefined é undefined; de objeto com ordem diferente
    // daria chaves diferentes pro mesmo pedido, então ordena.
    if (params && typeof params === 'object') {
      const o = params as Record<string, unknown>
      p = JSON.stringify(Object.keys(o).sort().map(k => [k, o[k]]))
    }
  } catch {
    return null   // params exótico: não deduplica, é o comportamento antigo
  }
  return `${url}?${p}`
}

/** Devolve a promessa compartilhada, ou registra a nova. */
export function compartilhar(
  chave: string,
  criar: () => Promise<AxiosResponse>,
): Promise<AxiosResponse> {
  const agora = Date.now()
  const atual = emVoo.get(chave)
  if (atual && agora - atual.em < JANELA_MS) return atual.promessa

  const promessa = criar()
  emVoo.set(chave, { promessa, em: agora })
  // Falha NÃO fica na janela: se a primeira quebrou, a próxima tela tem que
  // poder tentar de novo na hora, e não herdar o erro por mais um segundo.
  promessa.catch(() => emVoo.delete(chave))
  // Limpeza preguiçosa · sem timer, sem vazamento.
  if (emVoo.size > 60) {
    for (const [k, v] of emVoo) if (agora - v.em >= JANELA_MS) emVoo.delete(k)
  }
  return promessa
}

/** Esvazia a janela · usado depois de qualquer escrita. */
export function limparDedupe(): void {
  emVoo.clear()
}
