import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import SearchInput from '../SearchInput';
import { Pagination, SegmentedControl, StatusPill } from '../kit';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import {
  FILTROS_VACIOS,
  alcanceDe,
  avanceDeLinea,
  avanceDeTactical,
  estadoDe,
  formatMontoTactical,
  formatUnidades,
  paramsDeFiltros,
  valorDeLinea,
  vigenciaDe,
} from './tacticalsFormat';
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
const TIPO_PILL = { sell_in: { texto: 'Sell in', tono: 'neutral' }, sell_out: { texto: 'Sell out', tono: 'info' } };
const FILAS_POR_PAGINA = 50;
const COLUMNAS = 8;
const PORCENTAJE = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 });

function Barra({ avance, etiqueta }) {
  return (
    <div className={`${styles.bar} ${styles[avance.tono] ?? ''}`} role="img" aria-label={`${PORCENTAJE.format(avance.porcentaje)}% ${etiqueta}`}>
      <span style={{ width: `${avance.porcentaje}%` }} />
    </div>
  );
}

/** "Qué incluye": product chips, or the brand / category / invoice the line reaches. */
function QueIncluye({ linea }) {
  if (linea.alcance === 'productos') {
    return (
      <span className={styles.chips}>
        {(linea.productos ?? []).map((p) => (
          <span key={p.item_id} className={styles.chip} title={p.descripcion}>
            {p.descripcion}
          </span>
        ))}
      </span>
    );
  }
  const { titulo, detalle } = alcanceDe(linea);
  return (
    <span className={styles.alcance}>
      {titulo}
      {detalle && <small>{detalle}</small>}
    </span>
  );
}

function Lineas({ tactical }) {
  const { moneda, lineas } = tactical;
  const guion = <span className={styles.guion}>—</span>;
  return (
    <div className={styles.sub}>
      <p className={styles.subTitulo}>Líneas del tactical ({lineas.length})</p>
      <table className={styles.subTabla}>
        <thead>
          <tr>
            <th scope="col">Qué incluye</th>
            <th scope="col" className={styles.num}>Monto</th>
            <th scope="col" className={styles.num}>Tope unidades</th>
            <th scope="col" className={styles.num}>Usadas</th>
            <th scope="col" className={styles.num}>Tope monto</th>
            <th scope="col" className={styles.num}>Usado</th>
            <th scope="col">Avance</th>
          </tr>
        </thead>
        <tbody>
          {lineas.map((linea) => {
            const avance = avanceDeLinea(linea);
            return (
              <tr key={linea.id}>
                <td>
                  <QueIncluye linea={linea} />
                </td>
                <td className={styles.num}>{valorDeLinea(linea, moneda)}</td>
                <td className={styles.num}>{linea.tope_unidades == null ? guion : formatUnidades(linea.tope_unidades)}</td>
                <td className={styles.num}>{linea.unidades_usadas == null ? guion : formatUnidades(linea.unidades_usadas)}</td>
                <td className={styles.num}>{linea.tope_monto == null ? guion : formatMontoTactical(linea.tope_monto, moneda)}</td>
                <td className={styles.num}>{formatMontoTactical(linea.monto_usado, moneda)}</td>
                <td>
                  {avance ? (
                    <div className={styles.subAvance}>
                      <Barra avance={avance} etiqueta={linea.tope_unidades == null ? 'del tope de monto' : 'del tope de unidades'} />
                      {avance.tono === 'full' && <span className={styles.tag}>Tope alcanzado</span>}
                    </div>
                  ) : (
                    guion
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Tactical({ tactical, abierto, onAlternar }) {
  const tipo = TIPO_PILL[tactical.tipo] ?? { texto: tactical.tipo, tono: 'neutral' };
  const estado = estadoDe(tactical);
  const { unidades, montoUsado, topeMonto } = avanceDeTactical(tactical.lineas);
  const Chevron = abierto ? ChevronDown : ChevronRight;
  const usado = formatMontoTactical(montoUsado, tactical.moneda);
  return (
    <tbody>
      <tr className={abierto ? styles.abierto : undefined}>
        <td className={styles.twisty}>
          <button
            type="button"
            className={styles.alternar}
            aria-expanded={abierto}
            aria-controls={`tactical-${tactical.id}-lineas`}
            aria-label={`${abierto ? 'Ocultar' : 'Ver'} las líneas de ${tactical.nombre}`}
            onClick={onAlternar}
          >
            <Chevron size={16} aria-hidden="true" />
          </button>
        </td>
        <td>
          <span className={styles.nombre}>{tactical.nombre}</span>
          {tactical.referencia && <small className={styles.referencia}>{tactical.referencia}</small>}
        </td>
        <td>
          <StatusPill tone={tipo.tono} variant="soft">
            {tipo.texto}
          </StatusPill>
        </td>
        <td>{tactical.marca}</td>
        <td className={styles.nowrap}>{vigenciaDe(tactical.fecha_desde, tactical.fecha_hasta)}</td>
        <td className={styles.num}>{tactical.lineas.length}</td>
        <td>
          <div className={styles.avance}>
            {unidades ? (
              <>
                <Barra avance={unidades} etiqueta="de las unidades consumidas" />
                <span className={styles.unidades}>
                  {formatUnidades(unidades.usadas)} / {formatUnidades(unidades.tope)} u
                </span>
              </>
            ) : (
              <span className={styles.guion}>—</span>
            )}
            <span className={styles.monto}>{topeMonto == null ? usado : `${usado} de ${formatUnidades(topeMonto)}`}</span>
          </div>
        </td>
        <td>
          <StatusPill tone={estado.tono} variant="soft">
            {estado.texto}
          </StatusPill>
        </td>
      </tr>
      {abierto && (
        <tr id={`tactical-${tactical.id}-lineas`} className={styles.filaLineas}>
          <td colSpan={COLUMNAS}>
            <Lineas tactical={tactical} />
          </td>
        </tr>
      )}
    </tbody>
  );
}

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

  const filtrar = (cambio) => {
    setFiltros((actual) => ({ ...actual, ...cambio }));
    setOffset(0);
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
          <SearchInput value={filtros.q} onChange={(q) => filtrar({ q })} debounce={300} placeholder="Buscar por nombre o producto" />
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
            <table className={styles.tabla}>
              <thead>
                <tr>
                  <th scope="col">
                    <span className={styles.srOnly}>Líneas</span>
                  </th>
                  <th scope="col">Nombre</th>
                  <th scope="col">Tipo</th>
                  <th scope="col">Marca</th>
                  <th scope="col">Vigencia</th>
                  <th scope="col" className={styles.num}>Líneas</th>
                  <th scope="col">Avance</th>
                  <th scope="col">Estado</th>
                </tr>
              </thead>
              {datos.items.length === 0 && (
                <tbody>
                  <tr>
                    <td colSpan={COLUMNAS} className={styles.vacio}>
                      No hay tacticals con estos filtros.
                    </td>
                  </tr>
                </tbody>
              )}
              {datos.items.map((tactical) => (
                <Tactical key={tactical.id} tactical={tactical} abierto={abiertos.has(tactical.id)} onAlternar={() => alternar(tactical.id)} />
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
