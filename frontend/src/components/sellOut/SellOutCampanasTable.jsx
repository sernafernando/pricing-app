import { StatusPill } from '../kit';
import { formatDateOnly } from '../../utils/dateUtils';
import { formatEntero, formatMonto } from '../sellIn/sellInFormat';
import { beneficio } from './sellOutFormat';
import styles from '../sellIn/SellInTable.module.css';

const DIA = { day: '2-digit', month: '2-digit', year: 'numeric' };

/** The sell-out campaigns (`GET /sell-out/campanas`), with what each one credited; "Ver campaña" opens it (`onSelect`). */
export default function SellOutCampanasTable({ campanas, selectedId, onSelect }) {
  return (
    <div className={styles.scroller}>
      <table className={styles.table}>
        <thead>
          <tr>
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
              <td colSpan={6} className={styles.empty}>
                No hay campañas de sell out.
              </td>
            </tr>
          )}
          {campanas.map((campana) => (
            <tr key={campana.id} className={selectedId === campana.id ? styles.rowSelected : ''}>
              <td>
                <div>{campana.nombre}</div>
                {campana.offset_origen_id && <div className={styles.sub}>{`Del offset #${campana.offset_origen_id}`}</div>}
              </td>
              <td>{beneficio(campana)}</td>
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
