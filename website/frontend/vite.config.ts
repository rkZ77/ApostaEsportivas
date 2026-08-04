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
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-motion': ['framer-motion'],
          'vendor-net': ['axios'],
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
