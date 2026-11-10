import { useEffect, useState } from 'react';
import SearchInput from '../SearchInput';
import { Pagination, SegmentedControl } from '../kit';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import TacticalAnular from './TacticalAnular';
import TacticalEditar from './TacticalEditar';
import TacticalFila from './TacticalFila';
import { COLUMNAS_TACTICAL, FILTROS_VACIOS, formatMontosKpi, paramsDeFiltros } from './tacticalsFormat';
import tablaStyles from './TacticalFila.module.css';
import styles from './TacticalsList.module.css';

const TIPOS = [
  { value: 'todos', label: 'Todos' },
  { value: 'sell_in', label: 'Sell in' },
  { value: 'sell_out', label: 'Sell out' },
];
const ESTADOS = [
  { value: 'vigentes', label: 'Vigentes' },
  { value: 'vencidos', label: 'Vencidos' },
  { value: 'anulados', label: 'Anulados' },
];
const COBRANZAS = [
  { value: 'todos', label: 'Todos' },
  { value: 'pendientes', label: 'Pendientes' },
  { value: 'cobrados', label: 'Cobrados' },
];
const FILAS_POR_PAGINA = 50;

const cantidadDe = (n) => `${n} ${n === 1 ? 'tactical' : 'tacticals'}`;

/** Pendientes and Cobrados over every tactical the other filters match (tactical cobranza S4): count and amount. */
function KpisCobranza({ kpis }) {
  return (
    <section className={styles.kpis} aria-label="Cobranza de los tacticals">
      {[
        ['Pendientes', kpis.pendientes],
        ['Cobrados', kpis.cobrados],
      ].map(([titulo, grupo]) => (
        <div key={titulo} className={styles.kpi}>
          <span className={styles.label}>{titulo}</span>
          <div className={styles.kpiCantidad}>{cantidadDe(grupo.cantidad)}</div>
          <div className={styles.kpiMonto}>{formatMontosKpi(grupo.montos)}</div>
        </div>
      ))}
      <p className={styles.kpiNota}>Monto: lo que generaron las líneas de cada tactical, por moneda.</p>
    </section>
  );
}

/**
 * The Tacticals tab (S7): the brands' programs filtered by tipo, brand, currency, state, dates and a search, one row per
 * tactical with its overall progress; expanding a row shows its lines with their caps and usage. A new `version`
 * (the page's "Actualizar") asks the list again. A row of a kind the user manages (`puedeGestionar(tipo)`) has an
 * actions menu (tacticals F1): Editar, on a tactical that is not voided, opens the Editar dialog and asks the list
 * again after saving; Renovar hands the tactical to `onRenovar`; Anular, on a tactical that is not voided, asks for
 * confirmation, voids it and its children, asks the list again and tells `onCambio` (the page's tab count). An
 * expanded line's "Ver ventas" hands that line to `onVerLinea` (the page opens its record). `tipoInicial` (`todos`,
 * `sell_in` or `sell_out`) is the Tipo the list opens with; Limpiar filtros goes back to Todos.
 *
 * Cobranza (handoffs/tactical-cobranza-tarea.md S3, S4): a Cobranza filter (Todos | Pendientes | Cobrados), the
 * Pendientes / Cobrados KPIs the list answers over the other filters, and on each row a Pendiente / Cobrado pill; a
 * row the user manages opens its Cobranza box under it (one at a time), and a save or an undo asks the list again.
 */
export default function TacticalsList({ marcas = [], version = 0, puedeGestionar = () => false, onRenovar, onCambio, onVerLinea, tipoInicial = 'todos' }) {
  const [filtros, setFiltros] = useState(() => ({ ...FILTROS_VACIOS, tipo: tipoInicial }));
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(FILAS_POR_PAGINA);
  // The last answer with the query it answers: a new query shows the loading message until its own answer arrives.
  const [respuesta, setRespuesta] = useState(null);
  const [error, setError] = useState(false);
  const [abiertos, setAbiertos] = useState(() => new Set());
  const [editando, setEditando] = useState(null);
  const [anulando, setAnulando] = useState(null);
  const [guardados, setGuardados] = useState(0);
  // The tactical whose Cobranza box is open under its row (one at a time), or null.
  const [cobrando, setCobrando] = useState(null);

  const claveDe = (f, desde) => JSON.stringify(paramsDeFiltros(f, { page: Math.floor(desde / pageSize) + 1, pageSize }));
  const clave = claveDe(filtros, offset);
  const datos = respuesta?.clave === clave ? respuesta.data : null;
  useEffect(() => {
    let activo = true;
    setError(false);
    tacticalsAPI
      .listar(JSON.parse(clave))
      .then(({ data }) => activo && setRespuesta({ clave, data }))
      .catch(() => activo && setError(true));
    return () => {
      activo = false;
    };
  }, [clave, version, guardados]);

  // A reload can leave the page past the end (tacticals voided or expired meanwhile): go to the last page with some,
  // or to the first one when none are left.
  const fueraDeRango = datos != null && offset > 0 && offset >= datos.total;
  useEffect(() => {
    if (fueraDeRango) setOffset(Math.max(0, (Math.ceil(datos.total / pageSize) - 1) * pageSize));
  }, [fueraDeRango, datos, pageSize]);

  // Filters that ask something new start a new list on its first page with every row closed; a change that leaves the
  // same query (a trailing space in Buscar, Limpiar on clean filters) keeps the list as it is.
  const filtrar = (cambio) => {
    const nuevos = { ...filtros, ...cambio };
    setFiltros(nuevos);
    if (claveDe(nuevos, offset) === clave) return;
    setOffset(0);
    setAbiertos(new Set());
    setCobrando(null);
  };
  const alternar = (id) =>
    setAbiertos((actual) => {
      const siguiente = new Set(actual);
      if (siguiente.has(id)) siguiente.delete(id);
      else siguiente.add(id);
      return siguiente;
    });

  const accionesDe = (tactical) => {
    if (!puedeGestionar(tactical.tipo)) return [];
    const acciones = [];
    if (tactical.estado !== 'anulado') acciones.push({ label: 'Editar', onSelect: () => setEditando(tactical) });
    if (onRenovar) acciones.push({ label: 'Renovar', onSelect: () => onRenovar(tactical) });
    if (tactical.estado !== 'anulado') acciones.push({ label: 'Anular', onSelect: () => setAnulando(tactical) });
    return acciones;
  };

  return (
    <>
      <section className={styles.filtros} aria-label="Filtros de tacticals">
        <div className={styles.campo}>
          <span className={styles.label}>Tipo</span>
          <SegmentedControl label="Tipo" options={TIPOS} value={filtros.tipo} onChange={(tipo) => filtrar({ tipo })} />
        </div>
        <label className={styles.campo}>
          <span className={styles.label}>Marca</span>
          <select className={styles.control} value={filtros.marca} onChange={(e) => filtrar({ marca: e.target.value })}>
            <option value="">Todas</option>
            {marcas.map((marca) => (
              <option key={marca} value={marca}>
                {marca}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.campo}>
          <span className={styles.label}>Moneda</span>
          <select className={styles.control} value={filtros.moneda} onChange={(e) => filtrar({ moneda: e.target.value })}>
            <option value="">Todas</option>
            <option value="ARS">ARS</option>
            <option value="USD">USD</option>
          </select>
        </label>
        <div className={styles.campo}>
          <span className={styles.label}>Estado</span>
          <SegmentedControl label="Estado" options={ESTADOS} value={filtros.estado} onChange={(estado) => filtrar({ estado })} />
        </div>
        <div className={styles.campo}>
          <span className={styles.label}>Cobranza</span>
          <SegmentedControl label="Cobranza" options={COBRANZAS} value={filtros.cobranza} onChange={(cobranza) => filtrar({ cobranza })} />
        </div>
        <fieldset className={styles.vigencia}>
          <legend className={styles.label}>Vigencia</legend>
          <label className={styles.fecha}>
            <span className={styles.subLabel}>Desde</span>
            <input type="date" className={styles.control} value={filtros.desde} onChange={(e) => filtrar({ desde: e.target.value })} />
          </label>
          <label className={styles.fecha}>
            <span className={styles.subLabel}>Hasta</span>
            <input type="date" className={styles.control} value={filtros.hasta} onChange={(e) => filtrar({ hasta: e.target.value })} />
          </label>
        </fieldset>
        <div className={`${styles.campo} ${styles.buscar}`}>
          <span className={styles.label}>Buscar</span>
          <SearchInput value={filtros.q} onChange={(q) => filtrar({ q })} debounce={300} placeholder="Buscar por nombre o referencia" />
        </div>
        <button type="button" className={styles.limpiar} onClick={() => filtrar(FILTROS_VACIOS)}>
          Limpiar filtros
        </button>
      </section>

      {error && (
        <div className={styles.aviso} role="alert">
          No se pudieron cargar los tacticals.
        </div>
      )}
      {!error && !datos && <div className={styles.aviso}>Cargando tacticals…</div>}
      {!error && datos?.kpis && <KpisCobranza kpis={datos.kpis} />}
      {!error && datos && (
        <div className={styles.lista}>
          <div className={styles.scroller}>
            <table className={tablaStyles.tabla}>
              <thead>
                <tr>
                  <th scope="col">
                    <span className={styles.srOnly}>Líneas</span>
                  </th>
                  <th scope="col">Nombre</th>
                  <th scope="col">Tipo</th>
                  <th scope="col">Marca</th>
                  <th scope="col">Vigencia</th>
                  <th scope="col" className={tablaStyles.num}>Líneas</th>
                  <th scope="col">Avance</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Cobranza</th>
                  <th scope="col">
                    <span className={styles.srOnly}>Acciones</span>
                  </th>
                </tr>
              </thead>
              {datos.items.length === 0 && (
                <tbody>
                  <tr>
                    <td colSpan={COLUMNAS_TACTICAL} className={styles.vacio}>
                      No hay tacticals con estos filtros.
                    </td>
                  </tr>
                </tbody>
              )}
              {datos.items.map((tactical) => (
                <TacticalFila
                  key={tactical.id}
                  tactical={tactical}
                  abierto={abiertos.has(tactical.id)}
                  onAlternar={() => alternar(tactical.id)}
                  acciones={accionesDe(tactical)}
                  onVerLinea={onVerLinea}
                  cobranza={{
                    puede: puedeGestionar(tactical.tipo),
                    abierta: cobrando === tactical.id,
                    onAlternar: () => setCobrando((actual) => (actual === tactical.id ? null : tactical.id)),
                    onGuardado: () => {
                      setCobrando(null);
                      setGuardados((n) => n + 1);
                    },
                  }}
                />
              ))}
            </table>
          </div>
          <Pagination
            total={datos.total}
            offset={offset}
            pageSize={pageSize}
            onOffsetChange={setOffset}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setOffset(0);
              setAbiertos(new Set());
            }}
            pageSizeOptions={[25, 50, 100]}
            summary={
              <span className={styles.cuenta}>
                mostrando {Math.min(offset + 1, datos.total)}-{Math.min(offset + pageSize, datos.total)} de {datos.total}
              </span>
            }
          />
        </div>
      )}
      {anulando && (
        <TacticalAnular
          tactical={anulando}
          onCerrar={() => setAnulando(null)}
          onAnulado={() => {
            setAnulando(null);
            setGuardados((n) => n + 1);
            onCambio?.();
          }}
        />
      )}
      {editando && (
        <TacticalEditar
          tactical={editando}
          onCerrar={() => setEditando(null)}
          onGuardado={() => {
            setEditando(null);
            setGuardados((n) => n + 1);
          }}
        />
      )}
    </>
  );
}
