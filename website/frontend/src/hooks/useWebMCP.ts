import { useEffect } from 'react'

/*
 * WebMCP: ferramentas que um agente rodando DENTRO do navegador pode chamar.
 *
 * A API é `navigator.modelContext`, do rascunho de Community Group do W3C
 * (Web Machine Learning CG, abril de 2026). Ela não é padrão fechado e hoje
 * só existe em Edge e num teste de origem do Chrome · por isso tudo aqui é
 * detecção de recurso, e navegador sem suporte não paga nada além de um `if`.
 *
 * POR QUE NÃO REPETE O SERVIDOR MCP. O de `/mcp` (backend/agent_web.py) é
 * anônimo e público. Este roda na aba do usuário, com a sessão dele. A
 * tentação é justamente aproveitar isso pra expor pick de assinante ao
 * agente, e a resposta é não: o que sai daqui é o mesmo que sai pra visitante
 * sem conta. Conteúdo pago que passa por ferramenta de agente vira conteúdo
 * copiável, e a assinatura é o produto.
 *
 * As ferramentas de navegação existem porque são a única coisa que o servidor
 * MCP não consegue fazer: mudar a tela que a pessoa está olhando.
 */

interface FerramentaWebMCP {
  name: string
  description: string
  inputSchema: Record<string, unknown>
  execute: (args: Record<string, unknown>) => Promise<{ content: Array<{ type: string; text: string }> }>
}

interface ContextoDeModelo {
  registerTool?: (ferramenta: FerramentaWebMCP) => void
  unregisterTool?: (nome: string) => void
}

const SEM_ARGUMENTO = { type: 'object', properties: {}, additionalProperties: false }

function texto(conteudo: unknown) {
  return {
    content: [
      { type: 'text', text: typeof conteudo === 'string' ? conteudo : JSON.stringify(conteudo, null, 2) },
    ],
  }
}

async function buscar(caminho: string) {
  const r = await fetch(caminho, { headers: { Accept: 'application/json' } })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

export function useWebMCP(navegar: (rota: string) => void) {
  useEffect(() => {
    const contexto = (navigator as unknown as { modelContext?: ContextoDeModelo }).modelContext
    if (!contexto || typeof contexto.registerTool !== 'function') return

    const ferramentas: FerramentaWebMCP[] = [
      {
        name: 'pickia_resultados_publicos',
        description:
          'Desempenho consolidado dos picks já resolvidos do Pick IA: total, acertos, lucro em unidades e ROI. Dado público, igual ao da página de Resultados.',
        inputSchema: SEM_ARGUMENTO,
        execute: async () => {
          const dados = await buscar('/api/public/results?slim=1')
          return texto({
            resumo: dados?.summary ?? {},
            por_tipo: dados?.by_source ?? [],
            aviso: 'Desempenho passado não prevê resultado futuro.',
          })
        },
      },
      {
        name: 'pickia_dica_gratuita_de_hoje',
        description:
          'A dica gratuita do dia. Sem conta, o mercado volta bloqueado · é a mesma regra da página pública.',
        inputSchema: SEM_ARGUMENTO,
        execute: async () => texto(await buscar('/api/public/free-pick-today')),
      },
      {
        name: 'pickia_planos_e_precos',
        description: 'Planos de assinatura do Pick IA, com preço e período.',
        inputSchema: SEM_ARGUMENTO,
        execute: async () => texto(await buscar('/api/payments/plans')),
      },
      {
        name: 'pickia_abrir_pagina',
        description:
          'Abre uma página pública do Pick IA na aba atual. Só aceita as rotas listadas.',
        inputSchema: {
          type: 'object',
          properties: {
            pagina: {
              type: 'string',
              enum: ['inicio', 'planos', 'resultados', 'como-funciona', 'blog'],
              description: 'Qual página abrir.',
            },
          },
          required: ['pagina'],
          additionalProperties: false,
        },
        execute: async (args) => {
          // Lista fechada de propósito. Aceitar caminho livre daria a um
          // agente a chance de empurrar a aba pra /admin ou pra um link de
          // fora, e navegação é a única ferramenta daqui que muda o que a
          // pessoa está vendo.
          const rotas: Record<string, string> = {
            inicio: '/',
            planos: '/planos',
            resultados: '/resultados',
            'como-funciona': '/como-funciona',
            blog: '/blog',
          }
          const destino = rotas[String(args?.pagina ?? '')]
          if (!destino) return texto('Página desconhecida.')
          navegar(destino)
          return texto(`Abri ${destino}.`)
        },
      },
    ]

    for (const ferramenta of ferramentas) {
      try {
        contexto.registerTool(ferramenta)
      } catch {
        /* navegador com a API pela metade não pode derrubar a tela */
      }
    }

    return () => {
      for (const ferramenta of ferramentas) {
        try {
          contexto.unregisterTool?.(ferramenta.name)
        } catch {
          /* idem */
        }
      }
    }
  }, [navegar])
}
