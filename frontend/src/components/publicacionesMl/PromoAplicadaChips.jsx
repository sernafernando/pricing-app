import { FacetChips } from '../kit';
import facetStyles from '../kit/FacetChips.module.css';

/**
 * The "Promo aplicada" filter row (auditoria-stock S9, L8): Todas / Con promo aplicada / Sin promo aplicada. With
 * the backend's counts (`facets.promo`) it is the kit's FacetChips; when they are missing (the promotions database
 * did not answer) or not in yet, the same chips read "—" / "…" instead of a false 0, and still filter.
 */
export default function PromoAplicadaChips({ options, labels, promo, loading, activeValue, onChange }) {
  const label = 'Filtrar por promo aplicada';
  if (promo) {
    return (
      <FacetChips
        label={label}
        options={options}
        labels={labels}
        counts={{ con: promo.con_promo, sin: promo.sin_promo }}
        total={promo.con_promo + promo.sin_promo}
        activeValue={activeValue}
        onChange={onChange}
      />
    );
  }
  const unknown = loading ? '…' : '—';
  const title = loading ? undefined : 'Las promociones no están disponibles ahora';
  const chip = (value, text) => (
    <button
      key={value || 'todas'}
      type="button"
      className={`${facetStyles.chip} ${activeValue === value ? facetStyles.chipActive : ''}`}
      aria-pressed={activeValue === value}
      title={title}
      onClick={() => onChange(value !== '' && activeValue === value ? '' : value)}
    >
      <span>{text}</span> <span className={facetStyles.srOnly}>·</span> <span className={facetStyles.count}>{unknown}</span>
    </button>
  );
  return (
    <div className={facetStyles.row} role="group" aria-label={label}>
      {chip('', 'Todas')}
      {options.map((value) => chip(value, labels[value] ?? value))}
    </div>
  );
}
