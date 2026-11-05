import { useEffect, useState } from 'react';
import SearchInput from '../SearchInput';
import { Pagination, SegmentedControl } from '../kit';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import TacticalFila from './TacticalFila';
import { COLUMNAS_TACTICAL, FILTROS_VACIOS, paramsDeFiltros } from './tacticalsFormat';
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
const FILAS_POR_PAGINA = 50;

/**
 * The Tacticals tab (S7): the brands' programs filtered by tipo, brand, state, dates and a search, one row per
 * tactical with its overall progress; expanding a row shows its lines with their caps and usage. A new `version`
 * (the page's "Actualizar") asks the list again.
 */
export default function TacticalsList({ marcas = [], version = 0 }) {
  const [filtros, setFiltros] = useState(FILTROS_VACIOS);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(FILAS_POR_PAGINA);
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState(false);
  const [abiertos, setAbiertos] = useState(() => new Set());

  const clave = JSON.stringify(paramsDeFiltros(filtros, { page: Math.floor(offset / pageSize) + 1, pageSize }));
  useEffect(() => {
    let activo = true;
    setError(false);
    tacticalsAPI
      .listar(JSON.parse(clave))
      .then(({ data }) => activo && setDatos(data))
      .catch(() => activo && setError(true));
    return () => {
      activo = false;
    };
  }, [clave, version]);

  // A reload can leave the page past the end (tacticals voided or expired meanwhile): go to the last page with some,
  // or to the first one when none are left.
  const fueraDeRango = datos != null && offset > 0 && offset >= datos.total;
  useEffect(() => {
    if (fueraDeRango) setOffset(Math.max(0, (Math.ceil(datos.total / pageSize) - 1) * pageSize));
  }, [fueraDeRango, datos, pageSize]);

  // New filters are a new list: say it is loading rather than keep the previous rows, and start with every row closed.
  const filtrar = (cambio) => {
    setFiltros((actual) => ({ ...actual, ...cambio }));
    setOffset(0);
    setDatos(null);
    setAbiertos(new Set());
  };
  const alternar = (id) =>
    setAbiertos((actual) => {
      const siguiente = new Set(actual);
      if (siguiente.has(id)) siguiente.delete(id);
      else siguiente.add(id);
      return siguiente;
    });

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
        <div className={styles.campo}>
          <span className={styles.label}>Estado</span>
          <SegmentedControl label="Estado" options={ESTADOS} value={filtros.estado} onChange={(estado) => filtrar({ estado })} />
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
                <TacticalFila key={tactical.id} tactical={tactical} abierto={abiertos.has(tactical.id)} onAlternar={() => alternar(tactical.id)} />
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
            }}
            pageSizeOptions={[25, 50, 100]}
            summary={
              <span className={styles.cuenta}>
                mostrando {datos.total === 0 ? 0 : offset + 1}-{Math.min(offset + pageSize, datos.total)} de {datos.total}
              </span>
            }
          />
        </div>
      )}
    </>
  );
}
