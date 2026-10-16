/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#0b1020',
        panel: '#141a2e',
        accent: '#5eead4',
        warn: '#fbbf24',
        danger: '#f87171',
      },
    },
  },
  plugins: [],
}
