import { useId } from 'react';
import { AlertTriangle, Ban, CheckCircle2, FileWarning } from 'lucide-react';
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

const SIN_GRUPO = { total: 0, items: [] };

/**
 * Why an in-range invoice produced no purchase. The backend flags the
 * worker's error with `es_error`; any other reason is shown as is.
 */
function motivo({ motivo: texto, intentos, es_error: esError }) {
  if (esError) return `Error al aplicar: ${texto} (${formatEntero(intentos)} ${intentos === 1 ? 'intento' : 'intentos'})`;
  return texto;
}

/**
 * What a brand bonus reaches (Stitch `03`), from `GET /sell-in/bonos/{id}/alcance`:
 * the purchases it generated, the brand's operations invoiced inside the range
 * that it did not apply (and why), the ones still waiting for their invoice,
 * and the ones invoiced outside the range. Each group is capped by the backend
 * and shows its full count. A reached purchase opens with `onVerCompra` when
 * given; without it its number is plain text.
 */
export default function SellInBonoAlcance({ alcance, onVerCompra }) {
  // `sin_aplicar` is newer than the panel: an older backend omits it.
  const { alcanzadas, pendientes, fuera_de_rango: fuera, sin_aplicar: sinAplicar = SIN_GRUPO } = alcance;
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

      <Grupo titulo="Con factura, sin aplicar" total={sinAplicar.total} mostrados={sinAplicar.items.length} icono={<FileWarning size={16} aria-hidden />} tono="warning">
        <p className={panel.hint}>Operaciones con productos del bono facturadas dentro de su rango que todavía no generaron una compra. Las unidades son las facturadas.</p>
        {sinAplicar.items.length === 0 ? (
          <p className={panel.hint}>Todas las operaciones facturadas dentro del rango están aplicadas.</p>
        ) : (
          <ul className={styles.lista}>
            {sinAplicar.items.map((p) => (
              <li key={p.pedido_id} className={styles.pedido}>
                {[p.numero, p.proveedor_nombre, `factura ${fecha(p.fecha_factura)}`, `${formatEntero(p.unidades)} u`].filter(Boolean).join(' · ')}
                <span className={styles.motivo}>{motivo(p)}</span>
              </li>
            ))}
          </ul>
        )}
      </Grupo>

      <Grupo titulo="Pendientes de factura" total={pendientes.total} mostrados={pendientes.items.length} icono={<AlertTriangle size={16} aria-hidden />} tono="warning">
        <p className={panel.hint}>Operaciones con productos del bono sin factura del proveedor vinculada. El bono se aplica cuando se vincula la factura. Las unidades son las recibidas.</p>
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
        <p className={panel.hint}>Operaciones con productos del bono facturadas fuera de su rango. Las unidades son las facturadas.</p>
        {fuera.items.length === 0 ? (
          <p className={panel.hint}>No hay operaciones fuera de rango.</p>
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
