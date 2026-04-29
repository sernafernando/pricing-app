/**
 * EmptyState — Mensaje "no hay datos" con personalidad.
 *
 * 3 tones:
 * - 'hero': dashed border, padding 2xl, ícono en círculo 64x64. Para containers grandes.
 * - 'inline': padding compacto, sin border. Para dentro de tablas.
 * - 'default': intermedio.
 *
 * @example
 * <EmptyState
 *   icon={<Search size={36} />}
 *   title="Buscá un proveedor"
 *   subtitle="Empezá tipeando el nombre o CUIT."
 *   tone="hero"
 *   cta={{ label: 'Crear proveedor', onClick: openModal, variant: 'primary' }}
 * />
 */

import styles from './EmptyState.module.css';

/**
 * @param {Object} props
 * @param {React.ReactNode} props.icon
 * @param {string} props.title
 * @param {string} [props.subtitle]
 * @param {{label: string, onClick: () => void, variant?: 'primary'|'secondary'}} [props.cta]
 * @param {'default'|'inline'|'hero'} [props.tone='default']
 */
export default function EmptyState({ icon, title, subtitle, cta, tone = 'default' }) {
  const toneClass =
    tone === 'hero' ? styles.hero : tone === 'inline' ? styles.inline : styles.default;

  return (
    <div className={`${styles.container} ${toneClass}`}>
      {icon && <div className={styles.icon}>{icon}</div>}
      <div className={styles.title}>{title}</div>
      {subtitle && <div className={styles.subtitle}>{subtitle}</div>}
      {cta && (
        <button
          type="button"
          onClick={cta.onClick}
          className={cta.variant === 'primary' ? styles.ctaPrimary : styles.ctaSecondary}
        >
          {cta.label}
        </button>
      )}
    </div>
  );
}
