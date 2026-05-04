/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        navy: {
          DEFAULT: '#0F172A',
          50:  '#F0F4FF',
          100: '#D9E4FF',
          200: '#A3BBFF',
          300: '#6D92FF',
          400: '#3769FF',
          500: '#0140FF',
          600: '#0033CC',
          700: '#002699',
          800: '#0F172A',
          900: '#060C1A',
        },
        surface: '#1E293B',
        'surface-2': '#334155',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
};
