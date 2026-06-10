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
      backgroundImage: {
        'field-pattern': "repeating-linear-gradient(0deg, transparent, transparent 40px, rgba(0,204,0,0.03) 40px, rgba(0,204,0,0.03) 41px)",
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
}
