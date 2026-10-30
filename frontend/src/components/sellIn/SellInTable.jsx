import { Fragment, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { StatusPill } from '../kit';
import { formatDateOnly } from '../../utils/dateUtils';
import SellInLineas from './SellInLineas';
import { formatEntero, formatMonto, formatNumero } from './sellInFormat';
import styles from './SellInTable.module.css';

const COLUMNS = 9;

/** The checkbox column of the bulk void: a header box for the visible page and one per row. */
export function CheckPagina({ ids, seleccion, onTogglePagina, label }) {
  const marcadas = ids.filter((id) => seleccion.has(id)).length;
  return (
    <input
      type="checkbox"
      aria-label={label}
      checked={ids.length > 0 && marcadas === ids.length}
      ref={(el) => {
        if (el) el.indeterminate = marcadas > 0 && marcadas < ids.length;
      }}
      onChange={() => onTogglePagina(ids)}
    />
  );
}

/**
 * The sell-in purchases list. The chevron opens a row into its lines; a click
 * elsewhere on the row selects it (`onSelect`, the detail panel). A purchase a
 * brand bonus generated carries a "Bono de marca" badge and links to its bonus (`onVerBono`). With `seleccion` (a Set)
 * each row gets a checkbox for the bulk void (`onToggle`, `onTogglePagina`).
 */
export default function SellInTable({ compras, selectedId, onSelect, onVerBono, seleccion, onToggle, onTogglePagina }) {
  const columnas = COLUMNS + (seleccion ? 1 : 0);
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
            {seleccion && (
              <th>
                <CheckPagina ids={compras.map((c) => c.id)} seleccion={seleccion} onTogglePagina={onTogglePagina} label="Seleccionar la página de sell in" />
              </th>
            )}
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
              <td colSpan={columnas} className={styles.empty}>
                No hay sell in con estos filtros.
              </td>
            </tr>
          )}
          {compras.map((compra) => {
            const abierta = abiertas.has(compra.id);
            return (
              <Fragment key={compra.id}>
                <tr className={`${abierta ? styles.rowOpen : ''} ${selectedId === compra.id ? styles.rowSelected : ''}`}>
                  {seleccion && (
                    <td>
                      <input type="checkbox" aria-label={`Seleccionar compra #${compra.id}`} checked={seleccion.has(compra.id)} onChange={() => onToggle(compra.id)} />
                    </td>
                  )}
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
                        {onVerBono && (
                          <button type="button" className={styles.link} onClick={() => onVerBono(compra.bono_id)}>
                            {`Ver bono #${compra.bono_id}`}
                          </button>
                        )}
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
                    <td colSpan={columnas}>
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
