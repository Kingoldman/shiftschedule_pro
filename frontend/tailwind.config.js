/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // 主色调：Element Plus 蓝色系
        slatey: {
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
        // 强调色：Element Plus 主色
        ambery: {
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
        },
        // 日期性质配色
        workday: '#909399',
        weekend: '#409eff',
        holiday: '#f56c6c',
        vacation: '#e6a23c',
      },
      fontFamily: {
        display: ['Fraunces', 'Noto Serif SC', 'serif'],
        sans: ['Plus Jakarta Sans', 'Noto Sans SC', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Consolas', 'monospace'],
      },
      boxShadow: {
        'inset-line': 'inset 0 -1px 0 0 rgba(0,0,0,0.06)',
        'amber-glow': '0 0 0 1px rgba(64,158,255,0.2), 0 4px 12px -2px rgba(64,158,255,0.15)',
      },
    },
  },
  plugins: [],
}
