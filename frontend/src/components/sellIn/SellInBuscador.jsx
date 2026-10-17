import { useEffect, useState } from 'react';
import SearchInput from '../SearchInput';
import styles from './SellInPanel.module.css';

/**
 * A search box with its results as buttons: typing asks `buscar(texto)` for
 * `[{ key, label, sub }]`, picking one calls `onPick` and clears the box.
 * A failed search lists nothing and says so (`errorMessage`).
 */
export default function SellInBuscador({ label, placeholder, buscar, onPick, errorMessage = 'No se pudo buscar.' }) {
  const [texto, setTexto] = useState('');
  const [resultados, setResultados] = useState([]);
  const [error, setError] = useState(false);

  useEffect(() => {
    const query = texto.trim();
    if (!query) {
      setResultados([]);
      setError(false);
      return undefined;
    }
    let active = true;
    buscar(query)
      .then((opciones) => {
        if (!active) return;
        setResultados(opciones);
        setError(false);
      })
      .catch(() => {
        if (!active) return;
        setResultados([]);
        setError(true);
      });
    return () => {
      active = false;
    };
    // `buscar` is a fresh closure every render; the request depends on the text only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [texto]);

  const pick = (opcion) => {
    onPick(opcion);
    setTexto('');
    setResultados([]);
  };

  return (
    <div className={styles.buscador} role="group" aria-label={label}>
      <SearchInput value={texto} onChange={setTexto} debounce={300} placeholder={placeholder} size="sm" />
      {error && <p className={styles.hint}>{errorMessage}</p>}
      {resultados.length > 0 && (
        <ul className={styles.resultados}>
          {resultados.map((opcion) => (
            <li key={opcion.key}>
              <button type="button" className={styles.resultado} onClick={() => pick(opcion)}>
                <span>{opcion.label}</span>
                {opcion.sub && <span className={styles.resultadoSub}>{opcion.sub}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
