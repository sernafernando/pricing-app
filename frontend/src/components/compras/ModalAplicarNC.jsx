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

const formatDate = (isoStr) => {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    return d.toLocaleDateString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  } catch {
    return isoStr;
  }
};

/**
 * ModalAplicarNC — imputa (total o parcial) una NC local aprobada contra:
 *   - un pedido de compra del mismo proveedor (estado aprobado / pagado_parcial);
 *   - una factura del ERP vigente del mismo proveedor;
 *   - saldo general del proveedor (crédito a cuenta).
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
  const [facturaId, setFacturaId] = useState('');
  const [monto, setMonto] = useState(String(saldoNC));
  const [pedidos, setPedidos] = useState([]);
  const [facturas, setFacturas] = useState([]);
  const [loadingPedidos, setLoadingPedidos] = useState(false);
  const [loadingFacturas, setLoadingFacturas] = useState(false);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const pedidoSeleccionado = useMemo(
    () => pedidos.find((p) => String(p.id) === String(pedidoId)) || null,
    [pedidos, pedidoId]
  );

  const facturaSeleccionada = useMemo(
    () =>
      facturas.find((f) => String(f.ct_transaction) === String(facturaId)) || null,
    [facturas, facturaId]
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

  const fetchFacturasERP = useCallback(async () => {
    if (!nc?.proveedor_id) return;
    setLoadingFacturas(true);
    setError(null);
    try {
      const { data } = await api.get(
        `/administracion/compras/cc-proveedor/${nc.proveedor_id}/facturas-erp-vigentes`,
        { params: { moneda: nc.moneda } }
      );
      setFacturas(data || []);
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        'Error al cargar facturas ERP del proveedor.';
      setError(msg);
      setFacturas([]);
    } finally {
      setLoadingFacturas(false);
    }
  }, [nc?.proveedor_id, nc?.moneda]);

  useEffect(() => {
    if (destinoTipo === 'pedido_compra') {
      fetchPedidos();
    } else if (destinoTipo === 'factura_erp') {
      fetchFacturasERP();
    }
  }, [destinoTipo, fetchPedidos, fetchFacturasERP]);

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

  // Al elegir factura ERP, sugerir el mínimo entre el saldo NC y el total de
  // factura (ct_total). El backend no expone "saldo pendiente de factura ERP"
  // v1 — usamos ct_total como cota. La validación final corre server-side.
  useEffect(() => {
    if (facturaSeleccionada) {
      const totalFactura = Number(facturaSeleccionada.ct_total) || 0;
      const sugerido = Math.min(saldoNC, totalFactura);
      if (sugerido > 0) {
        setMonto(sugerido.toFixed(2));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [facturaId]);

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
    if (destinoTipo === 'factura_erp' && !facturaId) {
      return 'Seleccioná una factura ERP destino.';
    }
    return null;
  };

  const destinoIdPayload = () => {
    if (destinoTipo === 'saldo') return null;
    if (destinoTipo === 'factura_erp') return Number(facturaId);
    return Number(pedidoId);
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
        destino_id: destinoIdPayload(),
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
                onChange={(e) => {
                  setDestinoTipo(e.target.value);
                  setFacturaId('');
                }}
              />
              <span>Pedido de compra del proveedor</span>
            </label>
            <label className={styles.radioRow}>
              <input
                type="radio"
                name="destino_tipo"
                value="factura_erp"
                checked={destinoTipo === 'factura_erp'}
                onChange={(e) => {
                  setDestinoTipo(e.target.value);
                  setPedidoId('');
                }}
              />
              <span>Factura del ERP del proveedor</span>
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
                  setFacturaId('');
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

        {destinoTipo === 'factura_erp' && (
          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Factura ERP destino *</label>
            {loadingFacturas ? (
              <div className={styles.centered}>
                <Loader2 size={14} className={styles.spin} /> Cargando facturas ERP...
              </div>
            ) : facturas.length === 0 ? (
              <div className={styles.empty}>
                No hay facturas del ERP vigentes para este proveedor
                {nc?.moneda ? ` en moneda ${nc.moneda}` : ''}. Si el
                proveedor no tiene supp_id mapeado, este listado queda
                vacío.
              </div>
            ) : (
              <select
                className={styles.select}
                value={facturaId}
                onChange={(e) => setFacturaId(e.target.value)}
              >
                <option value="">Seleccionar...</option>
                {facturas.map((f) => (
                  <option key={f.ct_transaction} value={f.ct_transaction}>
                    {f.ct_docnumber} — {formatDate(f.ct_date)} —{' '}
                    {formatCurrency(f.ct_total, nc?.moneda)}
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
            {facturaSeleccionada &&
              ` Total factura: ${formatCurrency(
                facturaSeleccionada.ct_total,
                nc?.moneda
              )}. La validación de saldo contable corre server-side.`}
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
