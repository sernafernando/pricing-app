import { StatusPill } from '../kit';
import { formatDateOnly } from '../../utils/dateUtils';
import { formatEntero, formatMonto } from '../sellIn/sellInFormat';
import SellOutMonto from './SellOutMonto';
import { beneficio, cuantosItems, esDeduccion } from './sellOutFormat';
import { columnasCampanas } from './sellOutProgramas';
import styles from '../sellIn/SellInTable.module.css';
import repartoStyles from './SellOutReparto.module.css';
import filaStyles from './SellOutCampanasTable.module.css';

const DIA = { day: '2-digit', month: '2-digit', year: 'numeric' };

/** The table's header row; with `onTogglePagina` its first cell selects the page, with `seleccionable` alone it is empty. */
export function CabeceraCampanas({ seleccionable, paginaSeleccionada, onTogglePagina, vacia }) {
  return (
    <thead>
      <tr>
        {seleccionable && (
          <th>
            {onTogglePagina && (
              <input
                type="checkbox"
                aria-label="Seleccionar la página"
                checked={paginaSeleccionada}
                onChange={onTogglePagina}
                disabled={vacia}
              />
            )}
          </th>
        )}
        <th>Campaña</th>
        <th>Beneficio</th>
        <th>Vigencia</th>
        <th className={styles.num}>Acreditado</th>
        <th>Estado</th>
        <th aria-label="Acciones" />
      </tr>
    </thead>
  );
}

/**
 * One campaign row: the same in the flat list and inside a program group (`SellOutPorPrograma`). With `onRenovar`
 * (`sell_out.gestionar`) it also has "Renovar", the panel's renewal: it gets the campaign id.
 */
export function CampanaFila({ campana, selectedId, onSelect, seleccion, onToggle, onRenovar }) {
  return (
    <tr className={selectedId === campana.id ? styles.rowSelected : ''}>
      {seleccion != null && (
        <td>
          <input
            type="checkbox"
            aria-label={`Seleccionar ${campana.nombre}`}
            checked={seleccion.has(campana.id)}
            onChange={() => onToggle(campana)}
          />
        </td>
      )}
      <td>
        <div>{campana.nombre}</div>
        <span className={filaStyles.idChip}>{`ID #${campana.id}`}</span>
        {campana.offset_origen_id != null && <div className={styles.sub}>{`Del offset #${campana.offset_origen_id}`}</div>}
      </td>
      <td>
        <div>
          {campana.tipo === 'monto_total' ? (
            <>
              Monto total <SellOutMonto value={campana.monto_total} moneda={campana.moneda} />
            </>
          ) : (
            beneficio(campana)
          )}
        </div>
        {esDeduccion(campana) && <div className={`${styles.sub} ${repartoStyles.deduccion}`}>Deducción de ganancia</div>}
        {campana.items?.length > 0 && <div className={styles.sub}>{cuantosItems(campana)}</div>}
      </td>
      <td>{`${formatDateOnly(campana.fecha_desde, DIA)} – ${formatDateOnly(campana.fecha_hasta, DIA)}`}</td>
      <td className={styles.num}>
        <div>{`${formatEntero(campana.resumen?.unidades)} u`}</div>
        <div className={styles.sub}>{formatMonto(campana.resumen?.monto, campana.moneda)}</div>
      </td>
      <td>
        <StatusPill tone={campana.estado === 'activa' ? 'success' : 'danger'}>
          {campana.estado === 'activa' ? 'Activa' : 'Anulada'}
        </StatusPill>
      </td>
      <td>
        <div className={filaStyles.acciones}>
          <button type="button" className="btn-tesla ghost sm" onClick={() => onSelect(campana.id)}>
            Ver campaña
          </button>
          {onRenovar && (
            <button type="button" className="btn-tesla ghost sm" onClick={() => onRenovar(campana.id)}>
              Renovar
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

/**
 * The sell-out campaigns (`GET /sell-out/campanas`), with what each one credited; "Ver campaña" opens it (`onSelect`).
 * With `seleccion` (a `Map` keyed by id, `SellOutAnularMasivo`) each row and the header get a checkbox; with
 * `onRenovar`, each row gets "Renovar".
 */
export default function SellOutCampanasTable({
  campanas,
  selectedId,
  onSelect,
  onRenovar,
  seleccion,
  onToggle,
  paginaSeleccionada,
  onTogglePagina,
}) {
  const seleccionable = seleccion != null;
  return (
    <div className={styles.scroller}>
      <table className={styles.table}>
        <CabeceraCampanas
          seleccionable={seleccionable}
          paginaSeleccionada={paginaSeleccionada}
          onTogglePagina={onTogglePagina}
          vacia={campanas.length === 0}
        />
        <tbody>
          {campanas.length === 0 && (
            <tr>
              <td colSpan={columnasCampanas(seleccionable)} className={styles.empty}>
                No hay campañas de sell out.
              </td>
            </tr>
          )}
          {campanas.map((campana) => (
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
        </tbody>
      </table>
    </div>
  );
}
