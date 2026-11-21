import { pares } from './formato';
import styles from './AntesDespues.module.css';

/** "antes → después" of one action: each side as its "clave: valor" lines. */
export default function AntesDespues({ antes, despues }) {
  return (
    <div className={styles.cambio}>
      <ul className={styles.lado}>
        {pares(antes).map((linea) => (
          <li key={linea}>{linea}</li>
        ))}
      </ul>
      <span className={styles.flecha} aria-label="pasa a">
        →
      </span>
      <ul className={styles.lado}>
        {pares(despues).map((linea) => (
          <li key={linea}>{linea}</li>
        ))}
      </ul>
    </div>
  );
}
