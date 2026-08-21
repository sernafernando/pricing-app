/**
 * Asks for the REASON before accepting an anomaly as intentional.
 *
 * The reason is mandatory on purpose. An exception with no stated
 * justification is indistinguishable, a year later, from someone silencing
 * an alert they did not understand — and this mechanism exists precisely
 * so "reviewed and fine" stays distinguishable from "hidden".
 *
 * The evidence being accepted is shown verbatim above the field: the
 * operator confirms a CONCRETE SITUATION, not a product. If that evidence
 * changes (a different SKU loaded in TN), the acceptance stops applying
 * and the anomaly comes back for review — which is exactly why the copy
 * says so out loud.
 *
 * Built on `ModalTesla` rather than a hand-rolled overlay: focus trap, ESC
 * and click-outside come with it.
 */
import { useState } from 'react';
import ModalTesla from '../ModalTesla';
import styles from '../../pages/TiendaNubeReconcile.module.css';

const MOTIVO_MINIMO = 3;

export default function ExcepcionModal({ row, onCancel, onConfirm }) {
  const [motivo, setMotivo] = useState('');
  const [enviando, setEnviando] = useState(false);

  if (!row) return null;

  const detalle = row.reason_detail || {};
  const motivoValido = motivo.trim().length >= MOTIVO_MINIMO;

  async function handleConfirm() {
    if (!motivoValido || enviando) return;
    setEnviando(true);
    try {
      await onConfirm(row, motivo.trim());
    } finally {
      setEnviando(false);
    }
  }

  return (
    <ModalTesla
      isOpen
      onClose={onCancel}
      title="Aceptar como correcto"
      subtitle={row.ml_title || row.erp_desc || row.ean}
      size="sm"
      footer={
        <div data-testid="excepcion-acciones">
          <button type="button" className="btn-tesla ghost sm" onClick={onCancel} disabled={enviando}>
            Cancelar
          </button>
          <button
            type="button"
            className="btn-tesla outline sm"
            onClick={handleConfirm}
            disabled={!motivoValido || enviando}
          >
            {enviando ? 'Aceptando...' : 'Aceptar como correcto'}
          </button>
        </div>
      }
    >
      <p className={styles.excepcionHint}>
        Marca esta situación puntual como revisada e intencional. La fila NO desaparece del reporte: queda visible
        como aceptada, con el motivo y quién la aceptó.
      </p>

      <dl className={styles.excepcionEvidencia} data-testid="excepcion-evidencia">
        <div>
          <dt>Veredicto</dt>
          <dd>{row.verdict}</dd>
        </div>
        {detalle.expected_ean && (
          <div>
            <dt>EAN GBP</dt>
            <dd>
              <code>{detalle.expected_ean}</code>
            </dd>
          </div>
        )}
        {detalle.tn_sku_found && (
          <div>
            <dt>SKU en TN</dt>
            <dd>
              <code>{detalle.tn_sku_found}</code>
            </dd>
          </div>
        )}
      </dl>

      <p className={styles.excepcionHint}>
        Si esos valores cambian en Tienda Nube, la excepción deja de aplicar y el producto vuelve a aparecer para
        revisar.
      </p>

      <label className={styles.excepcionLabel} htmlFor="excepcion-motivo">
        Motivo (obligatorio)
      </label>
      <textarea
        id="excepcion-motivo"
        className={styles.excepcionMotivo}
        rows={3}
        value={motivo}
        placeholder="Ej.: el proveedor factura con otro código, verificado con compras"
        onChange={(e) => setMotivo(e.target.value)}
      />
    </ModalTesla>
  );
}
