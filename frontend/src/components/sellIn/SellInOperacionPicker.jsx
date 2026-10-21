import { useEffect, useId, useRef, useState } from 'react';
import { sellInAPI } from '../../services/sellInAPI';
import { formatDateOnly } from '../../utils/dateUtils';
import EstadoBadge from '../compras/_shared/EstadoBadge';
import SellInOperacionProductos from './SellInOperacionProductos';
import { formatMonto } from './sellInFormat';
import styles from './SellInPanel.module.css';

const DEBOUNCE_MS = 250;
const HOVER_MS = 200; // a pointer sweeping the list asks for nothing; only the row it rests on

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
 *
 * Resting the pointer on an option, or highlighting it with the arrow keys, shows a card with that
 * operation's products (`SellInOperacionProductos`), fetched once per operation and kept while mounted.
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
  const [apuntada, setApuntada] = useState(null); // the option under the pointer, at once
  const [mostrada, setMostrada] = useState(null); // { operacion, rect } once the pointer rested
  const [productos, setProductos] = useState({}); // operation id -> { estado, items }
  const pedidos = useRef(new Set());

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
    setApuntada(null);
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
      // The hint only shows with the list open: open it, or a failure here would go unseen.
      setAbierto(true);
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
  const cardId = `${id}-productos`;

  const objetivo = !mostrarLista ? null : (apuntada ?? (activo >= 0 ? opciones[activo] : null));
  const cargarProductos = (pedidoId) => {
    if (pedidos.current.has(pedidoId)) return;
    pedidos.current.add(pedidoId);
    setProductos((prev) => ({ ...prev, [pedidoId]: { estado: 'cargando' } }));
    Promise.resolve()
      .then(() => sellInAPI.operacionProductos(pedidoId))
      .then(({ data }) => setProductos((prev) => ({ ...prev, [pedidoId]: { estado: 'ok', items: data.items } })))
      .catch(() => {
        pedidos.current.delete(pedidoId); // the next rest on it tries again
        setProductos((prev) => ({ ...prev, [pedidoId]: { estado: 'error' } }));
      });
  };
  useEffect(() => {
    if (!objetivo) return undefined;
    const timer = setTimeout(() => {
      const rect = document.getElementById(opcionId(objetivo))?.getBoundingClientRect();
      setMostrada({ operacion: objetivo, rect });
      cargarProductos(objetivo.id);
    }, HOVER_MS);
    return () => clearTimeout(timer);
    // Only the operation matters: a new `opciones` array with the same target must not re-arm the timer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [objetivo?.id]);
  const card = objetivo && mostrada?.operacion.id === objetivo.id ? mostrada : null;

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
        aria-controls={mostrarLista ? listId : undefined}
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
              aria-describedby={card?.operacion.id === operacion.id ? cardId : undefined}
              className={`${styles.opcion} ${i === activo ? styles.opcionActiva : ''}`}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => elegir(operacion)}
              onMouseEnter={() => setApuntada(operacion)}
              onMouseLeave={() => setApuntada((prev) => (prev?.id === operacion.id ? null : prev))}
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
      {card && (
        <SellInOperacionProductos id={cardId} operacion={card.operacion} rect={card.rect} estado={productos[card.operacion.id]} />
      )}
    </div>
  );
}
