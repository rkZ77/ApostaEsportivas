/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        green: {
          400: '#4ade80',
          500: '#00CC00',
          600: '#00AA00',
        },
      },
      fontFamily: {
        display: ['"Space Grotesk"', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
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
