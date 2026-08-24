/** @type {import('tailwindcss').Config} */

/*
 * Os tokens neutros (superficie/tinta/linha) vivem como variaveis CSS em
 * index.css e entram aqui como canais RGB, pra que o modificador de opacidade
 * do Tailwind continue funcionando: bg-surface-2/60, border-line/40 etc.
 *
 * As cores semanticas (green/red/teal/orange do resultado, yellow/blue/purple
 * do tipo de pick) tambem passaram a ser tokens, mas por outro motivo: o
 * SIGNIFICADO delas nao muda com o tema, o TOM muda. #4ade80 se le sobre
 * #0a0a0c e some sobre #ffffff. Os nomes de classe continuam os do Tailwind
 * (text-green-400, bg-yellow-400/10) de proposito, pra que a troca de tema
 * nao obrigasse a reescrever 900 lugares.
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
          // o verde da marca quando ele e' TEXTO · ver --accent-ink
          ink: token('accent-ink'),
        },
        // texto por cima de preenchimento semantico solido · ver --on-fill
        'on-fill': token('on-fill'),

        /*
         * Escala semantica. Cada tom vira variavel; o que nao esta aqui segue
         * sendo a escala fixa do Tailwind (tons ja escuros o bastante pra
         * funcionarem nos dois temas, e os usados uma vez so').
         *
         * green-500/600/700 NAO entram: e' o verde da marca, e ele e'
         * preenchimento nos dois temas. Verde como palavra usa text-accent-ink.
         */
        green: {
          300: token('c-green-300'),
          400: token('c-green-400'),
          500: '#00CC00',
          600: '#00AA00',
        },
        red: {
          300: token('c-red-300'),
          400: token('c-red-400'),
          500: token('c-red-500'),
          600: token('c-red-600'),
        },
        yellow: {
          300: token('c-yellow-300'),
          400: token('c-yellow-400'),
          500: token('c-yellow-500'),
          600: token('c-yellow-600'),
        },
        amber: {
          300: token('c-amber-300'),
          400: token('c-amber-400'),
          500: token('c-amber-500'),
        },
        orange: {
          300: token('c-orange-300'),
          400: token('c-orange-400'),
          500: token('c-orange-500'),
        },
        blue: {
          300: token('c-blue-300'),
          400: token('c-blue-400'),
          500: token('c-blue-500'),
        },
        purple: {
          300: token('c-purple-300'),
          400: token('c-purple-400'),
          500: token('c-purple-500'),
        },
        teal: {
          400: token('c-teal-400'),
          500: token('c-teal-500'),
        },
        sky: {
          400: token('c-sky-400'),
        },
        rose: {
          400: token('c-rose-400'),
          500: token('c-rose-500'),
        },
        cyan: {
          400: token('c-cyan-400'),
          500: token('c-cyan-500'),
        },
        emerald: {
          400: token('c-emerald-400'),
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
      /* Poco de preto no tema escuro, veu no claro · ver --shadow-elev */
      boxShadow: {
        elev: 'var(--shadow-elev)',
        'elev-sm': 'var(--shadow-elev-sm)',
      },
      /* Grades decorativas. O alpha vem de --grid-alpha porque verde a 5% se ve
         sobre #0a0a0c e some sobre #ffffff · ver index.css. */
      backgroundImage: {
        'field-pattern': "repeating-linear-gradient(0deg, transparent, transparent 40px, rgb(var(--accent) / calc(var(--grid-alpha) * 0.6)) 40px, rgb(var(--accent) / calc(var(--grid-alpha) * 0.6)) 41px)",
        'data-grid': "linear-gradient(rgb(var(--accent) / var(--grid-alpha)) 1px, transparent 1px), linear-gradient(90deg, rgb(var(--accent) / var(--grid-alpha)) 1px, transparent 1px)",
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
