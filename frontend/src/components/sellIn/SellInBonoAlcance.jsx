import { useId } from 'react';
import { AlertTriangle, Ban, CheckCircle2 } from 'lucide-react';
import { formatDateOnly } from '../../utils/dateUtils';
import { formatEntero, formatMonto } from './sellInFormat';
import panel from './SellInPanel.module.css';
import styles from './SellInBonoAlcance.module.css';

const DIA = { day: '2-digit', month: '2-digit', year: 'numeric' };
const fecha = (value) => (value ? formatDateOnly(value, DIA) : '—');

function Grupo({ titulo, total, mostrados, icono, tono, children }) {
  const id = useId();
  const nombre = `${titulo} (${formatEntero(total)})`;
  return (
    <section className={`${panel.section} ${tono ? styles[tono] : ''}`} aria-labelledby={id}>
      <div className={panel.sectionHead}>
        <h3 id={id} className={styles.titulo}>
          {icono} {nombre}
        </h3>
        {total > mostrados && <span className={styles.conteo}>{`Mostrando ${formatEntero(mostrados)} de ${formatEntero(total)}`}</span>}
      </div>
      {children}
    </section>
  );
}

/** One operation the bonus does not reach, as a single line: number · supplier · detail · units. */
function Pedido({ pedido, detalle }) {
  const partes = [pedido.numero, pedido.proveedor_nombre, detalle, `${formatEntero(pedido.unidades)} u`].filter(Boolean);
  return <li className={styles.pedido}>{partes.join(' · ')}</li>;
}

/**
 * What a brand bonus reaches (Stitch `03`), from `GET /sell-in/bonos/{id}/alcance`:
 * the purchases it generated, the brand's operations still waiting for their
 * invoice, and the ones invoiced outside the range. Each group is capped by
 * the backend and shows its full count. A reached purchase opens with
 * `onVerCompra` when given; without it its number is plain text.
 */
export default function SellInBonoAlcance({ alcance, onVerCompra }) {
  const { alcanzadas, pendientes, fuera_de_rango: fuera } = alcance;
  return (
    <>
      <Grupo titulo="Compras alcanzadas" total={alcanzadas.total} mostrados={alcanzadas.items.length} icono={<CheckCircle2 size={16} aria-hidden />}>
        {alcanzadas.items.length === 0 ? (
          <p className={panel.hint}>Todavía no alcanzó ninguna compra.</p>
        ) : (
          <div className={styles.scroller}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Compra</th>
                  <th>Proveedor</th>
                  <th>Factura</th>
                  <th>Fecha</th>
                  <th className={styles.num}>Unid.</th>
                  <th className={styles.num}>Monto</th>
                </tr>
              </thead>
              <tbody>
                {alcanzadas.items.map((c) => (
                  <tr key={c.compra_id}>
                    <td>
                      {onVerCompra ? (
                        <button type="button" className={panel.linkButton} onClick={() => onVerCompra(c.compra_id)}>
                          {c.numero ?? `Sell in #${c.compra_id}`}
                        </button>
                      ) : (
                        (c.numero ?? `Sell in #${c.compra_id}`)
                      )}
                    </td>
                    <td>{c.proveedor_nombre ?? '—'}</td>
                    <td className={panel.mono}>{c.numero_factura ?? '—'}</td>
                    <td>{fecha(c.fecha_factura)}</td>
                    <td className={styles.num}>{formatEntero(c.unidades)}</td>
                    <td className={styles.num}>{formatMonto(c.monto, c.moneda)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Grupo>

      <Grupo titulo="Pendientes de factura" total={pendientes.total} mostrados={pendientes.items.length} icono={<AlertTriangle size={16} aria-hidden />} tono="warning">
        <p className={panel.hint}>Operaciones de la marca sin factura del proveedor vinculada. El bono se aplica cuando se vincula la factura. Las unidades son las recibidas.</p>
        {pendientes.items.length === 0 ? (
          <p className={panel.hint}>No hay operaciones pendientes de factura.</p>
        ) : (
          <ul className={styles.lista}>
            {pendientes.items.map((p) => (
              <Pedido key={p.pedido_id} pedido={p} detalle={p.numero_factura ? `Nro. ${p.numero_factura}` : null} />
            ))}
          </ul>
        )}
      </Grupo>

      <Grupo titulo="Fuera de rango" total={fuera.total} mostrados={fuera.items.length} icono={<Ban size={16} aria-hidden />}>
        <p className={panel.hint}>Operaciones de la marca facturadas fuera del rango del bono. Las unidades son las facturadas.</p>
        {fuera.items.length === 0 ? (
          <p className={panel.hint}>No hay operaciones de la marca fuera de rango.</p>
        ) : (
          <ul className={styles.lista}>
            {fuera.items.map((p) => (
              <Pedido key={p.pedido_id} pedido={p} detalle={`factura ${fecha(p.fecha_factura)}`} />
            ))}
          </ul>
        )}
      </Grupo>
    </>
  );
}
