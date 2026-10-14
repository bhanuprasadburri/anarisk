export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#F5F8FF',
        surface: '#FFFFFF',
        ink: {
          DEFAULT: '#10264F',
          700: '#1D3A6B',
          500: '#3C5A8F',
        },
        muted: '#64748B',
        faint: '#94A3B8',
        brand: {
          50: '#EEF4FF',
          100: '#DCE7FE',
          200: '#BCD0FD',
          300: '#8FB0FA',
          400: '#6391F7',
          500: '#4778F5',
          600: '#2F5CE0',
          700: '#2648B8',
          800: '#233E91',
          900: '#213772',
        },
        violet: {
          DEFAULT: '#8B5CF6',
          100: '#EFE9FE',
          200: '#DDD2FD',
          400: '#A78BFA',
          500: '#8B5CF6',
          600: '#7C3AED',
        },
        cyanx: {
          DEFAULT: '#20C5D7',
          100: '#DEF7FA',
          500: '#20C5D7',
          600: '#0EA5B7',
        },
        success: {
          DEFAULT: '#10B981',
          100: '#D9F7EC',
          500: '#10B981',
          600: '#059669',
        },
        warning: {
          DEFAULT: '#F59E0B',
          100: '#FEF0D5',
          500: '#F59E0B',
          600: '#D97706',
        },
        danger: {
          DEFAULT: '#F04464',
          100: '#FDE3E9',
          500: '#F04464',
          600: '#D92D50',
        },
        line: {
          DEFAULT: '#DCE6F5',
          soft: '#EDF2FC',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
      },
      borderRadius: {
        xl: '0.75rem',
        '2xl': '1rem',
        '3xl': '1.25rem',
      },
      boxShadow: {
        card: '0 1px 2px rgba(16,38,79,0.04), 0 4px 16px rgba(16,38,79,0.06)',
        'card-hover': '0 2px 4px rgba(16,38,79,0.05), 0 8px 28px rgba(16,38,79,0.10)',
        popover: '0 4px 24px rgba(16,38,79,0.12)',
        modal: '0 12px 48px rgba(16,38,79,0.18)',
        'inner-glow': 'inset 0 1px 0 rgba(255,255,255,0.6)',
      },
      backgroundImage: {
        'brand-gradient': 'linear-gradient(135deg, #4778F5 0%, #7C5CF6 100%)',
        'brand-gradient-soft': 'linear-gradient(135deg, #EEF4FF 0%, #F3EEFF 100%)',
        'hero-gradient':
          'linear-gradient(160deg, #10264F 0%, #2648B8 45%, #4778F5 75%, #8B5CF6 100%)',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'scale-in': {
          from: { opacity: '0', transform: 'scale(0.97)' },
          to: { opacity: '1', transform: 'scale(1)' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 0.2s ease-out',
        'scale-in': 'scale-in 0.15s ease-out',
      },
    },
  },
  plugins: [],
};
