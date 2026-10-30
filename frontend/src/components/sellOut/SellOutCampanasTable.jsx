import { StatusPill } from '../kit';
import { formatDateOnly } from '../../utils/dateUtils';
import { formatEntero, formatMonto } from '../sellIn/sellInFormat';
import SellOutMonto from './SellOutMonto';
import { beneficio, cuantosItems, esDeduccion } from './sellOutFormat';
import styles from '../sellIn/SellInTable.module.css';
import repartoStyles from './SellOutReparto.module.css';

const DIA = { day: '2-digit', month: '2-digit', year: 'numeric' };

/**
 * The sell-out campaigns (`GET /sell-out/campanas`), with what each one credited; "Ver campaña" opens it (`onSelect`).
 * With `seleccion` (a `Map` keyed by id, `SellOutAnularMasivo`) each row and the header get a checkbox.
 */
export default function SellOutCampanasTable({ campanas, selectedId, onSelect, seleccion, onToggle, paginaSeleccionada, onTogglePagina }) {
  const seleccionable = seleccion != null;
  return (
    <div className={styles.scroller}>
      <table className={styles.table}>
        <thead>
          <tr>
            {seleccionable && (
              <th>
                <input
                  type="checkbox"
                  aria-label="Seleccionar la página"
                  checked={paginaSeleccionada}
                  onChange={onTogglePagina}
                  disabled={campanas.length === 0}
                />
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
        <tbody>
          {campanas.length === 0 && (
            <tr>
              <td colSpan={seleccionable ? 7 : 6} className={styles.empty}>
                No hay campañas de sell out.
              </td>
            </tr>
          )}
          {campanas.map((campana) => (
            <tr key={campana.id} className={selectedId === campana.id ? styles.rowSelected : ''}>
              {seleccionable && (
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
                <button type="button" className="btn-tesla ghost sm" onClick={() => onSelect(campana.id)}>
                  Ver campaña
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
