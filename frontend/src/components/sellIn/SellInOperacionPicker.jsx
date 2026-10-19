import { useEffect, useId, useRef, useState } from 'react';
import { sellInAPI } from '../../services/sellInAPI';
import { formatDateOnly } from '../../utils/dateUtils';
import EstadoBadge from '../compras/_shared/EstadoBadge';
import { formatMonto } from './sellInFormat';
import styles from './SellInPanel.module.css';

const DEBOUNCE_MS = 250;

const esExacta = (operacion, texto) =>
  String(operacion.id) === texto || operacion.numero.toLowerCase() === texto.toLowerCase();

/**
 * Searchable picker of Compras operations (`GET /sell-in/compras/operaciones`) for the create panel:
 * a combobox whose list shows what the Compras list shows of each operation (number, supplier, date,
 * total in its currency, estado, invoice), newest first. Focusing it offers the newest ones; typing
 * narrows them (debounced). Arrow keys and Enter pick, Escape closes; Enter with nothing highlighted
 * adds the typed number directly when exactly one operation has it, as the old number box did.
 *
 * `restriccion` ({ proveedorId, proveedorNombre, moneda }) narrows the search server-side to the
 * operations a sell in may still combine (one supplier, one currency); `excluir` are the linked ones.
 */
export default function SellInOperacionPicker({ label, excluir, restriccion, deshabilitado = false, onPick }) {
  const id = useId();
  const listId = `${id}-lista`;
  const [texto, setTexto] = useState('');
  const [abierto, setAbierto] = useState(false);
  const [opciones, setOpciones] = useState([]);
  const [cargado, setCargado] = useState(false);
  const [activo, setActivo] = useState(-1);
  const [error, setError] = useState(false);
  const textoRef = useRef(texto);
  textoRef.current = texto;

  const parametros = (q) => ({
    q,
    excluir,
    ...(restriccion ? { proveedor_id: restriccion.proveedorId, moneda: restriccion.moneda } : {}),
  });
  const filtros = JSON.stringify([excluir, restriccion?.proveedorId, restriccion?.moneda]);

  useEffect(() => {
    if (!abierto) return undefined;
    let active = true;
    const timer = setTimeout(() => {
      sellInAPI
        .operaciones(parametros(texto.trim()))
        .then(({ data }) => {
          if (!active) return;
          setOpciones(data.items);
          setActivo(-1);
          setError(false);
          setCargado(true);
        })
        .catch(() => {
          if (!active) return;
          setOpciones([]);
          setError(true);
          setCargado(true);
        });
    }, DEBOUNCE_MS);
    return () => {
      active = false;
      clearTimeout(timer);
    };
    // `parametros` is a fresh closure every render; the request depends on the text and `filtros` only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [abierto, texto, filtros]);

  const cerrar = () => {
    setAbierto(false);
    setError(false);
    setCargado(false);
    setActivo(-1);
  };
  const elegir = (operacion) => {
    onPick(operacion);
    setTexto('');
    setOpciones([]);
    cerrar();
  };
  /** The old fast path: a typed number that exactly one operation has is added without opening the list. */
  const elegirTipeada = async () => {
    const q = texto.trim();
    if (!q) return;
    try {
      const { data } = await sellInAPI.operaciones(parametros(q));
      const exactas = data.items.filter((operacion) => esExacta(operacion, q));
      if (exactas.length === 1 && textoRef.current.trim() === q) elegir(exactas[0]);
    } catch {
      setError(true);
    }
  };

  const onKeyDown = (e) => {
    const visibles = abierto && cargado ? opciones : [];
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!abierto) setAbierto(true);
      if (visibles.length === 0) return;
      const paso = e.key === 'ArrowDown' ? 1 : -1;
      setActivo((prev) => (prev + paso + visibles.length) % visibles.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activo >= 0 && visibles[activo]) elegir(visibles[activo]);
      else elegirTipeada();
    } else if (e.key === 'Escape' && abierto) {
      e.preventDefault();
      cerrar();
    }
  };

  const mostrarLista = abierto && cargado && opciones.length > 0;
  const opcionId = (operacion) => `${id}-op-${operacion.id}`;

  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor={`${id}-input`}>
        {label}
      </label>
      <input
        id={`${id}-input`}
        type="text"
        role="combobox"
        autoComplete="off"
        className={styles.input}
        placeholder="Buscar por N°, proveedor o factura…"
        aria-expanded={mostrarLista}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={mostrarLista && activo >= 0 ? opcionId(opciones[activo]) : undefined}
        value={texto}
        disabled={deshabilitado}
        onChange={(e) => {
          setTexto(e.target.value);
          setAbierto(true);
        }}
        onFocus={() => setAbierto(true)}
        onClick={() => setAbierto(true)}
        onBlur={cerrar}
        onKeyDown={onKeyDown}
      />
      {restriccion && (
        <p className={styles.hint}>
          Solo se ofrecen operaciones de {restriccion.proveedorNombre} en {restriccion.moneda}.
        </p>
      )}
      {abierto && error && <p className={styles.hint}>No se pudieron buscar operaciones.</p>}
      {abierto && cargado && !error && opciones.length === 0 && <p className={styles.hint}>Ninguna operación coincide.</p>}
      {mostrarLista && (
        <ul id={listId} role="listbox" aria-label="Operaciones de compra encontradas" className={styles.resultados}>
          {opciones.map((operacion, i) => (
            <li
              key={operacion.id}
              id={opcionId(operacion)}
              role="option"
              aria-selected={i === activo}
              className={`${styles.opcion} ${i === activo ? styles.opcionActiva : ''}`}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => elegir(operacion)}
            >
              <span className={styles.opcionFila}>
                <span>N° {operacion.id}</span>
                <span className={styles.mono}>{operacion.numero}</span>
                <span className={styles.opcionProveedor}>{operacion.proveedor_nombre ?? `Proveedor #${operacion.proveedor_id}`}</span>
                <EstadoBadge variant="pedido" estado={operacion.estado} />
              </span>
              <span className={`${styles.opcionFila} ${styles.resultadoSub}`}>
                <span>{formatDateOnly(operacion.fecha)}</span>
                <span>{formatMonto(operacion.monto, operacion.moneda)}</span>
                {operacion.numero_factura && <span>Factura {operacion.numero_factura}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
