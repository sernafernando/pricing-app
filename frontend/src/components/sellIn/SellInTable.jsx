import { Fragment, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { StatusPill } from '../kit';
import { formatDateOnly } from '../../utils/dateUtils';
import { FORMULA_LABELS, formatEntero, formatMonto, formatNumero } from './sellInFormat';
import styles from './SellInTable.module.css';

const COLUMNS = 9;

/** The purchase's lines: what each one got and its unit cost before and after the sell in. */
function Lineas({ compra }) {
  const { moneda } = compra;
  return (
    <div className={styles.lines}>
      <table className={styles.linesTable}>
        <thead>
          <tr>
            <th>Producto</th>
            <th className={styles.num}>Unid.</th>
            <th className={styles.num}>Monto asignado</th>
            <th className={styles.num}>Costo antes</th>
            <th className={styles.num}>Costo después</th>
            <th className={styles.num}>Consumidas</th>
          </tr>
        </thead>
        <tbody>
          {compra.items.map((linea) => (
            <tr key={linea.id}>
              <td>
                <span>{linea.descripcion}</span> <span className={styles.mono}>{linea.codigo}</span>
              </td>
              <td className={styles.num}>{formatEntero(linea.cantidad)}</td>
              <td className={styles.num}>{formatMonto(linea.monto_asignado, moneda)}</td>
              <td className={`${styles.num} ${styles.before}`}>{formatMonto(linea.costo_base_unit, moneda)}</td>
              <td className={`${styles.num} ${styles.after}`}>{formatMonto(linea.costo_con_sell_in_unit, moneda)}</td>
              <td className={styles.num}>{formatEntero(linea.unidades_consumidas)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className={styles.note}>
        {FORMULA_LABELS[compra.formula] ?? compra.formula} · al consumirse las unidades el costo vuelve al normal.
      </p>
    </div>
  );
}

/**
 * The sell-in purchases list. The chevron opens a row into its lines; a click
 * elsewhere on the row selects it (`onSelect`, the detail panel).
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
                  <td>{compra.descripcion || <span className={styles.muted}>Sin descripción</span>}</td>
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
                      <Lineas compra={compra} />
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
