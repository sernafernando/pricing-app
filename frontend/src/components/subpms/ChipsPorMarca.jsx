import { X } from 'lucide-react';
import styles from './ChipsPorMarca.module.css';

/**
 * ChipsPorMarca — what the selected user manages, one chip per marca
 * ("LENOVO · 12") instead of one chip per pair, so a user with dozens of
 * pairs still fits in a line or two. Removing a chip unchecks that marca's
 * pairs; it stays a pending change until the parent saves.
 *
 * `grupos` is an array of { marca, total, cambiado } sorted by the parent.
 */
export default function ChipsPorMarca({ grupos, onQuitarMarca, disabled }) {
  if (grupos.length === 0) {
    return <p className={styles.vacio}>Todavía no gestiona ningún par.</p>;
  }

  return (
    <ul className={styles.chips} aria-label="Marcas que gestiona">
      {grupos.map(({ marca, total, cambiado }) => (
        <li key={marca} className={cambiado ? styles.chipCambiado : styles.chip}>
          <span className={styles.marca}>{marca}</span>
          <span className={styles.total}>· {total}</span>
          <button
            type="button"
            className={styles.quitar}
            onClick={() => onQuitarMarca(marca)}
            disabled={disabled}
            aria-label={`Quitar ${marca}`}
          >
            <X size={12} aria-hidden="true" />
          </button>
        </li>
      ))}
    </ul>
  );
}
