/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ctp: Object.fromEntries(['rosewater','flamingo','pink','mauve','red','maroon','peach','yellow','green','teal','sky','sapphire','blue','lavender','text','subtext1','subtext0','overlay2','overlay1','overlay0','surface2','surface1','surface0','base','mantle','crust'].map(k=>[k,`rgb(var(--ctp-${k}) / <alpha-value>)`])),
        app: {
          bg: 'rgb(var(--app-bg) / <alpha-value>)',
          bgSecondary: 'rgb(var(--app-bg-secondary) / <alpha-value>)',
          bgTertiary: 'rgb(var(--app-bg-tertiary) / <alpha-value>)',
          surface: 'rgb(var(--app-surface) / <alpha-value>)',
          surfaceRaised: 'rgb(var(--app-surface-raised) / <alpha-value>)',
          surfaceActive: 'rgb(var(--app-surface-active) / <alpha-value>)',
          border: 'rgb(var(--app-border) / <alpha-value>)',
          borderMuted: 'rgb(var(--app-border-muted) / <alpha-value>)',
          text: 'rgb(var(--app-text) / <alpha-value>)',
          textMuted: 'rgb(var(--app-text-muted) / <alpha-value>)',
          textSubtle: 'rgb(var(--app-text-subtle) / <alpha-value>)',
          textDisabled: 'rgb(var(--app-text-disabled) / <alpha-value>)',
          primary: 'rgb(var(--app-primary) / <alpha-value>)',
          primaryHover: 'rgb(var(--app-primary-hover) / <alpha-value>)',
          focus: 'rgb(var(--app-focus) / <alpha-value>)',
          success: 'rgb(var(--app-success) / <alpha-value>)',
          warning: 'rgb(var(--app-warning) / <alpha-value>)',
          danger: 'rgb(var(--app-danger) / <alpha-value>)',
          accent: 'rgb(var(--app-accent) / <alpha-value>)',
        },
      },
    },
  },
  plugins: [],
};
