import { useEffect, useState } from 'react';
import { Search } from 'lucide-react';
import { productoMaestroAPI, productoMarcasAPI } from '../../services/api';
import { useDebounce } from '../../hooks/useDebounce';
import { numero } from './formato';
import m from './maestro.module.css';
import styles from './MaestroLista.module.css';

const PAGE = 50;

const TABS = [
  { key: 'todos', label: 'Todos', tipo: undefined },
  { key: 'notebook', label: 'Notebooks', tipo: 'notebook' },
  { key: 'pc', label: 'PCs', tipo: 'pc' },
];

function Fila({ item, on, onSelect }) {
  const conSpecs = item.specs_total != null;
  const completo = conSpecs && item.specs_completos === item.specs_total;
  const barCls = !conSpecs ? `${m.bar} ${m.barNone}` : completo ? `${m.bar} ${m.barFull}` : m.bar;
  const ancho = conSpecs ? `${Math.round((item.specs_completos / item.specs_total) * 100)}%` : '0';
  return (
    <button type="button" className={on ? `${styles.row} ${styles.rowOn}` : styles.row} aria-current={on || undefined} onClick={() => onSelect(item.item_id)}>
      <span className={styles.rowMain}>
        <span className={styles.rowName}>{item.nombre ?? '—'}</span>
        <span className={`${m.mono} ${styles.rowMeta}`}>{`item ${item.item_id} · ${item.ean ?? 'sin EAN'}`}</span>
      </span>
      <span className={`${m.mono} ${styles.rowStock}`}>{numero(item.stock)}</span>
      <span className={styles.rowSpecs}>
        <span className={`${m.mono} ${styles.rowFrac}`}>{conSpecs ? `${item.specs_completos} / ${item.specs_total}` : '—'}</span>
        <span className={barCls}>
          <i style={{ width: ancho }} />
        </span>
      </span>
    </button>
  );
}

/**
 * The product master's list (abm-productos S5, the approved mock's left card): every ERP product ordered by stock,
 * Todos / Notebooks / PCs with their totals, "Specs incompletas", a search by name, EAN or code and the brand.
 *
 * @param {object} props
 * @param {number | null} props.selectedId The product open in the ficha.
 * @param {(itemId: number) => void} props.onSelect
 * @param {(itemId: number) => void} [props.onFirst] Receives the first product of a load, to open one at start.
 * @param {number} [props.reloadKey] Changes after a save, so the list shows the new name or completeness.
 */
export default function MaestroLista({ selectedId, onSelect, onFirst, reloadKey = 0 }) {
  const [tab, setTab] = useState('todos');
  const [incompletos, setIncompletos] = useState(false);
  const [q, setQ] = useState('');
  const [marca, setMarca] = useState('');
  const [marcas, setMarcas] = useState([]);
  const [totales, setTotales] = useState({});
  const [estado, setEstado] = useState({ items: [], total: 0, loading: true, error: null });
  const [offset, setOffset] = useState(0);
  const qDebounced = useDebounce(q.trim(), 300);
  const tipo = TABS.find((t) => t.key === tab).tipo;

  useEffect(() => {
    productoMarcasAPI
      .listar()
      .then(({ data }) => setMarcas(data.filter((x) => x.activa && x.productos > 0).map((x) => x.nombre).sort()))
      .catch(() => setMarcas([]));
    Promise.all(TABS.map((t) => productoMaestroAPI.listar({ tipo: t.tipo, limit: 1, offset: 0 })))
      .then((answers) => setTotales(Object.fromEntries(answers.map(({ data }, i) => [TABS[i].key, data.total]))))
      .catch(() => setTotales({}));
  }, [reloadKey]);

  // A new filter starts again from the first page.
  const filtros = `${tab}|${incompletos}|${qDebounced}|${marca}`;
  const [filtrosPrevios, setFiltrosPrevios] = useState(filtros);
  if (filtros !== filtrosPrevios) {
    setFiltrosPrevios(filtros);
    setOffset(0);
  }

  useEffect(() => {
    let vigente = true;
    setEstado((prev) => ({ ...prev, loading: true, error: null }));
    const params = { tipo, incompletos: incompletos || undefined, q: qDebounced || undefined, marca: marca || undefined, limit: PAGE, offset };
    productoMaestroAPI
      .listar(params)
      .then(({ data }) => {
        if (!vigente) return;
        setEstado((prev) => ({ items: offset === 0 ? data.items : [...prev.items, ...data.items], total: data.total, loading: false, error: null }));
        if (offset === 0 && data.items.length) onFirst?.(data.items[0].item_id);
      })
      .catch(() => vigente && setEstado((prev) => ({ ...prev, loading: false, error: 'No se pudo cargar la lista. Probá de nuevo.' })));
    return () => {
      vigente = false;
    };
    // onFirst is read once per load; a new callback identity is no reason to load again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tipo, incompletos, qDebounced, marca, offset, reloadKey]);

  return (
    <section aria-label="Listado" className={`${m.card} ${styles.lista}`}>
      <div className={styles.top}>
        <div role="tablist" aria-label="Tipo de producto" className={m.tablist}>
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              className={tab === t.key ? `${m.tab} ${m.tabOn}` : m.tab}
              onClick={() => setTab(t.key)}
            >
              {t.label} {totales[t.key] != null && <span className={m.tabCount}>{numero(totales[t.key])}</span>}
            </button>
          ))}
        </div>
        <label className={styles.check}>
          <input className={m.chk} type="checkbox" checked={incompletos} onChange={(e) => setIncompletos(e.target.checked)} />
          Specs incompletas
        </label>
      </div>
      <div className={styles.filtros}>
        <label className={m.inpWrap}>
          <span className={m.searchIcon} aria-hidden="true">
            <Search size={16} strokeWidth={1.5} />
          </span>
          <input
            className={`${m.inp} ${m.inpSearch}`}
            type="search"
            placeholder="Buscar"
            aria-label="Buscar por nombre, EAN o código"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </label>
        <select className={m.inp} aria-label="Marca" value={marca} onChange={(e) => setMarca(e.target.value)}>
          <option value="">Todas las marcas</option>
          {marcas.map((nombre) => (
            <option key={nombre} value={nombre}>
              {nombre}
            </option>
          ))}
        </select>
      </div>

      <div className={styles.head} aria-hidden="true">
        <span>Producto</span>
        <span className={styles.right}>Stock</span>
        <span>Specs</span>
      </div>
      <div className={styles.rows}>
        {estado.items.map((item) => (
          <Fila key={item.item_id} item={item} on={item.item_id === selectedId} onSelect={onSelect} />
        ))}
        {!estado.loading && !estado.error && estado.items.length === 0 && <p className={styles.vacio}>Ningún producto coincide con los filtros</p>}
      </div>
      {estado.error && (
        <p className={m.feedback} role="alert">
          {estado.error}
        </p>
      )}
      <div className={styles.pie}>
        <p className={`${m.mono} ${styles.pieTxt}`}>
          {estado.loading && estado.items.length === 0 ? 'Cargando…' : `${numero(estado.items.length)} de ${numero(estado.total)} · ordenado por stock`}
        </p>
        {estado.items.length < estado.total && (
          <button type="button" className={m.lnk} disabled={estado.loading} onClick={() => setOffset(estado.items.length)}>
            Ver más
          </button>
        )}
      </div>
    </section>
  );
}
