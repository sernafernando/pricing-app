import { useCallback, useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Plus, X, Loader2 } from 'lucide-react';
import ModalCheque from '../ModalCheque';
import styles from './PanelCheques.module.css';

/**
 * PanelCheques — panel colapsable de cheques propios como VALOR en la OP.
 *
 * Espejo de PanelNCsProveedor (mode="seleccionar") pero para cheques.
 * El cheque es un VALOR: cubre parte del total a pagar, como la NC.
 * NO es una fuente de fondos (caja/banco).
 *
 * Al hacer click en "Emitir cheque", abre ModalCheque en mode="op".
 * El modal llama onEmitido(payload) sin ir al backend.
 * Este panel acumula la lista y notifica al padre vía onChange([...]).
 *
 * Props:
 *   proveedorId   (number|null) — id del proveedor; si es null no muestra el panel.
 *   empresaId     (number|null) — filtra bancos de empresa para el modal.
 *   opMoneda      (string)      — moneda de la OP; para mostrar equivalentes cross-moneda.
 *   onChange      ([cheques]) => void — notifica al padre los cheques acumulados.
 *   disabled      (bool)        — desactiva botones.
 */

const formatCurrency = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export default function PanelCheques({
  proveedorId,
  empresaId,
  opMoneda,
  onChange,
  disabled = false,
}) {
  const [abierto, setAbierto] = useState(false);
  const [chequesEmitidos, setChequesEmitidos] = useState([]);
  const [showModalEmitir, setShowModalEmitir] = useState(false);

  // Reset when proveedor changes.
  useEffect(() => {
    setChequesEmitidos([]);
    if (onChange) onChange([]);
  }, [proveedorId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleEmitido = useCallback(
    (payload) => {
      const next = [...chequesEmitidos, payload];
      setChequesEmitidos(next);
      if (onChange) onChange(next);
      setShowModalEmitir(false);
    },
    [chequesEmitidos, onChange],
  );

  const handleQuitar = useCallback(
    (idx) => {
      const next = chequesEmitidos.filter((_, i) => i !== idx);
      setChequesEmitidos(next);
      if (onChange) onChange(next);
    },
    [chequesEmitidos, onChange],
  );

  if (!proveedorId) return null;

  return (
    <div className={styles.wrapper}>
      <button
        type="button"
        className={styles.toggleBtn}
        onClick={() => setAbierto((v) => !v)}
        aria-expanded={abierto}
      >
        Cheques{chequesEmitidos.length > 0 ? ` (${chequesEmitidos.length})` : ''}{' '}
        {abierto ? (
          <ChevronDown size={14} className={styles.arrow} />
        ) : (
          <ChevronRight size={14} className={styles.arrow} />
        )}
      </button>

      {abierto && (
        <div className={styles.panel}>
          <p className={styles.panelHint}>
            Los cheques propios que emitas acá se descuentan del total a pagar (igual que NCs).
            Se emiten en la misma transacción al confirmar.
          </p>

          {/* Lista de cheques ya agregados */}
          {chequesEmitidos.length > 0 && (
            <div className={styles.lista}>
              {chequesEmitidos.map((ch, idx) => (
                <div key={idx} className={styles.chequeRow}>
                  <div className={styles.chequeInfo}>
                    <span className={styles.chequeNumero}>Nº {ch.numero}</span>
                    <span className={styles.chequeMonto}>
                      {formatCurrency(ch.monto, ch.moneda)} {ch.moneda}
                      {ch.moneda !== opMoneda && (
                        <span className={styles.crossMonedaTag}> (cross-moneda)</span>
                      )}
                    </span>
                    <span className={styles.chequeFecha}>
                      pago {ch.fecha_pago}
                      {ch.fecha_pago > ch.fecha_emision && (
                        <span className={styles.diferidoTag}> diferido</span>
                      )}
                    </span>
                  </div>
                  <button
                    type="button"
                    className={styles.btnQuitar}
                    onClick={() => handleQuitar(idx)}
                    disabled={disabled}
                    aria-label={`Quitar cheque ${ch.numero}`}
                  >
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}

          {!disabled && (
            <button
              type="button"
              className={styles.btnEmitir}
              onClick={() => setShowModalEmitir(true)}
            >
              <Plus size={13} />
              Emitir cheque propio
            </button>
          )}
        </div>
      )}

      {showModalEmitir && (
        <ModalCheque
          mode="op"
          proveedorId={proveedorId}
          empresaId={empresaId}
          onClose={() => setShowModalEmitir(false)}
          onEmitido={handleEmitido}
        />
      )}
    </div>
  );
}
