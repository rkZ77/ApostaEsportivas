/** @type {import('tailwindcss').Config} */

/*
 * Os tokens neutros (superficie/tinta/linha) vivem como variaveis CSS em
 * index.css e entram aqui como canais RGB, pra que o modificador de opacidade
 * do Tailwind continue funcionando: bg-surface-2/60, border-line/40 etc.
 *
 * As cores semanticas (green/red/teal/orange do resultado, yellow/blue/purple
 * do tipo de pick) NAO sao tokens de tema: elas carregam significado que o
 * usuario ja aprendeu, entao seguem sendo a escala do Tailwind.
 */
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // rampa de superficie · 0 = pagina, 3 = topo da pilha
        surface: {
          0: token('surface-0'),
          1: token('surface-1'),
          2: token('surface-2'),
          3: token('surface-3'),
        },
        // rampa de tinta · 1 = primaria, 4 = desabilitada/decorativa
        ink: {
          1: token('ink-1'),
          2: token('ink-2'),
          3: token('ink-3'),
          4: token('ink-4'),
        },
        line: {
          DEFAULT: token('line'),
          strong: token('line-strong'),
        },
        accent: {
          DEFAULT: token('accent'),
          hover: token('accent-hover'),
          press: token('accent-press'),
        },
        // preservado: green-400 e o GREEN de resultado, green-500 o acento legado
        green: {
          400: '#4ade80',
          500: '#00CC00',
          600: '#00AA00',
        },
      },
      /*
       * Nunito em todo o site. `display` continua existindo como nome porque
       * ~28 lugares usam font-display, mas aponta pra mesma familia do corpo:
       * o que separa titulo de texto e peso e tamanho, nao familia.
       *
       * A pilha de fallback e a pedida: system fonts antes de cair no
       * sans-serif generico, pra que a troca de fonte nao mude o layout
       * enquanto a webfont carrega.
       *
       * A familia `mono` NAO e monoespaçada: e Inter. O nome ficou porque ~150
       * lugares usam font-mono, e o papel continua o mesmo (numero, evidencia).
       *
       * Inter resolve o que a JetBrains Mono resolvia sem parecer terminal: ela
       * tem algarismo TABULAR de verdade, e a regra em index.css liga tnum em
       * tudo que usa font-mono. Coluna de odd e de percentual continua alinhada
       * mesmo com os digitos mudando.
       */
      fontFamily: {
        display: ['Nunito', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', '"Open Sans"', '"Helvetica Neue"', 'sans-serif'],
        sans:    ['Nunito', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', '"Open Sans"', '"Helvetica Neue"', 'sans-serif'],
        mono:    ['Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
      },
      // escala de raio enxuta: 3 degraus + pilula. xl/2xl foram dobrados em lg.
      borderRadius: {
        sm: '4px',
        DEFAULT: '6px',
        md: '6px',
        lg: '10px',
        xl: '10px',
        '2xl': '10px',
      },
      transitionTimingFunction: {
        DEFAULT: 'cubic-bezier(0.2, 0, 0, 1)',
        smooth: 'cubic-bezier(0.2, 0, 0, 1)',
      },
      transitionDuration: {
        DEFAULT: '150ms',
        1: '150ms',
        2: '240ms',
      },
      boxShadow: {
        elev: '0 12px 32px rgba(0, 0, 0, 0.5)',
        'elev-sm': '0 4px 12px rgba(0, 0, 0, 0.4)',
      },
      backgroundImage: {
        'field-pattern': "repeating-linear-gradient(0deg, transparent, transparent 40px, rgba(0,204,0,0.03) 40px, rgba(0,204,0,0.03) 41px)",
        'data-grid': "linear-gradient(rgba(0,204,0,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(0,204,0,0.05) 1px, transparent 1px)",
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'marquee': 'marquee 28s linear infinite',
      },
      keyframes: {
        marquee: {
          '0%': { transform: 'translateX(0%)' },
          '100%': { transform: 'translateX(-50%)' },
        },
      },
    },
  },
  plugins: [],
}
