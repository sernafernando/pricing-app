/**
 * Multi-select store/channel context for Productos sell-in/out companions.
 * Independent of the listing's "Tienda Oficial" product filter.
 */
import { useState } from 'react';
import styles from './MarkupContextoPicker.module.css';
import { CANALES_TACTICAL } from './markupContextos';

export default function MarkupContextoPicker({
  grupos = [],
  todas = true,
  keys = [],
  onChange,
}) {
  // Unticking Todas with nothing picked yet sends no context (the read stays global), so the parent's state still
  // says Todas: the picker remembers it is choosing, so the stores stay open until Todas is ticked again.
  const [eligiendo, setEligiendo] = useState(false);
  const mostrarTodas = todas && !eligiendo;
  const toggleKey = (key) => {
    const next = keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key];
    setEligiendo(true);
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
            checked={mostrarTodas}
            onChange={(e) => {
              setEligiendo(!e.target.checked);
              onChange({
                todas: e.target.checked,
                keys: e.target.checked
                  ? keys.filter((k) => CANALES_TACTICAL.some((c) => c.value === k))
                  : keys,
              });
            }}
          />
          <span>Todas (como hoy)</span>
        </label>
        {!mostrarTodas &&
          grupos.map((g) => (
            <label key={g.value} className={styles.check}>
              <input type="checkbox" checked={keys.includes(g.value)} onChange={() => toggleKey(g.value)} />
              <span>{g.label}</span>
            </label>
          ))}
        {!mostrarTodas &&
          keys
            .filter((k) => !CANALES_TACTICAL.some((c) => c.value === k) && !grupos.some((g) => g.value === k))
            .map((k) => (
              // A store from the URL that no whole group covers: shown so it can be unticked, never hidden.
              <label key={k} className={styles.check}>
                <input type="checkbox" checked onChange={() => toggleKey(k)} />
                <span>{`Tienda ${k}`}</span>
              </label>
            ))}
        {CANALES_TACTICAL.map((c) => (
          <label key={c.value} className={styles.check}>
            <input type="checkbox" checked={keys.includes(c.value)} onChange={() => toggleKey(c.value)} />
            <span>{c.label}</span>
          </label>
        ))}
      </div>
      {!mostrarTodas && keys.length === 0 && (
        <p className={styles.ayuda}>Elegí al menos una tienda o canal; mientras tanto se ve como Todas.</p>
      )}
      <p className={styles.ayuda}>
        Unión: un tactical entra si aplica a alguna tienda o canal elegido. No filtra el listado.
      </p>
    </div>
  );
}
