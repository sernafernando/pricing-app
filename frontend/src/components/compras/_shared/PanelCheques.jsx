import { useCallback, useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Plus, X, Loader2, Inbox, Library } from 'lucide-react';
import ModalCheque from '../ModalCheque';
import useCheques from '../../../hooks/useCheques';
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

/**
 * chequeAplicado shape:
 *
 *   Cheque propio (emisión nueva):
 *     { banco_empresa_id, chequera_id?, instrumento, numero, monto, moneda,
 *       fecha_emision, fecha_pago, proveedor_id }
 *     → sin cheque_id; el backend lo emite y lo imputa.
 *
 *   Cheque de tercero (endoso):
 *     { cheque_id, monto, moneda }
 *     → el backend reconoce la presencia de cheque_id y lo endosa.
 */

const formatDateShort = (dateStr) => {
  if (!dateStr) return '—';
  const [y, m, d] = dateStr.split('-');
  return `${d}/${m}/${y}`;
};

export default function PanelCheques({
  proveedorId,
  empresaId,
  opMoneda,
  onChange,
  disabled = false,
}) {
  const { listar, loading: loadingCartera } = useCheques();

  const [abierto, setAbierto] = useState(false);
  const [chequesEmitidos, setChequesEmitidos] = useState([]);
  const [showModalEmitir, setShowModalEmitir] = useState(false);

  // ── Cartera de terceros (para endoso) ──
  const [showSelectorCartera, setShowSelectorCartera] = useState(false);
  const [cartera, setCartera] = useState([]);
  const [loadingCarteraLocal, setLoadingCarteraLocal] = useState(false);

  const fetchCartera = useCallback(async () => {
    setLoadingCarteraLocal(true);
    try {
      const result = await listar({ tipo: 'tercero', estado: 'en_cartera', page_size: 200 });
      const items = result?.items ?? (Array.isArray(result) ? result : []);
      setCartera(items);
    } catch {
      setCartera([]);
    } finally {
      setLoadingCarteraLocal(false);
    }
  }, [listar]);

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

  // Endosar cheque de cartera: arma payload con cheque_id (no datos de emisión).
  const handleEndosar = useCallback(
    (cheque) => {
      // Evitar duplicados
      if (chequesEmitidos.some((c) => c.cheque_id === cheque.id)) return;
      const payload = {
        cheque_id: cheque.id,
        monto: cheque.monto,
        moneda: cheque.moneda,
        // numero y banco_nombre solo para mostrar en la lista
        _display_numero: cheque.numero,
        _display_banco: cheque.banco_nombre,
        _display_fecha_pago: cheque.fecha_pago,
        _es_endoso: true,
      };
      const next = [...chequesEmitidos, payload];
      setChequesEmitidos(next);
      if (onChange) onChange(next);
      setShowSelectorCartera(false);
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
              {chequesEmitidos.map((ch, idx) => {
                const esEndoso = ch._es_endoso === true;
                const numero = esEndoso ? ch._display_numero : ch.numero;
                const banco = esEndoso ? ch._display_banco : null;
                const fechaPago = esEndoso ? ch._display_fecha_pago : ch.fecha_pago;
                const esDiferido = !esEndoso && ch.fecha_pago > ch.fecha_emision;
                // Key estable: cheque_id (endoso) o numero (emisión). Evita que React
                // reconcilie la fila equivocada al quitar por índice.
                const rowKey = esEndoso ? `endoso-${ch.cheque_id}` : `propio-${ch.numero}`;
                return (
                  <div key={rowKey} className={`${styles.chequeRow} ${esEndoso ? styles.chequeRowEndoso : ''}`}>
                    <div className={styles.chequeInfo}>
                      {esEndoso && <span className={styles.tagEndoso}>Endoso</span>}
                      <span className={styles.chequeNumero}>Nº {numero}</span>
                      {banco && <span className={styles.chequeBanco}>{banco}</span>}
                      <span className={styles.chequeMonto}>
                        {formatCurrency(ch.monto, ch.moneda)} {ch.moneda}
                        {ch.moneda !== opMoneda && (
                          <span className={styles.crossMonedaTag}> (cross-moneda)</span>
                        )}
                      </span>
                      <span className={styles.chequeFecha}>
                        pago {fechaPago}
                        {esDiferido && (
                          <span className={styles.diferidoTag}> diferido</span>
                        )}
                      </span>
                    </div>
                    <button
                      type="button"
                      className={styles.btnQuitar}
                      onClick={() => handleQuitar(idx)}
                      disabled={disabled}
                      aria-label={`Quitar cheque ${numero}`}
                    >
                      <X size={12} />
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {!disabled && (
            <div className={styles.botonesAccion}>
              <button
                type="button"
                className={styles.btnEmitir}
                onClick={() => setShowModalEmitir(true)}
              >
                <Plus size={13} />
                Emitir cheque propio
              </button>
              <button
                type="button"
                className={styles.btnEmitir}
                onClick={() => {
                  fetchCartera();
                  setShowSelectorCartera(true);
                }}
              >
                <Library size={13} />
                Endosar de cartera
              </button>
            </div>
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

      {/* Selector de cartera para endoso */}
      {showSelectorCartera && (
        <div className={styles.selectorOverlay}>
          <div className={styles.selectorModal} role="dialog" aria-modal="true" aria-labelledby="selector-cartera-title">
            <header className={styles.selectorHeader}>
              <h3 id="selector-cartera-title" className={styles.selectorTitle}>
                Cheques en cartera
              </h3>
              <button
                type="button"
                className={styles.btnClose}
                onClick={() => setShowSelectorCartera(false)}
                aria-label="Cerrar"
              >
                <X size={16} />
              </button>
            </header>

            <div className={styles.selectorBody}>
              {loadingCarteraLocal || loadingCartera ? (
                <div className={styles.selectorLoading}>
                  <Loader2 size={18} className={styles.spin} />
                  <span>Cargando cartera...</span>
                </div>
              ) : cartera.length === 0 ? (
                <div className={styles.selectorEmpty}>
                  <Inbox size={28} />
                  <p>No hay cheques en cartera disponibles.</p>
                </div>
              ) : (
                <div className={styles.selectorLista}>
                  {cartera.map((ch) => {
                    const yaAgregado = chequesEmitidos.some((c) => c.cheque_id === ch.id);
                    return (
                      <button
                        key={ch.id}
                        type="button"
                        className={`${styles.selectorItem} ${yaAgregado ? styles.selectorItemUsado : ''}`}
                        onClick={() => handleEndosar(ch)}
                        disabled={yaAgregado}
                        aria-label={`Endosar cheque ${ch.numero}`}
                      >
                        <div className={styles.selectorItemInfo}>
                          <span className={styles.selectorNumero}>Nº {ch.numero}</span>
                          <span className={styles.selectorBanco}>{ch.banco_nombre ?? '—'}</span>
                          <span className={styles.selectorLibrador}>
                            {ch.librador_nombre ?? ch.cuit_librador ?? '—'}
                          </span>
                        </div>
                        <div className={styles.selectorItemRight}>
                          <span className={styles.selectorMonto}>
                            {formatCurrency(ch.monto, ch.moneda)} {ch.moneda}
                          </span>
                          <span className={styles.selectorFecha}>
                            pago {formatDateShort(ch.fecha_pago)}
                          </span>
                          {yaAgregado && (
                            <span className={styles.selectorTagUsado}>Ya agregado</span>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
