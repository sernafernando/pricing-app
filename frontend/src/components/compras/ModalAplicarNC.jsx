import { useCallback, useEffect, useMemo, useState } from 'react';
import { X, Loader2, AlertCircle, CreditCard } from 'lucide-react';
import api from '../../services/api';
import useNCsLocales from '../../hooks/useNCsLocales';
import styles from './ModalAplicarNC.module.css';

const formatCurrency = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
};

/**
 * ModalAplicarNC — imputa (total o parcial) una NC local aprobada contra:
 *   - un pedido de compra del mismo proveedor (estado aprobado / pagado_parcial);
 *   - saldo general del proveedor (crédito a cuenta).
 *
 * factura_erp NO está incluido en la UI v1 — es menos común en el flujo operativo
 * y se puede agregar con un selector específico cuando haya demanda real.
 *
 * Props:
 *   nc       — NC local aprobada o aplicada_parcial (debe tener `saldo_pendiente`).
 *   onClose  — (reload) => void; true → el detalle debe refrescarse.
 *
 * REGLA AGENTS.md: cierra solo con X o Cancelar.
 */
export default function ModalAplicarNC({ nc, onClose }) {
  const { aplicar } = useNCsLocales();

  const saldoNC = Number(nc?.saldo_pendiente ?? nc?.monto) || 0;

  const [destinoTipo, setDestinoTipo] = useState('pedido_compra');
  const [pedidoId, setPedidoId] = useState('');
  const [monto, setMonto] = useState(String(saldoNC));
  const [pedidos, setPedidos] = useState([]);
  const [loadingPedidos, setLoadingPedidos] = useState(false);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const pedidoSeleccionado = useMemo(
    () => pedidos.find((p) => String(p.id) === String(pedidoId)) || null,
    [pedidos, pedidoId]
  );

  const fetchPedidos = useCallback(async () => {
    if (!nc?.proveedor_id) return;
    setLoadingPedidos(true);
    setError(null);
    try {
      const { data } = await api.get('/administracion/compras/pedidos/pendientes-pago', {
        params: { proveedor_id: nc.proveedor_id, moneda: nc.moneda },
      });
      setPedidos(data || []);
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        'Error al cargar pedidos del proveedor.';
      setError(msg);
      setPedidos([]);
    } finally {
      setLoadingPedidos(false);
    }
  }, [nc?.proveedor_id, nc?.moneda]);

  useEffect(() => {
    if (destinoTipo === 'pedido_compra') {
      fetchPedidos();
    }
  }, [destinoTipo, fetchPedidos]);

  // Al elegir pedido, sugerir el mínimo entre el saldo de la NC y el saldo del pedido.
  useEffect(() => {
    if (pedidoSeleccionado) {
      const saldoPedido = Number(pedidoSeleccionado.saldo_pendiente) || 0;
      const sugerido = Math.min(saldoNC, saldoPedido);
      if (sugerido > 0) {
        setMonto(sugerido.toFixed(2));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pedidoId]);

  const validar = () => {
    const m = parseFloat(monto);
    if (!Number.isFinite(m) || m <= 0) return 'El monto debe ser mayor a 0.';
    if (m > saldoNC + 0.001) {
      return `El monto excede el saldo pendiente de la NC (${formatCurrency(
        saldoNC,
        nc?.moneda
      )}).`;
    }
    if (destinoTipo === 'pedido_compra') {
      if (!pedidoId) return 'Seleccioná un pedido destino.';
      if (pedidoSeleccionado) {
        const saldoPedido = Number(pedidoSeleccionado.saldo_pendiente) || 0;
        if (m > saldoPedido + 0.001) {
          return `El monto excede el saldo pendiente del pedido (${formatCurrency(
            saldoPedido,
            nc?.moneda
          )}).`;
        }
      }
    }
    return null;
  };

  const handleSubmit = async () => {
    const v = validar();
    if (v) {
      setError(v);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const body = {
        destino_tipo: destinoTipo,
        destino_id: destinoTipo === 'saldo' ? null : Number(pedidoId),
        monto_imputado: parseFloat(monto),
      };
      await aplicar(nc.id, body);
      onClose(true);
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        'Error al aplicar la NC.';
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>
            <CreditCard size={18} /> Aplicar NC {nc?.numero}
          </span>
          <button
            className={styles.modalCloseBtn}
            onClick={() => onClose(false)}
            aria-label="Cerrar"
            type="button"
          >
            <X size={18} />
          </button>
        </div>

        <div className={styles.saldoBox}>
          <span className={styles.saldoLabel}>Saldo disponible de la NC</span>
          <strong className={styles.saldoValue}>
            {formatCurrency(saldoNC, nc?.moneda)}
          </strong>
        </div>

        {error && (
          <div className={styles.errorBanner}>
            <AlertCircle size={14} /> {error}
          </div>
        )}

        <div className={styles.formGroup}>
          <label className={styles.formLabel}>Aplicar a *</label>
          <div className={styles.radioGroup}>
            <label className={styles.radioRow}>
              <input
                type="radio"
                name="destino_tipo"
                value="pedido_compra"
                checked={destinoTipo === 'pedido_compra'}
                onChange={(e) => setDestinoTipo(e.target.value)}
              />
              <span>Pedido de compra del proveedor</span>
            </label>
            <label className={styles.radioRow}>
              <input
                type="radio"
                name="destino_tipo"
                value="saldo"
                checked={destinoTipo === 'saldo'}
                onChange={(e) => {
                  setDestinoTipo(e.target.value);
                  setPedidoId('');
                }}
              />
              <span>Saldo general del proveedor (a cuenta)</span>
            </label>
          </div>
        </div>

        {destinoTipo === 'pedido_compra' && (
          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Pedido destino *</label>
            {loadingPedidos ? (
              <div className={styles.centered}>
                <Loader2 size={14} className={styles.spin} /> Cargando pedidos...
              </div>
            ) : pedidos.length === 0 ? (
              <div className={styles.empty}>
                No hay pedidos pendientes del proveedor en moneda {nc?.moneda}.
              </div>
            ) : (
              <select
                className={styles.select}
                value={pedidoId}
                onChange={(e) => setPedidoId(e.target.value)}
              >
                <option value="">Seleccionar...</option>
                {pedidos.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.numero} — {p.estado} — saldo{' '}
                    {formatCurrency(p.saldo_pendiente, p.moneda)}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}

        <div className={styles.formGroup}>
          <label className={styles.formLabel}>
            Monto a imputar * <span className={styles.labelHint}>({nc?.moneda})</span>
          </label>
          <input
            type="number"
            step="0.01"
            min="0.01"
            className={styles.input}
            value={monto}
            onChange={(e) => setMonto(e.target.value)}
            placeholder="0.00"
            required
          />
          <div className={styles.labelHint}>
            Máximo: {formatCurrency(saldoNC, nc?.moneda)} (saldo de la NC)
            {pedidoSeleccionado &&
              `, y ${formatCurrency(
                pedidoSeleccionado.saldo_pendiente,
                pedidoSeleccionado.moneda
              )} (saldo del pedido).`}
          </div>
        </div>

        <div className={styles.formActions}>
          <button
            type="button"
            className={styles.btnSecondary}
            onClick={() => onClose(false)}
            disabled={submitting}
          >
            Cancelar
          </button>
          <button
            type="button"
            className={styles.btnPrimary}
            onClick={handleSubmit}
            disabled={submitting}
          >
            {submitting ? (
              <>
                <Loader2 size={14} className={styles.spin} /> Aplicando...
              </>
            ) : (
              'Aplicar crédito'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
