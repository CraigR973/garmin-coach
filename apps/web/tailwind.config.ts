import type { Config } from 'tailwindcss';

export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontSize: {
        // Batch 254 (UX241-12). The app had 26 hard-coded `text-[10px]` /
        // `text-[11px]` utilities — literal pixel values that ignore the reader's
        // text-size setting entirely, on an app read every morning by a
        // 61-year-old. Body text is `text-sm` and rem-based, so raising the phone's
        // text size grew the body and left these behind: the gap widened rather
        // than closed. These two rem tokens replace them, and the smaller is
        // deliberately no smaller than 0.6875rem (11px at default) — the 10px
        // eyebrows, combined with `tracking-[0.3em]` and `text-text-muted`, were
        // the least legible text in the app, and one of them was the date.
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
        '3xs': ['0.625rem', { lineHeight: '0.875rem' }],
      },
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
          text: 'var(--primary-text)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          dark: 'var(--accent-dark)',
          text: 'var(--accent-text)',
        },
        steele: {
          DEFAULT: 'var(--steele)',
          mid: 'var(--steele-mid)',
          dark: 'var(--steele-dark)',
        },

        // Semantic
        success: {
          DEFAULT: 'var(--success)',
          text: 'var(--success-text)',
        },
        warning: {
          DEFAULT: 'var(--warning)',
          text: 'var(--warning-text)',
        },
        error: {
          DEFAULT: 'var(--error)',
          text: 'var(--error-text)',
        },
        locked: 'var(--locked)',
        live: {
          DEFAULT: 'var(--live)',
          text: 'var(--live-text)',
        },

        // Rank medals
        gold: {
          DEFAULT: 'var(--gold)',
          text: 'var(--gold-text)',
        },
        silver: {
          DEFAULT: 'var(--silver)',
          text: 'var(--silver-text)',
        },
        bronze: {
          DEFAULT: 'var(--bronze)',
          text: 'var(--bronze-text)',
        },
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
