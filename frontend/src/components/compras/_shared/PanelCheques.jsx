import { useCallback, useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Plus, X, Library, FileCheck2 } from 'lucide-react';
import ModalCheque from '../ModalCheque';
import useCheques from '../../../hooks/useCheques';
import useChequesAplicables from '../../../hooks/useChequesAplicables';
import SelectorListaModal from './SelectorListaModal';
import selectorStyles from './SelectorListaModal.module.css';
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
 *   pedidos       (Array<{id, numero, moneda}>) — pedidos de la OP. Con más de uno,
 *                 cada cheque pide destino explícito (mismo contrato que las NCs).
 *   onChange      ([cheques]) => void — notifica al padre los cheques acumulados.
 *   disabled      (bool)        — desactiva botones.
 *
 * Sobre `pedido_id`: con 0 o 1 pedido el destino es inequívoco y lo resuelven el
 * caller y el backend. Con 2+ hay que preguntarlo — sin eso el cheque no descuenta
 * de ningún ítem y el backend no sabe contra qué imputarlo.
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
  pedidos = [],
  onChange,
  disabled = false,
}) {
  const requierePedido = pedidos.length > 1;
  const { listar, loading: loadingCartera } = useCheques();
  const { fetchElegibles, loading: loadingAplicables } = useChequesAplicables();

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

  // ── Cheques propios elegibles para "aplicar" (S4) ──
  const [showSelectorAplicar, setShowSelectorAplicar] = useState(false);
  const [elegibles, setElegibles] = useState([]);

  const fetchAplicables = useCallback(async () => {
    const items = await fetchElegibles(proveedorId);
    setElegibles(items);
  }, [fetchElegibles, proveedorId]);

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

  // Aplicar un cheque propio pre-existente (S4): mismo shape que el endoso
  // ({cheque_id, monto, moneda}) — el backend ya sabe distinguir tipo=propio
  // vs tercero al pagar (ADR-3 paso 5). NO llama al backend acá: viaja como
  // parte de `cheques` en crear_y_pagar/pagar, igual que un endoso.
  const handleAplicarPropio = useCallback(
    (cheque) => {
      if (chequesEmitidos.some((c) => c.cheque_id === cheque.id)) return;
      const payload = {
        cheque_id: cheque.id,
        monto: cheque.monto,
        moneda: cheque.moneda,
        _display_numero: cheque.numero,
        _display_banco: cheque.banco_nombre,
        _display_fecha_pago: cheque.fecha_pago,
        _es_aplicado_propio: true,
      };
      const next = [...chequesEmitidos, payload];
      setChequesEmitidos(next);
      if (onChange) onChange(next);
      setShowSelectorAplicar(false);
    },
    [chequesEmitidos, onChange],
  );

  const handlePedidoDestino = useCallback(
    (idx, value) => {
      const next = chequesEmitidos.map((ch, i) =>
        i === idx ? { ...ch, pedido_id: value === '' ? null : Number(value) } : ch,
      );
      setChequesEmitidos(next);
      if (onChange) onChange(next);
    },
    [chequesEmitidos, onChange],
  );

  // Si el usuario saca de la OP un pedido ya elegido como destino, el cheque no
  // puede quedar apuntando a un id que la OP no tiene.
  const pedidoIdsDisponibles = pedidos.map((p) => String(p.id)).join(',');
  useEffect(() => {
    const validos = new Set(pedidoIdsDisponibles ? pedidoIdsDisponibles.split(',') : []);
    let cambio = false;
    const next = chequesEmitidos.map((ch) => {
      if (ch.pedido_id != null && !validos.has(String(ch.pedido_id))) {
        cambio = true;
        return { ...ch, pedido_id: null };
      }
      return ch;
    });
    // Fuera de un updater de setState a propósito: los updaters corren en fase
    // de render y deben ser puros. Notificar al padre desde adentro lo estaría
    // actualizando durante el render de este componente, y StrictMode lo
    // dispararía dos veces por la misma limpieza.
    if (!cambio) return;
    setChequesEmitidos(next);
    if (onChange) onChange(next);
  }, [pedidoIdsDisponibles, onChange, chequesEmitidos]);

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
                const esAplicado = ch._es_aplicado_propio === true;
                const esExistente = esEndoso || esAplicado;
                const numero = esExistente ? ch._display_numero : ch.numero;
                const banco = esExistente ? ch._display_banco : null;
                const fechaPago = esExistente ? ch._display_fecha_pago : ch.fecha_pago;
                const esDiferido = !esExistente && ch.fecha_pago > ch.fecha_emision;
                // Key estable: cheque_id (endoso/aplicado) o numero (emisión). Evita
                // que React reconcilie la fila equivocada al quitar por índice.
                const rowKey = esExistente ? `existente-${ch.cheque_id}` : `propio-${ch.numero}`;
                return (
                  <div key={rowKey} className={`${styles.chequeRow} ${esExistente ? styles.chequeRowEndoso : ''}`}>
                    <div className={styles.chequeInfo}>
                      {esEndoso && <span className={styles.tagEndoso}>Endoso</span>}
                      {esAplicado && <span className={styles.tagEndoso}>Cheque propio aplicado</span>}
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
                    {requierePedido && (
                      <div className={styles.chequeDestino}>
                        <select
                          className={styles.selectDestino}
                          value={ch.pedido_id != null ? String(ch.pedido_id) : ''}
                          onChange={(e) => handlePedidoDestino(idx, e.target.value)}
                          disabled={disabled}
                          aria-label={`Pedido destino para cheque ${numero}`}
                        >
                          <option value="">Elegir pedido...</option>
                          {pedidos.map((p) => (
                            <option key={p.id} value={String(p.id)}>
                              {p.numero ?? `#${p.id}`}
                            </option>
                          ))}
                        </select>
                        {ch.pedido_id == null && (
                          <span className={styles.destinoError}>
                            Elegí contra qué pedido se descuenta.
                          </span>
                        )}
                      </div>
                    )}
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
              <button
                type="button"
                className={styles.btnEmitir}
                onClick={() => {
                  fetchAplicables();
                  setShowSelectorAplicar(true);
                }}
              >
                <FileCheck2 size={13} />
                Aplicar cheque propio
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
        <SelectorListaModal
          title="Cheques en cartera"
          items={cartera}
          loading={loadingCarteraLocal || loadingCartera}
          emptyMessage="No hay cheques en cartera disponibles."
          getKey={(ch) => ch.id}
          ariaLabel={(ch) => `Endosar cheque ${ch.numero}`}
          isDisabled={(ch) => chequesEmitidos.some((c) => c.cheque_id === ch.id)}
          onSelect={handleEndosar}
          onClose={() => setShowSelectorCartera(false)}
          renderItem={(ch) => {
            const yaAgregado = chequesEmitidos.some((c) => c.cheque_id === ch.id);
            return (
              <>
                <div className={selectorStyles.selectorItemInfo}>
                  <span className={selectorStyles.selectorNumero}>Nº {ch.numero}</span>
                  <span className={selectorStyles.selectorBanco}>{ch.banco_nombre ?? '—'}</span>
                  <span className={selectorStyles.selectorLibrador}>
                    {ch.librador_nombre ?? ch.cuit_librador ?? '—'}
                  </span>
                </div>
                <div className={selectorStyles.selectorItemRight}>
                  <span className={selectorStyles.selectorMonto}>
                    {formatCurrency(ch.monto, ch.moneda)} {ch.moneda}
                  </span>
                  <span className={selectorStyles.selectorFecha}>
                    pago {formatDateShort(ch.fecha_pago)}
                  </span>
                  {yaAgregado && <span className={selectorStyles.selectorTagUsado}>Ya agregado</span>}
                </div>
              </>
            );
          }}
        />
      )}

      {/* Selector de cheques propios elegibles para aplicar (S4) */}
      {showSelectorAplicar && (
        <SelectorListaModal
          title="Cheques propios para aplicar"
          items={elegibles}
          loading={loadingAplicables}
          emptyMessage="No hay cheques propios elegibles para este proveedor."
          getKey={(ch) => ch.id}
          ariaLabel={(ch) => `Aplicar cheque propio ${ch.numero}`}
          isDisabled={(ch) => chequesEmitidos.some((c) => c.cheque_id === ch.id)}
          onSelect={handleAplicarPropio}
          onClose={() => setShowSelectorAplicar(false)}
          renderItem={(ch) => {
            const yaAgregado = chequesEmitidos.some((c) => c.cheque_id === ch.id);
            return (
              <>
                <div className={selectorStyles.selectorItemInfo}>
                  <span className={selectorStyles.selectorNumero}>Nº {ch.numero}</span>
                  <span className={selectorStyles.selectorBanco}>{ch.banco_nombre ?? '—'}</span>
                  <span className={selectorStyles.selectorLibrador}>{ch.estado}</span>
                </div>
                <div className={selectorStyles.selectorItemRight}>
                  <span className={selectorStyles.selectorMonto}>
                    {formatCurrency(ch.monto, ch.moneda)} {ch.moneda}
                  </span>
                  <span className={selectorStyles.selectorFecha}>
                    pago {formatDateShort(ch.fecha_pago)}
                  </span>
                  {yaAgregado && <span className={selectorStyles.selectorTagUsado}>Ya agregado</span>}
                </div>
              </>
            );
          }}
        />
      )}
    </div>
  );
}
