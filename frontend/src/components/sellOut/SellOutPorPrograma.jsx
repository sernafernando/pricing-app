import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Pagination, StatusPill } from '../kit';
import { sellOutAPI } from '../../services/sellOutAPI';
import { CabeceraCampanas, CampanaFila } from './SellOutCampanasTable';
import { columnasCampanas, plural, resumenDeGrupo, textoActivas } from './sellOutProgramas';
import tableStyles from '../sellIn/SellInTable.module.css';
import styles from './SellOutPorPrograma.module.css';

const GRUPOS_POR_PAGINA = 50;
/** Campaigns asked per expanded group: the list endpoint's maximum (`page_size` le=200). */
const CAMPANAS_POR_GRUPO = 200;

/** A group's campaigns with the list's filters plus its program (or `sin_programa`), read when it is expanded. */
function CampanasDelGrupo({ grupo, filtros, version, columnas, seleccion, onToggle, selectedId, onSelect, onRenovar }) {
  const [lista, setLista] = useState(null);
  const [error, setError] = useState(false);
  const deGrupo = grupo.programa_id == null ? { sin_programa: true } : { programa_id: grupo.programa_id };
  const clave = JSON.stringify({ ...filtros, ...deGrupo });
  useEffect(() => {
    let activo = true;
    setError(false);
    sellOutAPI
      .listar({ ...JSON.parse(clave), page: 1, page_size: CAMPANAS_POR_GRUPO })
      .then(({ data }) => activo && setLista(data))
      .catch(() => activo && setError(true));
    return () => {
      activo = false;
    };
  }, [clave, version]);

  const aviso = (texto) => (
    <tr>
      <td colSpan={columnas} className={tableStyles.empty}>
        {texto}
      </td>
    </tr>
  );
  if (error) return aviso('No se pudieron cargar las campañas del programa.');
  if (!lista) return aviso('Cargando campañas…');
  return (
    <>
      {lista.items.map((campana) => (
        <CampanaFila
          key={campana.id}
          campana={campana}
          selectedId={selectedId}
          onSelect={onSelect}
          onRenovar={onRenovar}
          seleccion={seleccion}
          onToggle={onToggle}
        />
      ))}
      {lista.total > lista.items.length &&
        aviso(`Se muestran ${lista.items.length} de ${lista.total} campañas: filtrá por este programa en la vista Lista para verlas todas.`)}
    </>
  );
}

function Grupo({ grupo, abierto, onAlternar, ...resto }) {
  const nombre = grupo.programa_id == null ? 'Sin programa' : grupo.nombre;
  const Chevron = abierto ? ChevronDown : ChevronRight;
  return (
    <tbody>
      <tr className={styles.grupo}>
        <td colSpan={resto.columnas}>
          <div className={styles.cabecera}>
            <button type="button" className={styles.alternar} aria-expanded={abierto} onClick={onAlternar}>
              <Chevron size={16} aria-hidden="true" />
              <span className={styles.nombre}>{nombre}</span>
            </button>
            <span className={styles.resumen}>{resumenDeGrupo(grupo)}</span>
            {grupo.activas > 0 && (
              <span className={styles.activas}>
                <StatusPill tone="success">{textoActivas(grupo.activas)}</StatusPill>
              </span>
            )}
          </div>
        </td>
      </tr>
      {abierto && <CampanasDelGrupo grupo={grupo} {...resto} />}
    </tbody>
  );
}

/**
 * The "Por programa" view of the sell-out campaigns (campanas-sistema slice E): one row per program with campaigns
 * under the list's filters (`GET /sell-out/campanas/por-programa`, so a program with none is not shown and the
 * request count stays one per page of groups), then "Sin programa". Expanding a group reads its campaigns with the
 * same filters plus the program, shown with the flat list's row (checkbox, "Ver campaña", "Renovar"). A new `version` reads
 * the groups and the open ones again. `seleccion` / `onToggle` come from the bulk bar; without them there are no
 * checkboxes.
 */
export default function SellOutPorPrograma({ filtros, version, seleccion, onToggle, selectedId, onSelect, onRenovar }) {
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(GRUPOS_POR_PAGINA);
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState(false);
  const [abiertos, setAbiertos] = useState(() => new Set());
  const clave = JSON.stringify(filtros);
  useEffect(() => {
    let activo = true;
    setError(false);
    sellOutAPI
      .porPrograma({ ...JSON.parse(clave), page: Math.floor(offset / pageSize) + 1, page_size: pageSize })
      .then(({ data }) => activo && setDatos(data))
      .catch(() => activo && setError(true));
    return () => {
      activo = false;
    };
  }, [clave, version, offset, pageSize]);

  // A reload can leave the page past the end (its last groups' campaigns moved): go to the last page with groups.
  const fueraDeRango = datos != null && datos.total > 0 && offset >= datos.total;
  useEffect(() => {
    if (fueraDeRango) setOffset((Math.ceil(datos.total / pageSize) - 1) * pageSize);
  }, [fueraDeRango, datos, pageSize]);

  if (error) {
    return (
      <div className={styles.aviso} role="alert">
        No se pudieron cargar los programas.
      </div>
    );
  }
  if (!datos) return <div className={styles.aviso}>Cargando programas…</div>;

  const seleccionable = seleccion != null;
  const columnas = columnasCampanas(seleccionable);
  const ultimaPagina = offset + pageSize >= datos.total;
  const grupos = [...datos.items, ...(ultimaPagina && datos.sin_programa ? [datos.sin_programa] : [])];
  const claveDe = (g) => (g.programa_id == null ? 'sin' : `p${g.programa_id}`);
  const alternar = (k) =>
    setAbiertos((actual) => {
      const siguiente = new Set(actual);
      if (siguiente.has(k)) siguiente.delete(k);
      else siguiente.add(k);
      return siguiente;
    });

  return (
    <>
      <div className={tableStyles.scroller}>
        <table className={tableStyles.table}>
          <CabeceraCampanas seleccionable={seleccionable} />
          {grupos.length === 0 && (
            <tbody>
              <tr>
                <td colSpan={columnas} className={tableStyles.empty}>
                  No hay campañas de sell out.
                </td>
              </tr>
            </tbody>
          )}
          {grupos.map((g) => (
            <Grupo
              key={claveDe(g)}
              grupo={g}
              abierto={abiertos.has(claveDe(g))}
              onAlternar={() => alternar(claveDe(g))}
              filtros={filtros}
              version={version}
              columnas={columnas}
              seleccion={seleccion}
              onToggle={onToggle}
              selectedId={selectedId}
              onSelect={onSelect}
              onRenovar={onRenovar}
            />
          ))}
        </table>
      </div>
      {datos.total > GRUPOS_POR_PAGINA && (
        <Pagination
          total={datos.total}
          offset={offset}
          pageSize={pageSize}
          onOffsetChange={setOffset}
          onPageSizeChange={(size) => {
            setPageSize(size);
            setOffset(0);
          }}
          pageSizeOptions={[GRUPOS_POR_PAGINA, 100, 200]}
          summary={<span>{plural(datos.total, 'programa', 'programas')}</span>}
        />
      )}
    </>
  );
}
