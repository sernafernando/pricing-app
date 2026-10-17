import { useEffect, useId, useState } from 'react';
import { X } from 'lucide-react';
import { sellInAPI } from '../../services/sellInAPI';
import { formatDateOnly } from '../../utils/dateUtils';
import { StatusPill } from '../kit';
import SellInLineas from './SellInLineas';
import { FORMULA_LABELS, apiMessage, formatEntero, formatMonto, formatNumero } from './sellInFormat';
import styles from './SellInPanel.module.css';

const MOTIVO_MAX = 500; // backend `SellInAnularIn.motivo` (auditoria.comentario is VARCHAR(500))
const CUENTA_DESDE = { compra: 'Fecha de compra', ingreso: 'Fecha de ingreso' };

/**
 * One sell-in purchase in the side panel, read fresh from `GET /{id}`. With
 * `sell_in.gestionar` an active purchase can be voided after an inline
 * confirmation (no modal); there is no edit: a wrong one is voided and loaded again.
 */
export default function SellInDetailPanel({ compraId, puedeGestionar, onChanged, onClose }) {
  const id = useId();
  const [compra, setCompra] = useState(null);
  const [error, setError] = useState(null);
  const [confirmando, setConfirmando] = useState(false);
  const [motivo, setMotivo] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    setCompra(null);
    setError(null);
    setConfirmando(false);
    sellInAPI
      .detalle(compraId)
      .then(({ data }) => active && setCompra(data))
      .catch((err) => active && setError(apiMessage(err, 'No se pudo cargar el sell in.')));
    return () => {
      active = false;
    };
  }, [compraId]);

  const anular = async () => {
    setBusy(true);
    setError(null);
    try {
      const { data } = await sellInAPI.anular(compraId, motivo);
      setCompra(data);
      setConfirmando(false);
      onChanged(data);
    } catch (err) {
      setError(apiMessage(err, 'No se pudo anular el sell in.'));
    } finally {
      setBusy(false);
    }
  };

  const campos = compra
    ? [
        ['Proveedor', compra.proveedor_nombre ?? '—'],
        ['Fecha de compra', formatDateOnly(compra.fecha_compra)],
        ['Fecha de ingreso', compra.fecha_ingreso ? formatDateOnly(compra.fecha_ingreso) : '—'],
        ['Cuenta desde', CUENTA_DESDE[compra.cuenta_desde] ?? compra.cuenta_desde],
        ['Monto total', formatMonto(compra.monto_total, compra.moneda)],
        ['Tipo de cambio', compra.tipo_cambio ? formatNumero(compra.tipo_cambio) : '—'],
        ['Reparto', FORMULA_LABELS[compra.formula] ?? compra.formula],
        ['Pedido de compra', compra.pedido_compra_id ?? '—'],
        ['Unidades', `${formatEntero(compra.unidades_consumidas)} consumidas · ${formatEntero(compra.unidades_restantes)} restantes`],
      ]
    : [];

  return (
    <div className={styles.panel}>
      <header className={styles.panelHeader}>
        <h2>{compra ? compra.descripcion || `Sell in #${compra.id}` : 'Sell in'}</h2>
        <button type="button" className={styles.close} aria-label="Cerrar" onClick={onClose}>
          <X size={18} />
        </button>
      </header>

      <div className={styles.panelBody}>
        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
        {!compra && !error && <p className={styles.hint}>Cargando…</p>}
        {compra && (
          <>
            <div className={styles.pills}>
              <StatusPill tone={compra.estado === 'activa' ? 'success' : 'danger'}>
                {compra.estado === 'activa' ? 'Activa' : 'Anulada'}
              </StatusPill>
              <StatusPill tone={compra.aplica ? 'success' : 'neutral'}>{compra.aplica ? 'Aplica' : 'No aplica'}</StatusPill>
            </div>
            <dl className={styles.campos}>
              {campos.map(([label, value]) => (
                <div key={label} className={styles.campo}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
            <SellInLineas compra={compra} />
          </>
        )}
      </div>

      {compra && puedeGestionar && compra.estado === 'activa' && (
        <footer className={styles.panelFooter}>
          {confirmando ? (
            <div className={styles.confirm}>
              <label className={styles.field} htmlFor={`${id}-motivo`}>
                <span className={styles.label}>Motivo (opcional)</span>
                <textarea id={`${id}-motivo`} className={styles.textarea} maxLength={MOTIVO_MAX} value={motivo} onChange={(e) => setMotivo(e.target.value)} />
              </label>
              <div className={styles.confirmActions}>
                <button type="button" className="btn-tesla outline sm" onClick={() => setConfirmando(false)} disabled={busy}>
                  Cancelar
                </button>
                <button type="button" className="btn-tesla danger sm" onClick={anular} disabled={busy}>
                  Confirmar anulación
                </button>
              </div>
            </div>
          ) : (
            <button type="button" className="btn-tesla outline sm" onClick={() => setConfirmando(true)}>
              Anular
            </button>
          )}
        </footer>
      )}
    </div>
  );
}
