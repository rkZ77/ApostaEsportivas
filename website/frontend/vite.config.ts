import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
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
