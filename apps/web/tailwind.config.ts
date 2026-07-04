import type { Config } from 'tailwindcss';

export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Surface tiers
        background: 'var(--bg)',
        bg: 'var(--bg)',
        surface: 'var(--surface)',
        'surface-elevated': 'var(--surface-elevated)',
        'surface-overlay': 'var(--surface-overlay)',
        border: 'var(--border)',
        'border-strong': 'var(--border-strong)',
        // Control fill tier for form inputs (Batch 52)
        control: 'var(--control)',
        'control-border': 'var(--control-border)',

        // Text
        'text-primary': 'var(--text-primary)',
        'text-secondary': 'var(--text-secondary)',
        'text-muted': 'var(--text-muted)',
        'text-inverse': 'var(--text-inverse)',
        // On-brand text (locked dark across themes — see index.css)
        'on-primary': 'var(--on-primary)',
        'on-accent': 'var(--on-accent)',

        // Brand
        primary: {
          DEFAULT: 'var(--primary)',
          dark: 'var(--primary-dark)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          dark: 'var(--accent-dark)',
        },
        steele: {
          DEFAULT: 'var(--steele)',
          mid: 'var(--steele-mid)',
          dark: 'var(--steele-dark)',
        },

        // Semantic
        success: 'var(--success)',
        warning: 'var(--warning)',
        error: 'var(--error)',
        locked: 'var(--locked)',
        live: 'var(--live)',

        // Rank medals
        gold: 'var(--gold)',
        silver: 'var(--silver)',
        bronze: 'var(--bronze)',
      },
      fontFamily: {
        sans: ['Outfit', 'system-ui', 'sans-serif'],
        // `font-display` aliases to Outfit so legacy heading/numeric usages
        // remain readable. The Brand wordmark uses `font-mono` directly.
        display: ['Outfit', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      borderRadius: {
        xs: 'var(--radius-xs)',
        sm: 'var(--radius-sm)',
        DEFAULT: 'var(--radius-md)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        xl: 'var(--radius-xl)',
        '2xl': 'var(--radius-2xl)',
      },
      boxShadow: {
        sm: 'var(--shadow-sm)',
        DEFAULT: 'var(--shadow-md)',
        md: 'var(--shadow-md)',
        lg: 'var(--shadow-lg)',
        sheet: 'var(--shadow-sheet)',
        glow: 'var(--shadow-glow)',
        'glow-accent': 'var(--shadow-glow-accent)',
      },
      borderColor: {
        DEFAULT: 'var(--border)',
      },
      backgroundColor: {
        DEFAULT: 'var(--bg)',
      },
      transitionTimingFunction: {
        'out-quart': 'cubic-bezier(0.2, 0, 0, 1)',
      },
      transitionDuration: {
        fast: '150ms',
        base: '220ms',
        page: '280ms',
        sheet: '320ms',
      },
      zIndex: {
        tabbar: '40',
        header: '50',
        banner: '55',
        sheet: '60',
        modal: '70',
        toast: '80',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
} satisfies Config;
