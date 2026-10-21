import { Fragment, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { StatusPill } from '../kit';
import { formatDateOnly } from '../../utils/dateUtils';
import SellInLineas from './SellInLineas';
import { formatEntero, formatMonto, formatNumero } from './sellInFormat';
import styles from './SellInTable.module.css';

const COLUMNS = 9;

/**
 * The sell-in purchases list. The chevron opens a row into its lines; a click
 * elsewhere on the row selects it (`onSelect`, the detail panel). A purchase a
 * brand bonus generated carries a "Bono de marca" badge.
 */
export default function SellInTable({ compras, selectedId, onSelect }) {
  const [abiertas, setAbiertas] = useState(() => new Set());
  const toggle = (id) =>
    setAbiertas((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className={styles.scroller}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th aria-label="Expandir" />
            <th>Descripción</th>
            <th>Proveedor</th>
            <th>Fecha compra</th>
            <th className={styles.num}>Monto</th>
            <th className={styles.num}>Unidades</th>
            <th>Estado</th>
            <th>Aplicación</th>
            <th aria-label="Acciones" />
          </tr>
        </thead>
        <tbody>
          {compras.length === 0 && (
            <tr>
              <td colSpan={COLUMNS} className={styles.empty}>
                No hay sell in con estos filtros.
              </td>
            </tr>
          )}
          {compras.map((compra) => {
            const abierta = abiertas.has(compra.id);
            return (
              <Fragment key={compra.id}>
                <tr className={`${abierta ? styles.rowOpen : ''} ${selectedId === compra.id ? styles.rowSelected : ''}`}>
                  <td>
                    <button
                      type="button"
                      className={styles.expander}
                      aria-label="Ver ítems"
                      aria-expanded={abierta}
                      onClick={() => toggle(compra.id)}
                    >
                      {abierta ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </button>
                  </td>
                  <td>
                    <div>{compra.descripcion || <span className={styles.muted}>Sin descripción</span>}</div>
                    {compra.origen === 'bono_marca' && (
                      <div className={styles.origen}>
                        <StatusPill tone="purple">Bono de marca</StatusPill>
                      </div>
                    )}
                  </td>
                  <td>{compra.proveedor_nombre ?? <span className={styles.muted}>—</span>}</td>
                  <td>{formatDateOnly(compra.fecha_compra)}</td>
                  <td className={styles.num}>
                    <div>{formatMonto(compra.monto_total, compra.moneda)}</div>
                    {compra.tipo_cambio && <div className={styles.sub}>TC {formatNumero(compra.tipo_cambio)}</div>}
                  </td>
                  <td className={styles.num}>
                    {formatEntero(compra.unidades_restantes)} / {formatEntero(compra.unidades_total)}
                  </td>
                  <td>
                    <StatusPill tone={compra.estado === 'activa' ? 'success' : 'danger'}>
                      {compra.estado === 'activa' ? 'Activa' : 'Anulada'}
                    </StatusPill>
                  </td>
                  <td>
                    <StatusPill tone={compra.aplica ? 'success' : 'neutral'}>{compra.aplica ? 'Aplica' : 'No aplica'}</StatusPill>
                  </td>
                  <td>
                    {onSelect && (
                      <button type="button" className="btn-tesla ghost sm" onClick={() => onSelect(compra.id)}>
                        Detalle
                      </button>
                    )}
                  </td>
                </tr>
                {abierta && (
                  <tr className={styles.subRow}>
                    <td colSpan={COLUMNS}>
                      <SellInLineas compra={compra} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
