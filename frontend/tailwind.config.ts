import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        ink: '#17202a',
        line: '#d9dee7',
        paper: '#f7f9fc',
        brand: '#246b8f',
        accent: '#c96f34'
      }
    }
  },
  plugins: []
} satisfies Config

