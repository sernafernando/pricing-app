import { useEffect, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import SearchInput from '../SearchInput';
import { usePermisos } from '../../contexts/PermisosContext';
import { sellInLotesAPI } from '../../services/sellInAPI';
import { formatEntero, formatMonto } from './sellInFormat';
import SellInModoPorDefecto from './SellInModoPorDefecto';
import styles from './SellInProductosCosto.module.css';

/** The labels the cost-mode panel (`SellInModoCosto`) uses; no mode row is FIFO, the default. */
const MODOS = { fifo: 'FIFO', ponderado: 'Ponderado (PPP)', ultimo: 'Último precio', manual: 'Manual' };
// The modes a default may be (never Manual: it needs its own figures), in the panel selector's order.
const MODOS_DEFECTO = ['fifo', 'ponderado', 'ultimo'].map((value) => ({ value, label: MODOS[value] }));
// Only an admin changes the default (the endpoint asks for one), as in the product panel.
const ADMINS = ['ADMIN', 'SUPERADMIN'];
// The Modo filter: "FIFO (por defecto)" is a product without a mode of its own, "FIFO" one set to FIFO.
const SIN_MODO = 'sin-modo';
const FILTROS_VACIOS = { q: '', marca: '', modo: '' };

const modoLabel = (modo) => (modo ? (MODOS[modo] ?? modo) : 'FIFO (por defecto)');

const fecha = (iso) => {
  const [y, m, d] = String(iso).split('-');
  return `${d}/${m}/${y}`;
};

// Search ignores case and accents.
const normalizar = (texto) =>
  String(texto ?? '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase();

const comparaTexto = (a, b) => a.localeCompare(b, 'es', { sensitivity: 'base' });

/** The sortable columns: how each one compares two rows; a row with no value goes last in both directions. */
const COLUMNAS = [
  { key: 'producto', label: 'Producto', valor: (x) => x.descripcion ?? x.codigo ?? '', compara: comparaTexto },
  { key: 'modo', label: 'Modo de costo', valor: (x) => modoLabel(x.modo), compara: comparaTexto },
  { key: 'unidades', label: 'Unidades', num: true, valor: (x) => x.unidades, compara: (a, b) => a - b },
  {
    key: 'sell_in_unit',
    label: 'Sell in por unidad',
    num: true,
    valor: (x) => (x.sell_in_unit == null ? null : Number(x.sell_in_unit)),
    compara: (a, b) => a - b,
  },
  { key: 'ultima_compra', label: 'Últ. compra', num: true, valor: (x) => x.ultima_compra, compara: comparaTexto },
];

function filtrar(productos, filtros) {
  const q = normalizar(filtros.q.trim());
  return productos.filter(
    (x) =>
      (!q || normalizar(x.codigo).includes(q) || normalizar(x.descripcion).includes(q)) &&
      (!filtros.marca || x.marca === filtros.marca) &&
      (!filtros.modo || (filtros.modo === SIN_MODO ? x.modo == null : x.modo === filtros.modo)),
  );
}

function ordenar(productos, orden) {
  const columna = COLUMNAS.find((c) => c.key === orden?.key);
  if (!columna) return productos;
  const signo = orden.dir === 'asc' ? 1 : -1;
  return [...productos].sort((a, b) => {
    const va = columna.valor(a);
    const vb = columna.valor(b);
    if (va == null || vb == null) return (va == null) - (vb == null);
    return signo * columna.compara(va, vb);
  });
}

/** The saved default mode, read on mount and with each `version`; null while unread or when it cannot be read. */
function useModoPorDefecto(version) {
  const [modo, setModo] = useState(null);
  useEffect(() => {
    let current = true;
    sellInLotesAPI
      .modoPorDefecto()
      .then(({ data }) => current && setModo(data.modo))
      .catch(() => current && setModo(null));
    return () => {
      current = false;
    };
  }, [version]);
  return [modo, setModo];
}

/**
 * Sell in's Productos list (`GET /sell-in/productos/costos`, one request for the whole list): every product with
 * units left in its lots, with its "Modo de costo", units, what the next sale takes per unit and its latest purchase,
 * and the total units under it. A toolbar searches by código/descripción and filters by Marca and Modo de costo,
 * client side: the endpoint already computes the whole list in a fixed number of queries, so a server filter would not
 * save it work. The headers sort; "Ver lotes" opens a product's lots and cost mode (`onVer(fila)`). The toolbar also
 * shows the default mode and, for an admin, "Cambiar" opens its modal. A new `version` reads both again.
 *
 * @param {object} props
 * @param {(fila: object) => void} props.onVer
 * @param {number} [props.version]
 */
export default function SellInProductosCosto({ onVer, version = 0 }) {
  const { rol } = usePermisos();
  const [read, setRead] = useState({ status: 'loading', productos: [] });
  const [attempt, setAttempt] = useState(0);
  const [filtros, setFiltros] = useState(FILTROS_VACIOS);
  const [orden, setOrden] = useState(null); // null: the server's order (description, then code)
  const [porDefecto, setPorDefecto] = useModoPorDefecto(version);
  const [editandoDefecto, setEditandoDefecto] = useState(false);

  useEffect(() => {
    let current = true;
    sellInLotesAPI
      .productos()
      .then(({ data }) => current && setRead({ status: 'ready', productos: data.productos ?? [] }))
      .catch(() => current && setRead({ status: 'error', productos: [] }));
    return () => {
      current = false;
    };
  }, [version, attempt]);

  const cambiarFiltros = (cambios) => setFiltros((prev) => ({ ...prev, ...cambios }));
  const ordenarPor = (key) =>
    setOrden((prev) => (prev?.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }));

  if (read.status === 'loading' && read.productos.length === 0) {
    return (
      <p className={styles.nota} role="status">
        Cargando productos…
      </p>
    );
  }
  if (read.status === 'error') {
    return (
      <div className={styles.error} role="alert">
        <span>No se pudieron cargar los productos.</span>
        <button
          type="button"
          className="btn-tesla outline sm"
          onClick={() => {
            setRead({ status: 'loading', productos: [] });
            setAttempt((n) => n + 1);
          }}
        >
          Reintentar
        </button>
      </div>
    );
  }
  if (read.productos.length === 0) {
    return <p className={styles.nota}>Ningún producto tiene unidades en lotes de sell in.</p>;
  }

  const marcas = [...new Set(read.productos.map((x) => x.marca).filter(Boolean))].sort(comparaTexto);
  const visibles = ordenar(filtrar(read.productos, filtros), orden);
  const total = visibles.reduce((sum, x) => sum + x.unidades, 0);

  return (
    <>
      <section className={styles.filtros} aria-label="Filtros de productos">
        <div className={`${styles.campo} ${styles.buscar}`}>
          <span className={styles.label}>Buscar</span>
          <SearchInput
            value={filtros.q}
            onChange={(q) => cambiarFiltros({ q })}
            debounce={200}
            size="sm"
            placeholder="Buscar por código o descripción"
          />
        </div>
        <label className={styles.campo}>
          <span className={styles.label}>Marca</span>
          <select className={styles.control} value={filtros.marca} onChange={(e) => cambiarFiltros({ marca: e.target.value })}>
            <option value="">Todas</option>
            {marcas.map((marca) => (
              <option key={marca} value={marca}>
                {marca}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.campo}>
          <span className={styles.label}>Modo de costo</span>
          <select className={styles.control} value={filtros.modo} onChange={(e) => cambiarFiltros({ modo: e.target.value })}>
            <option value="">Todos</option>
            <option value={SIN_MODO}>FIFO (por defecto)</option>
            {Object.entries(MODOS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className={styles.limpiar} onClick={() => setFiltros(FILTROS_VACIOS)}>
          Limpiar filtros
        </button>
        {porDefecto && (
          <div className={styles.defecto}>
            <span className={styles.defectoTexto}>
              <span>Modo por defecto:</span> <strong>{MODOS[porDefecto] ?? porDefecto}</strong>
            </span>
            {ADMINS.includes(rol) && (
              <button
                type="button"
                className="btn-tesla outline sm"
                aria-label="Cambiar modo por defecto"
                onClick={() => setEditandoDefecto(true)}
              >
                Cambiar
              </button>
            )}
          </div>
        )}
      </section>

      <section className={styles.card}>
        <div className={styles.scroller}>
          <table className={styles.table} aria-label="Productos con lotes de sell in">
            <thead>
              <tr>
                {COLUMNAS.map((columna) => {
                  const activa = orden?.key === columna.key;
                  return (
                    <th
                      key={columna.key}
                      scope="col"
                      className={columna.num ? styles.num : undefined}
                      aria-sort={activa ? (orden.dir === 'asc' ? 'ascending' : 'descending') : undefined}
                    >
                      <button type="button" className={styles.sort} onClick={() => ordenarPor(columna.key)}>
                        {columna.label}
                        {activa &&
                          (orden.dir === 'asc' ? (
                            <ChevronUp size={12} aria-hidden="true" />
                          ) : (
                            <ChevronDown size={12} aria-hidden="true" />
                          ))}
                      </button>
                    </th>
                  );
                })}
                <th scope="col" className={styles.acciones}>
                  <span className={styles.srOnly}>Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {visibles.map((fila) => (
                <tr key={fila.item_id}>
                  <td>
                    <span className={styles.producto}>
                      <span className={styles.nombre}>{fila.descripcion}</span>
                      <span className={styles.codigo}>{fila.codigo}</span>
                    </span>
                  </td>
                  <td>
                    <span className={styles.pill}>{modoLabel(fila.modo)}</span>
                  </td>
                  <td className={styles.num}>{formatEntero(fila.unidades)} u</td>
                  <td className={styles.num}>{formatMonto(fila.sell_in_unit, 'ARS')}</td>
                  <td className={styles.num}>{fecha(fila.ultima_compra)}</td>
                  <td className={styles.acciones}>
                    <button
                      type="button"
                      className="btn-tesla outline sm"
                      aria-label={`Ver lotes y modo de costo de ${fila.descripcion ?? fila.codigo}`}
                      onClick={() => onVer(fila)}
                    >
                      Ver lotes
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {visibles.length === 0 ? (
          <p className={styles.nota}>Ningún producto coincide con los filtros.</p>
        ) : (
          <div className={`${styles.total} ${styles.num}`}>{formatEntero(total)} u</div>
        )}
      </section>

      {editandoDefecto && (
        <SellInModoPorDefecto
          actual={porDefecto}
          options={MODOS_DEFECTO}
          onClose={() => setEditandoDefecto(false)}
          onSaved={(value) => {
            setPorDefecto(value);
            setEditandoDefecto(false);
          }}
        />
      )}
    </>
  );
}
