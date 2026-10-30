import { useState } from 'react';
import { X } from 'lucide-react';
import { sellOutAPI } from '../../services/sellOutAPI';
import { formatDateOnly } from '../../utils/dateUtils';
import SellInBuscador from '../sellIn/SellInBuscador';
import { apiMessage, formatMonto, formatPorcentaje } from '../sellIn/sellInFormat';
import SellOutMonto from './SellOutMonto';
import { buscarProductos } from './sellOutBuscar';
import { nombreDeItem } from './sellOutFormat';
import {
  MODO_MONTO,
  MODO_PORCENTAJE,
  aCentavos,
  centavosAjenos,
  centavosDeFila,
  errorDeReparto,
  filasDeCampana,
  repartosDeFilas,
  totalesDeReparto,
} from './sellOutReparto';
import panelStyles from '../sellIn/SellInPanel.module.css';
import tableStyles from '../sellIn/SellInTable.module.css';
import styles from './SellOutReparto.module.css';

const DIA = { day: '2-digit', month: '2-digit', year: 'numeric' };


/**
 * The split of a `monto_total` campaign among its products (T26d, S34/S35). Everyone who sees the campaign gets
 * the server's summary (`resumen.reparto`: assigned, assigned to products without sales, unassigned, or why it
 * cannot be computed) and the shares. With `editable` (`sell_out.repartir` or `sell_out.gestionar`, active campaign)
 * the PM adds products, picks "%" or "Monto fijo" for each, sees the live totals and saves with `PUT /reparto`.
 * The client guard mirrors the API's; the API's own 422/403 message shows when it refuses. `onGuardado` gets the
 * campaign as read again after saving; `busy` / `onBusyChange` are the panel's: one request at a time.
 */
export default function SellOutReparto({ campana, editable = false, busy = false, onBusyChange = () => {}, onGuardado }) {
  const [filas, setFilas] = useState(() => filasDeCampana(campana));
  const [error, setError] = useState(null);
  const { moneda } = campana;
  const total = campana.monto_total;
  const resumen = campana.resumen?.reparto;
  const totalCentavos = aCentavos(total);
  // A brand-scoped PM holds only their brands' shares; the server keeps (and counts) the others.
  const ajenos = centavosAjenos(campana);
  const enVivo = totalesDeReparto(total, filas, ajenos);

  const cambiar = (itemId, patch) => setFilas(filas.map((f) => (f.itemId === itemId ? { ...f, ...patch } : f)));
  const agregar = ({ producto }) => {
    if (filas.some((f) => f.itemId === producto.item_id)) return;
    setFilas([
      ...filas,
      { itemId: producto.item_id, codigo: producto.codigo, descripcion: producto.descripcion, modo: MODO_PORCENTAJE, valor: '' },
    ]);
  };

  const guardar = async () => {
    const invalido = errorDeReparto(total, filas, moneda, ajenos);
    if (invalido) {
      setError(invalido);
      return;
    }
    onBusyChange(true);
    setError(null);
    try {
      const { data } = await sellOutAPI.repartir(campana.id, repartosDeFilas(filas));
      // A scoped PM's PUT answers only their shares: read the campaign again rather than keep that subset.
      const fresca = await sellOutAPI
        .detalle(campana.id)
        .then((r) => r.data)
        .catch(() => data);
      onGuardado(fresca);
    } catch (err) {
      setError(apiMessage(err, 'No se pudo guardar el reparto.'));
    } finally {
      onBusyChange(false);
    }
  };

  return (
    <section className={panelStyles.section} aria-label="Reparto del monto total">
      <h3>Reparto del monto total</h3>
      <dl className={panelStyles.campos}>
        {[
          ['Asignado', resumen?.asignado],
          ['Asignado sin ventas', resumen?.asignado_sin_ventas],
          ['Sin asignar', resumen?.sin_asignar],
        ].map(([label, value]) => (
          <div key={label} className={panelStyles.campo}>
            <dt>{label}</dt>
            <dd>
              <SellOutMonto value={value} moneda={moneda} />
            </dd>
          </div>
        ))}
      </dl>
      {resumen?.motivo && <p className={panelStyles.error}>{resumen.motivo}</p>}
      <p className={panelStyles.hint}>
        {`Lo sin asignar (y lo asignado a productos sin ventas) suma en los totales el ${formatDateOnly(campana.fecha_hasta, DIA)}, no en la fila de ningún producto.`}
      </p>

      {editable ? (
        <>
          <SellInBuscador
            label="Agregar producto"
            placeholder="Buscar por código o descripción…"
            buscar={buscarProductos}
            onPick={agregar}
            errorMessage="No se pudieron buscar productos."
          />
          {filas.length === 0 && <p className={panelStyles.hint}>Todavía no se repartió: todo el monto está sin asignar.</p>}
          {filas.map((fila) => {
            const nombre = nombreDeItem(fila);
            const importe = centavosDeFila(totalCentavos, fila);
            return (
              <div key={fila.itemId} className={styles.fila}>
                <span className={styles.filaNombre}>
                  <span className={panelStyles.mono}>{nombre}</span> {fila.descripcion}
                </span>
                <select
                  className={styles.modo}
                  aria-label={`Tipo de reparto de ${nombre}`}
                  value={fila.modo}
                  onChange={(e) => cambiar(fila.itemId, { modo: e.target.value })}
                >
                  <option value={MODO_PORCENTAJE}>%</option>
                  <option value={MODO_MONTO}>Monto fijo</option>
                </select>
                <input
                  type="number"
                  step={fila.modo === MODO_PORCENTAJE ? '0.0001' : '0.01'}
                  className={styles.valor}
                  aria-label={`Reparto de ${nombre}`}
                  placeholder={fila.modo === MODO_PORCENTAJE ? '%' : `Monto (${moneda})`}
                  value={fila.valor}
                  onChange={(e) => cambiar(fila.itemId, { valor: e.target.value })}
                />
                <span className={styles.importe}>
                  {importe === null ? '—' : <SellOutMonto value={importe / 100} moneda={moneda} />}
                </span>
                <button
                  type="button"
                  className={panelStyles.close}
                  aria-label={`Quitar ${nombre}`}
                  onClick={() => setFilas(filas.filter((f) => f.itemId !== fila.itemId))}
                >
                  <X size={14} />
                </button>
              </div>
            );
          })}
          {ajenos !== 0 && (
            <p className={panelStyles.hint}>
              {`Incluye ${formatMonto(ajenos / 100, moneda)} de productos de otras marcas, que no se ven ni se cambian acá.`}
            </p>
          )}
          <div className={styles.enVivo} data-testid="reparto-en-vivo">
            <span>
              Asignado <SellOutMonto value={enVivo.asignado} moneda={moneda} />
            </span>
            <span>
              Sin asignar <SellOutMonto value={enVivo.sinAsignar} moneda={moneda} />
            </span>
          </div>
          {error && (
            <p className={panelStyles.error} role="alert">
              {error}
            </p>
          )}
          <div className={styles.acciones}>
            <button type="button" className="btn-tesla primary sm" onClick={guardar} disabled={busy}>
              Guardar reparto
            </button>
          </div>
        </>
      ) : filas.length === 0 ? (
        <p className={panelStyles.hint}>Todavía no se repartió: todo el monto está sin asignar.</p>
      ) : (
        <table className={tableStyles.table}>
          <thead>
            <tr>
              <th>Producto</th>
              <th className={tableStyles.num}>Reparto</th>
              <th className={tableStyles.num}>Monto</th>
            </tr>
          </thead>
          <tbody>
            {filas.map((fila) => {
              const importe = centavosDeFila(totalCentavos, fila);
              return (
                <tr key={fila.itemId}>
                  <td>
                    <span className={panelStyles.mono}>{nombreDeItem(fila)}</span> {fila.descripcion}
                  </td>
                  <td className={tableStyles.num}>{fila.modo === MODO_PORCENTAJE ? formatPorcentaje(fila.valor) : 'Monto fijo'}</td>
                  <td className={tableStyles.num}>{importe === null ? '—' : <SellOutMonto value={importe / 100} moneda={moneda} />}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
