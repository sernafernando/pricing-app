/**
 * Multi-select store/channel context for Productos sell-in/out companions.
 * Independent of the listing's "Tienda Oficial" product filter.
 */
import styles from './MarkupContextoPicker.module.css';
import { CANALES_TACTICAL } from './markupContextos';

export default function MarkupContextoPicker({
  grupos = [],
  todas = true,
  keys = [],
  onChange,
}) {
  const toggleKey = (key) => {
    const next = keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key];
    onChange({ todas: false, keys: next });
  };

  return (
    <div className={styles.wrap} data-testid="markup-contexto-picker">
      <span className={styles.lbl} id="markup-contexto-label">
        Contexto de markup (tacticals)
      </span>
      <div className={styles.checks} role="group" aria-labelledby="markup-contexto-label">
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={todas}
            onChange={(e) =>
              onChange({
                todas: e.target.checked,
                keys: e.target.checked
                  ? keys.filter((k) => CANALES_TACTICAL.some((c) => c.value === k))
                  : keys,
              })
            }
          />
          <span>Todas (como hoy)</span>
        </label>
        {!todas &&
          grupos.map((g) => (
            <label key={g.value} className={styles.check}>
              <input type="checkbox" checked={keys.includes(g.value)} onChange={() => toggleKey(g.value)} />
              <span>{g.label}</span>
            </label>
          ))}
        {CANALES_TACTICAL.map((c) => (
          <label key={c.value} className={styles.check}>
            <input type="checkbox" checked={keys.includes(c.value)} onChange={() => toggleKey(c.value)} />
            <span>{c.label}</span>
          </label>
        ))}
      </div>
      <p className={styles.ayuda}>
        Unión: un tactical entra si aplica a alguna tienda o canal elegido. No filtra el listado.
      </p>
    </div>
  );
}
