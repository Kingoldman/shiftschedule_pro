/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // 覆盖 Tailwind 默认 blue 色板为 Element Plus 主色系
        // 这样所有 blue-xxx 工具类自动与 Element Plus #409eff 保持一致
        blue: {
          50: '#ecf5ff',
          100: '#d9ecff',
          200: '#b3d8ff',
          300: '#8cc5ff',
          400: '#66b1ff',
          500: '#409eff',
          600: '#3a8ee6',
          700: '#337ecc',
          800: '#2c6eb5',
          900: '#1d4e89',
          950: '#0c3667',
        },
      },
      fontFamily: {
        display: ['Fraunces', 'Noto Serif SC', 'serif'],
        sans: ['Plus Jakarta Sans', 'Noto Sans SC', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}
