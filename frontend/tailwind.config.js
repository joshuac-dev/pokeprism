/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: 'rgb(15 23 42)',   // slate-950
          raised: 'rgb(30 41 59)',    // slate-800
          border: 'rgb(51 65 85)',    // slate-700
        },
      },
    },
  },
  plugins: [],
};
