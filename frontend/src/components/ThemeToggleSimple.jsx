import { useTheme } from '../contexts/ThemeContext';

export default function ThemeToggleSimple() {
  const { theme, toggleTheme } = useTheme();

  return (
    <button
      onClick={toggleTheme}
      style={{
        background: 'transparent',
        border: 'none',
        color: 'var(--cf-text-secondary)',
        fontSize: '13px',
        fontWeight: 500,
        cursor: 'pointer',
        padding: 0,
        transition: 'color 150ms ease',
        textAlign: 'center',
        width: '100%',
      }}
      onMouseEnter={(e) => e.target.style.color = 'var(--cf-text-primary)'}
      onMouseLeave={(e) => e.target.style.color = 'var(--cf-text-secondary)'}
      aria-label={theme === 'light' ? 'Cambiar a modo oscuro' : 'Cambiar a modo claro'}
    >
      {theme === 'light' ? 'Modo Oscuro' : 'Modo Claro'}
    </button>
  );
}
