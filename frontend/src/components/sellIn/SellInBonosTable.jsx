import { StatusPill } from '../kit';
import { formatDateOnly } from '../../utils/dateUtils';
import { alcanceDeBono, esBonoCosto, origenDeBono, restanteDeTope } from './sellInBonoValores';
import { formatEntero, formatMonto, formatPorcentaje } from './sellInFormat';
import styles from './SellInTable.module.css';

const DIA = { day: '2-digit', month: '2-digit', year: 'numeric' };

/** How a bonus pays: "USD 3,00 / u", "2,5 % de lo facturado" or, over the sale's cost, "2,71 % del costo". */
const montoDeBono = (bono) => {
  if (esBonoCosto(bono)) return `${formatPorcentaje(bono.porcentaje)} del costo`;
  return bono.tipo === 'porcentaje' ? `${formatPorcentaje(bono.porcentaje)} de lo facturado` : `${formatMonto(bono.monto_unit, bono.moneda)} / u`;
};

/** What the bonus reached: purchases and their units, or (over the sale's cost) the units of its sales. */
const alcanzadasDeBono = (bono) =>
  esBonoCosto(bono) ? `${formatEntero(bono.unidades)} u en ventas` : `${formatEntero(bono.compras_activas)} compras · ${formatEntero(bono.unidades)} u`;

/** What is left of the bonus's shared cap, or nothing without one. */
function TopeRestante({ bono }) {
  const restante = restanteDeTope(bono, formatEntero, formatMonto);
  return restante ? <div className={styles.sub}>{`Tope: quedan ${restante}`}</div> : null;
}

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
              <td>
                <div>{bono.descripcion || <span className={styles.muted}>Sin descripción</span>}</div>
                {esBonoCosto(bono) && <StatusPill tone="info">Sobre costo</StatusPill>}
                {origenDeBono(bono) && <div className={styles.sub}>{origenDeBono(bono)}</div>}
              </td>
              <td>{alcanceDeBono(bono)}</td>
              <td className={styles.num}>{montoDeBono(bono)}</td>
              <td>
                <div>{`${formatDateOnly(bono.fecha_desde, DIA)} – ${formatDateOnly(bono.fecha_hasta, DIA)}`}</div>
                {esBonoCosto(bono) && <div className={styles.sub}>Fecha de venta</div>}
              </td>
              <td className={styles.num}>
                <div>{alcanzadasDeBono(bono)}</div>
                <div className={styles.sub}>{formatMonto(bono.monto_generado, bono.moneda)}</div>
                <TopeRestante bono={bono} />
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
