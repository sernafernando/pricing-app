/**
 * TacticalPicker — the popover that adds products or invoices to a tactical line, as the approved design draws it:
 * a search box, a list of results with checkboxes ("En la línea" marks what the line already has), a count and
 * "Agregar a la línea". Escape or a click outside closes it; Enter in the search adds what is checked.
 *
 * `buscar(q)` resolves to the results; `minimo` is the shortest query it searches (0 searches on open). `fila(item)`
 * draws a result as `{ codigo, descripcion, meta, importe }`; `inicial` are the items the line already has.
 */
import { useEffect, useRef, useState } from 'react';
import styles from './TacticalPicker.module.css';

const ESPERA_MS = 300;

export default function TacticalPicker({
  titulo,
  buscarLabel,
  placeholder,
  nota,
  vacio,
  minimo = 0,
  buscar,
  claveDe,
  fila,
  inicial,
  singular,
  plural,
  onAgregar,
  onCerrar,
}) {
  const [query, setQuery] = useState('');
  const [resultados, setResultados] = useState([]);
  const [buscando, setBuscando] = useState(false);
  const [elegidos, setElegidos] = useState(() => new Map(inicial.map((item) => [claveDe(item), item])));
  const enLinea = useRef(new Set(inicial.map(claveDe)));
  const caja = useRef(null);

  useEffect(() => {
    const texto = query.trim();
    if (texto.length < minimo) {
      setResultados([]);
      return undefined;
    }
    let activo = true;
    const timer = setTimeout(() => {
      setBuscando(true);
      buscar(texto)
        .then((items) => activo && setResultados(items))
        .catch(() => activo && setResultados([]))
        .finally(() => activo && setBuscando(false));
    }, ESPERA_MS);
    return () => {
      activo = false;
      clearTimeout(timer);
    };
  }, [query, minimo, buscar]);

  // Opened on a line near the bottom it would fall below the fold: bring all of it into view, above the sticky bar.
  useEffect(() => {
    caja.current?.scrollIntoView?.({ block: 'nearest' });
  }, []);

  useEffect(() => {
    const afuera = (e) => caja.current && !caja.current.contains(e.target) && onCerrar();
    document.addEventListener('mousedown', afuera);
    return () => document.removeEventListener('mousedown', afuera);
  }, [onCerrar]);

  const alternar = (item) =>
    setElegidos((actual) => {
      const nuevo = new Map(actual);
      if (nuevo.has(claveDe(item))) nuevo.delete(claveDe(item));
      else nuevo.set(claveDe(item), item);
      return nuevo;
    });

  const agregar = () => elegidos.size && onAgregar([...elegidos.values()]);
  const n = elegidos.size;

  return (
    <div
      ref={caja}
      className={styles.picker}
      role="dialog"
      aria-label={titulo}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          onCerrar();
        }
      }}
    >
      <div className={styles.search}>
        <input
          className={styles.input}
          type="search"
          aria-label={buscarLabel}
          placeholder={placeholder}
          autoComplete="off"
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              agregar();
            }
          }}
        />
      </div>
      {nota && <p className={styles.note}>{nota}</p>}
      <div className={styles.list}>
        {resultados.map((item) => {
          const { codigo, descripcion, meta, importe } = fila(item);
          const clave = claveDe(item);
          return (
            <label key={clave} className={styles.item}>
              <input type="checkbox" checked={elegidos.has(clave)} onChange={() => alternar(item)} />
              <span className={styles.itemText}>
                <span className={styles.code}>{codigo}</span>
                <span className={styles.desc}>{descripcion}</span>
                <span className={styles.meta}>
                  {meta}
                  {enLinea.current.has(clave) && <span className={styles.tag}>En la línea</span>}
                </span>
              </span>
              {importe && <span className={styles.amount}>{importe}</span>}
            </label>
          );
        })}
        {!buscando && query.trim().length >= Math.max(minimo, 1) && resultados.length === 0 && (
          <p className={styles.empty}>{`${vacio} “${query.trim()}”.`}</p>
        )}
      </div>
      <div className={styles.foot}>
        <span className={styles.count}>
          <b>{n}</b> {n === 1 ? singular : plural}
        </span>
        <button type="button" className={styles.ghost} onClick={onCerrar}>
          Cancelar
        </button>
        <button type="button" className={styles.primary} onClick={agregar} disabled={!n}>
          Agregar a la línea
        </button>
      </div>
    </div>
  );
}
