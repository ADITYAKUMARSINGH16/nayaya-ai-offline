/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Judicial palette — deep ink + warm gold
        ink: {
          50:  '#f5f6fa',
          100: '#e6e8f0',
          200: '#c7cbdc',
          300: '#9aa1bd',
          400: '#5b6494',
          500: '#3a4275',
          600: '#252c5c',
          700: '#181d44',
          800: '#0f1331',
          900: '#080a1f',
          950: '#03050f',
        },
        gold: {
          50:  '#fdf9ee',
          100: '#faf0cf',
          200: '#f4dd92',
          300: '#edc659',
          400: '#e6b22d',
          500: '#c8951f',
          600: '#a07219',
          700: '#7d5717',
          800: '#5a3e15',
          900: '#3d2a10',
        },
        accent: {
          DEFAULT: '#e6b22d',
          soft: '#f4dd92',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        serif: ['"Cormorant Garamond"', 'ui-serif', 'Georgia', 'serif'],
      },
      boxShadow: {
        glow: '0 0 0 1px rgba(230,178,45,0.15), 0 8px 30px rgba(0,0,0,0.45)',
        card: '0 1px 0 rgba(255,255,255,0.04) inset, 0 12px 40px rgba(0,0,0,0.35)',
      },
      backgroundImage: {
        'grid-soft': 'radial-gradient(rgba(230,178,45,0.08) 1px, transparent 1px)',
        'noise': 'url("data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22120%22 height=%22120%22><filter id=%22n%22><feTurbulence baseFrequency=%220.9%22/><feColorMatrix values=%220 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.04 0%22/></filter><rect width=%22100%22 height=%22100%22 filter=%22url(%23n)%22/></svg>")',
      },
      animation: {
        'fade-in': 'fadein 0.4s ease-out both',
        'slide-up': 'slideup 0.5s cubic-bezier(0.16,1,0.3,1) both',
      },
      keyframes: {
        fadein: { '0%': { opacity: 0 }, '100%': { opacity: 1 } },
        slideup: { '0%': { opacity: 0, transform: 'translateY(8px)' }, '100%': { opacity: 1, transform: 'translateY(0)' } },
      },
    },
  },
  plugins: [],
}
