import styles from './IncludeToggles.module.css';

/**
 * ventas-ml-kpi-strip T4/T5: the four `include_*` switches the backend's
 * `SalesFilter` accepts (`ml_ventas_ops.py`). This component ONLY renders
 * state handed to it and reports a toggle by KEY — `VentasML.jsx` owns the
 * actual state and is the one place that fans a change out to BOTH the
 * list and the KPI request (T5 parity is a caller responsibility, not
 * this component's).
 *
 * `excludedByToggle` badges (`SalesKpiResponse.excluded_by_toggle`) are
 * shown ONLY for a toggle that is currently OFF — the backend itself
 * always reports `0` for an ON toggle (its own docstring), so showing the
 * badge regardless would read as "this hides 0 groups", which is not what
 * an ON toggle means.
 */
const TOGGLE_DEFS = [
  { key: 'includeUnknown', excludedKey: 'a_revisar', label: 'A revisar' },
  { key: 'includeInDispute', excludedKey: 'en_disputa', label: 'En disputa' },
  { key: 'includeMixed', excludedKey: 'mixta', label: 'Mixta' },
  { key: 'includeProvisional', excludedKey: 'provisorio', label: 'Provisorio' },
];

export default function IncludeToggles({ values, excludedByToggle, onChange }) {
  return (
    <div className={styles.toggles}>
      {TOGGLE_DEFS.map(({ key, excludedKey, label }) => {
        const checked = Boolean(values?.[key]);
        const excludedCount = excludedByToggle?.[excludedKey] ?? 0;
        return (
          <label key={key} className={styles.toggle}>
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => onChange(key, e.target.checked)}
            />
            <span>{label}</span>
            {!checked && excludedCount > 0 && (
              <span className={styles.excludedBadge} title={`Ocultando ${excludedCount} grupos`}>
                +{excludedCount}
              </span>
            )}
          </label>
        );
      })}
    </div>
  );
}
