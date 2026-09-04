import { defineConfig, Plugin } from 'vite'
import react from '@vitejs/plugin-react'

/*
 * PRELOAD DOS CHUNKS DA PRIMEIRA ROTA.
 *
 * O index.html so' conhece o `index.js`. Quem sabe que a `/` precisa de
 * `Home.js` (e do PageShell, do cn, do marketTranslate que ele importa) e' o
 * proprio index.js, DEPOIS de baixar e executar. Em 4G lento isso e' uma ida e
 * volta inteira parada entre "o bundle chegou" e "o navegador descobriu o que
 * faltava" · era o que o PageSpeed mostrava como arvore de dependencia de rede
 * com tres niveis.
 *
 * Este plugin acha, no bundle pronto, o chunk de cada pagina de entrada e a
 * arvore estatica dela, e injeta os <link rel=modulepreload> no HTML. Como o
 * mesmo index.html serve TODAS as rotas do SPA, os links sao criados por um
 * script curto que olha o pathname: quem abre a `/` nao baixa o chunk do Login
 * e vice-versa.
 *
 * So' as duas rotas de entrada de verdade entram aqui. Preload e' banda
 * gasta antes da hora: listar tudo faria a Home competir consigo mesma.
 */
function preloadDaRota(): Plugin {
  const ROTAS: Record<string, string> = {
    '/':      'src/pages/Home.tsx',
    '/login': 'src/pages/Login.tsx',
  }

  return {
    name: 'preload-da-rota',
    enforce: 'post',
    transformIndexHtml: {
      order: 'post',
      handler(html, ctx) {
        if (!ctx.bundle) return html

        // Fecho transitivo dos imports ESTATICOS do chunk · sao exatamente os
        // que o navegador pediria em seguida de qualquer jeito. Os dinamicos
        // ficam de fora: sao o que a pagina busca sob demanda depois.
        const arvore = (nome: string, visto = new Set<string>()): string[] => {
          const chunk = ctx.bundle![nome]
          if (!chunk || chunk.type !== 'chunk' || visto.has(nome)) return []
          visto.add(nome)
          return [nome, ...chunk.imports.flatMap((i) => arvore(i, visto))]
        }

        // O que o index.html ja' traz sozinho nao precisa ser repetido.
        const jaNoHtml = new Set(
          [...html.matchAll(/(?:src|href)="\/([^"]+\.js)"/g)].map((m) => m[1]),
        )

        const mapa: Record<string, string[]> = {}
        for (const [rota, fonte] of Object.entries(ROTAS)) {
          const entrada = Object.values(ctx.bundle).find(
            (c) =>
              c.type === 'chunk' &&
              // No Windows o facadeModuleId vem com barra invertida.
              c.facadeModuleId?.replace(/\\/g, '/').endsWith(fonte),
          )
          if (!entrada || entrada.type !== 'chunk') continue
          const arquivos = [...new Set(arvore(entrada.fileName))].filter(
            (f) => !jaNoHtml.has(f),
          )
          if (arquivos.length) mapa[rota] = arquivos
        }

        if (!Object.keys(mapa).length) return html

        return {
          html,
          tags: [
            {
              tag: 'script',
              injectTo: 'head',
              /*
               * DEPOIS DO PRIMEIRO PAINT, E NAO NA HORA.
               *
               * `modulepreload` e' pedido de prioridade ALTA. Disparado no
               * head, ele disputa banda com o CSS · que e' bloqueante · e com
               * a fonte, e em 4G lento adia justamente o quadro que ele
               * deveria adiantar. Medido em 04/09: com os preloads imediatos,
               * FCP de 5,0s; o texto do hero ja estava no DOM em 500ms e
               * esperava so' o CSS que ficou na fila atras deles.
               *
               * O rAF duplo espera o primeiro quadro pintado (que so'
               * acontece depois do CSS chegar). Dai em diante a banda e'
               * toda do JavaScript, e a cascata que este plugin existe pra
               * evitar continua evitada.
               */
              children:
                `(function(){var m=${JSON.stringify(mapa)}[location.pathname];if(!m)return;` +
                `function p(){for(var i=0;i<m.length;i++){var l=document.createElement('link');` +
                `l.rel='modulepreload';l.crossOrigin='';l.href='/'+m[i];document.head.appendChild(l)}}` +
                `requestAnimationFrame(function(){requestAnimationFrame(p)})})()`,
            },
          ],
        }
      },
    },
  }
}

export default defineConfig({
  plugins: [react(), preloadDaRota()],
  build: {
    rollupOptions: {
      output: {
        /*
         * Separa as dependências do código do app.
         *
         * Sem isto tudo caía num chunk `index` de ~400 KB: a cada deploy o
         * hash mudava e o usuário rebaixava React, o router, o framer e o
         * axios de novo, mesmo sem nenhum deles ter mudado. Quebrado assim,
         * um deploy normal invalida só o chunk do app.
         *
         * Os grupos seguem o ciclo de atualização de cada um, não o tamanho:
         * juntar framer com react faria uma atualização do framer derrubar o
         * cache do react junto.
         */
        /*
         * POR QUE ISTO É FUNÇÃO E NÃO O OBJETO DE ANTES.
         *
         * Com a forma de objeto (`{'vendor-react': ['react', ...]}`), o
         * `react/jsx-runtime` NÃO caía em vendor-react · ele é um módulo
         * separado de `react` pro Rollup, e listá-lo por nome também não
         * resolvia. Quem o importava primeiro era o framer-motion, então ele
         * era engolido pelo `vendor-motion`.
         *
         * Consequência, medida no build de 14/08: TODO chunk que renderiza JSX
         * passava a importar `vendor-motion`, e o index.html trazia um
         * `modulepreload` dele. Termos, Privacidade, TeamLogo, Badge, Skeleton:
         * nenhum anima nada, e todos carregavam os 43,8 KB comprimidos do
         * framer antes do primeiro pixel. Não adiantava tirar o framer do topo
         * do App.tsx · a dependência real era o jsx-runtime, não a animação.
         *
         * Decidir por CAMINHO resolve porque `react/jsx-runtime.js` mora dentro
         * de `node_modules/react/`, então cai na mesma regra que o `react`.
         */
        manualChunks(id) {
          const p = id.replace(/\\/g, '/')
          if (!p.includes('/node_modules/')) return
          // scheduler é dependência interna do react-dom; junto evita um chunk
          // solto de 5 KB que sempre viaja com o react mesmo.
          if (/\/node_modules\/(react|react-dom|react-router|react-router-dom|scheduler)\//.test(p)) return 'vendor-react'
          // motion-dom e motion-utils são pacotes irmãos publicados pelo framer.
          if (/\/node_modules\/(framer-motion|motion-dom|motion-utils)\//.test(p)) return 'vendor-motion'
          if (/\/node_modules\/axios\//.test(p)) return 'vendor-net'
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api':    'http://localhost:8000',
      '/static': 'http://localhost:8000',
    },
  },
})
