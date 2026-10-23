import { StatusPill } from '../kit';
import { formatDateOnly } from '../../utils/dateUtils';
import { alcanceDeBono } from './sellInBonoValores';
import { formatEntero, formatMonto, formatPorcentaje } from './sellInFormat';
import styles from './SellInTable.module.css';

const DIA = { day: '2-digit', month: '2-digit', year: 'numeric' };

/** How a bonus pays: "USD 3,00 / u" or "2,5 % de lo facturado". */
const montoDeBono = (bono) =>
  bono.tipo === 'porcentaje' ? `${formatPorcentaje(bono.porcentaje)} de lo facturado` : `${formatMonto(bono.monto_unit, bono.moneda)} / u`;

/** The bonuses (`GET /sell-in/bonos`): what each reaches, how it pays and what it generated; "Ver bono" opens it (`onSelect`). */
export default function SellInBonosTable({ bonos, selectedId, onSelect }) {
  return (
    <div className={styles.scroller}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Descripción</th>
            <th>Alcance</th>
            <th className={styles.num}>Monto</th>
            <th>Fecha de factura</th>
            <th className={styles.num}>Alcanzadas</th>
            <th>Estado</th>
            <th aria-label="Acciones" />
          </tr>
        </thead>
        <tbody>
          {bonos.length === 0 && (
            <tr>
              <td colSpan={7} className={styles.empty}>
                No hay bonos de marca.
              </td>
            </tr>
          )}
          {bonos.map((bono) => (
            <tr key={bono.id} className={selectedId === bono.id ? styles.rowSelected : ''}>
              <td>{bono.descripcion || <span className={styles.muted}>Sin descripción</span>}</td>
              <td>{alcanceDeBono(bono)}</td>
              <td className={styles.num}>{montoDeBono(bono)}</td>
              <td>{`${formatDateOnly(bono.fecha_desde, DIA)} – ${formatDateOnly(bono.fecha_hasta, DIA)}`}</td>
              <td className={styles.num}>
                <div>{`${formatEntero(bono.compras_activas)} compras · ${formatEntero(bono.unidades)} u`}</div>
                <div className={styles.sub}>{formatMonto(bono.monto_generado, bono.moneda)}</div>
              </td>
              <td>
                <StatusPill tone={bono.estado === 'activa' ? 'success' : 'danger'}>{bono.estado === 'activa' ? 'Activo' : 'Anulado'}</StatusPill>
              </td>
              <td>
                <button type="button" className="btn-tesla ghost sm" onClick={() => onSelect(bono.id)}>
                  Ver bono
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
