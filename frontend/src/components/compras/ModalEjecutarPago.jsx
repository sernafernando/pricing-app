import { useCallback, useEffect, useState } from 'react';
import { X, Wallet, AlertTriangle, Landmark, Copy, Check } from 'lucide-react';
import { Link } from 'react-router-dom';
import api from '../../services/api';
import useComprasOP from '../../hooks/useComprasOP';
import styles from './ModalEjecutarPago.module.css';

/**
 * ModalEjecutarPago — selecciona caja + fecha y dispara POST /pagar.
 *
 * Filtra las cajas por `moneda === op.moneda` para evitar 422
 * OP_CAJA_MONEDA_MISMATCH (design §3.2). Si aun así el backend devuelve
 * 422 (por empresa_id mismatch o edge case), mostramos el mensaje inline.
 */
export default function ModalEjecutarPago({ op, onClose }) {
  const opApi = useComprasOP();

  const today = () => new Date().toISOString().split('T')[0];

  const [cajas, setCajas] = useState([]);
  const [cajaId, setCajaId] = useState('');
  const [fechaPagoReal, setFechaPagoReal] = useState(today());
  const [loadingCajas, setLoadingCajas] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  // TC al momento del pago (sub-batch 2.2). Arranca con el TC de la OP si
  // existe; el usuario puede sobrescribirlo. Solo es editable si la OP es USD.
  const [tipoCambioOverride, setTipoCambioOverride] = useState(
    op?.tipo_cambio ? String(op.tipo_cambio) : ''
  );

  // Datos bancarios del proveedor (Batch G — tesorería los copia al homebanking).
  const [bancos, setBancos] = useState([]);
  const [loadingBancos, setLoadingBancos] = useState(false);
  const [copiado, setCopiado] = useState(null); // { id, campo } del último copiado

  const fetchCajas = useCallback(async () => {
    setLoadingCajas(true);
    try {
      const { data } = await api.get('/administracion-caja/cajas');
      setCajas(data || []);
    } catch {
      setCajas([]);
    } finally {
      setLoadingCajas(false);
    }
  }, []);

  const fetchBancosProveedor = useCallback(async () => {
    if (!op?.proveedor_id) return;
    setLoadingBancos(true);
    try {
      const { data } = await api.get(
        `/administracion/proveedores/${op.proveedor_id}/bancos`
      );
      setBancos(Array.isArray(data) ? data : []);
    } catch {
      setBancos([]);
    } finally {
      setLoadingBancos(false);
    }
  }, [op?.proveedor_id]);

  useEffect(() => {
    fetchCajas();
  }, [fetchCajas]);

  useEffect(() => {
    fetchBancosProveedor();
  }, [fetchBancosProveedor]);

  const copyToClipboard = async (text, bancoId, campo) => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopiado({ id: bancoId, campo });
      setTimeout(() => {
        setCopiado((c) => (c && c.id === bancoId && c.campo === campo ? null : c));
      }, 1500);
    } catch {
      // Fallback silencioso: clipboard bloqueado o permiso denegado.
    }
  };

  // Cajas válidas: misma moneda que la OP, o cross-moneda (si el usuario
  // proveerá TC override). Filtramos por empresa.
  const cajasFiltradas = cajas.filter((c) => {
    if (c.empresa_id && op.empresa_id && c.empresa_id !== op.empresa_id) return false;
    return true;
  });

  const cajaSeleccionada = cajasFiltradas.find((c) => String(c.id) === String(cajaId));
  const esCrossMoneda =
    cajaSeleccionada && cajaSeleccionada.moneda && cajaSeleccionada.moneda !== op.moneda;
  const requiereTC = op.moneda === 'USD' || esCrossMoneda;
  const tcNum = parseFloat(tipoCambioOverride);
  const tcValido = Number.isFinite(tcNum) && tcNum > 0;

  // Monto equivalente en moneda de la caja seleccionada (info display).
  const montoEnCaja = (() => {
    if (!cajaSeleccionada) return null;
    const monto = Number(op.monto_total) || 0;
    if (cajaSeleccionada.moneda === op.moneda) return { valor: monto, moneda: op.moneda };
    if (!tcValido) return null;
    if (op.moneda === 'USD' && cajaSeleccionada.moneda === 'ARS') {
      return { valor: monto * tcNum, moneda: 'ARS' };
    }
    if (op.moneda === 'ARS' && cajaSeleccionada.moneda === 'USD') {
      return { valor: monto / tcNum, moneda: 'USD' };
    }
    return null;
  })();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!cajaId) {
      setError('Seleccioná una caja.');
      return;
    }
    if (!fechaPagoReal) {
      setError('La fecha de pago es requerida.');
      return;
    }
    if (esCrossMoneda && !tcValido) {
      setError(
        `Caja en ${cajaSeleccionada.moneda} ≠ OP en ${op.moneda}. Ingresá un tipo de cambio > 0 para convertir.`
      );
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const tcToSend = requiereTC && tcValido ? tcNum : null;
      await opApi.pagar(op.id, Number(cajaId), fechaPagoReal, tcToSend);
      onClose(true);
    } catch (err) {
      const res = err.response;
      const detail = res?.data?.detail || '';
      const asText = typeof detail === 'string' ? detail : JSON.stringify(detail);
      if (
        res?.status === 422 &&
        asText.includes('OP_CAJA_MONEDA_MISMATCH')
      ) {
        setError(
          `La caja elegida tiene moneda distinta a la OP (${op.moneda}) y no se pudo aplicar TC. Verificá el tipo de cambio.`
        );
      } else {
        setError(asText || 'Error al ejecutar el pago.');
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>
            <Wallet size={18} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            Ejecutar pago — OP {op.numero}
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

        <div className={styles.infoBox}>
          <div>
            <span className={styles.infoLabel}>Empresa:</span>{' '}
            {op.empresa_nombre || `#${op.empresa_id}`}
          </div>
          <div>
            <span className={styles.infoLabel}>Moneda:</span> {op.moneda}
          </div>
          <div>
            <span className={styles.infoLabel}>Monto total:</span>{' '}
            {Number(op.monto_total).toLocaleString('es-AR', {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </div>
        </div>

        {/* ── Panel de datos bancarios del proveedor (Batch G) ── */}
        <div className={styles.bancosPanel}>
          <div className={styles.bancosHeader}>
            <Landmark size={14} />
            <span>Datos bancarios del proveedor</span>
          </div>
          {loadingBancos ? (
            <div className={styles.bancosLoading}>Cargando...</div>
          ) : bancos.length === 0 ? (
            <div className={styles.bancosEmpty}>
              El proveedor no tiene bancos cargados.{' '}
              <Link
                to={`/administracion/proveedores?proveedor_id=${op.proveedor_id}`}
                className={styles.bancosLink}
              >
                Agregar desde ficha del proveedor →
              </Link>
            </div>
          ) : (
            <div className={styles.bancosList}>
              {bancos.map((b) => (
                <div key={b.id} className={styles.bancoCard}>
                  <div className={styles.bancoNombre}>
                    {b.banco}
                    {b.tipo_cuenta && (
                      <span className={styles.bancoTipo}> · {b.tipo_cuenta}</span>
                    )}
                  </div>
                  {b.alias && (
                    <div className={styles.bancoRow}>
                      <span className={styles.bancoLabel}>Alias:</span>
                      <code className={styles.bancoValor}>{b.alias}</code>
                      <button
                        type="button"
                        className={styles.btnCopiar}
                        onClick={() => copyToClipboard(b.alias, b.id, 'alias')}
                        aria-label="Copiar alias"
                        title="Copiar alias"
                      >
                        {copiado?.id === b.id && copiado?.campo === 'alias' ? (
                          <Check size={12} />
                        ) : (
                          <Copy size={12} />
                        )}
                      </button>
                    </div>
                  )}
                  {b.cbu && (
                    <div className={styles.bancoRow}>
                      <span className={styles.bancoLabel}>CBU:</span>
                      <code className={styles.bancoValor}>{b.cbu}</code>
                      <button
                        type="button"
                        className={styles.btnCopiar}
                        onClick={() => copyToClipboard(b.cbu, b.id, 'cbu')}
                        aria-label="Copiar CBU"
                        title="Copiar CBU"
                      >
                        {copiado?.id === b.id && copiado?.campo === 'cbu' ? (
                          <Check size={12} />
                        ) : (
                          <Copy size={12} />
                        )}
                      </button>
                    </div>
                  )}
                  {b.numero_cuenta && (
                    <div className={styles.bancoRow}>
                      <span className={styles.bancoLabel}>Cuenta:</span>
                      <code className={styles.bancoValor}>{b.numero_cuenta}</code>
                    </div>
                  )}
                  {b.sucursal && (
                    <div className={styles.bancoRow}>
                      <span className={styles.bancoLabel}>Sucursal:</span>
                      <span className={styles.bancoValorText}>{b.sucursal}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {error && <div className={styles.errorBanner}>{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Caja *</label>
            {loadingCajas ? (
              <div className={styles.loading}>Cargando cajas...</div>
            ) : cajasFiltradas.length === 0 ? (
              <div className={styles.warning}>
                <AlertTriangle size={14} /> No hay cajas disponibles para la empresa{' '}
                {op.empresa_nombre || `#${op.empresa_id}`} (id #{op.empresa_id}). Creá
                una caja antes de pagar.
              </div>
            ) : (
              <select
                className={styles.select}
                value={cajaId}
                onChange={(e) => setCajaId(e.target.value)}
                required
              >
                <option value="">Seleccionar...</option>
                {cajasFiltradas.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nombre} — {c.moneda} — saldo:{' '}
                    {Number(c.saldo_actual || 0).toLocaleString('es-AR', {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}
                    {c.moneda && c.moneda !== op.moneda ? ' — cross-moneda' : ''}
                  </option>
                ))}
              </select>
            )}
          </div>

          {requiereTC && (
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>
                Tipo de cambio{esCrossMoneda ? ' *' : ''}{' '}
                <span className={styles.labelHint}>(ARS por 1 USD)</span>
              </label>
              <input
                type="number"
                step="0.0001"
                min="0"
                className={styles.input}
                value={tipoCambioOverride}
                onChange={(e) => setTipoCambioOverride(e.target.value)}
                placeholder={op.tipo_cambio ? String(op.tipo_cambio) : '1150.50'}
              />
              <div className={styles.labelHint}>
                {op.tipo_cambio
                  ? `TC registrado en la OP: ${op.tipo_cambio}. Podés sobrescribirlo si cambió al momento de pagar.`
                  : 'Dejar vacío si no aplica conversión.'}
              </div>
              {esCrossMoneda && montoEnCaja && (
                <div className={styles.labelHint}>
                  Equivale a{' '}
                  {montoEnCaja.valor.toLocaleString('es-AR', {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}{' '}
                  {montoEnCaja.moneda} en la caja.
                </div>
              )}
            </div>
          )}

          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Fecha pago real *</label>
            <input
              type="date"
              className={styles.input}
              value={fechaPagoReal}
              onChange={(e) => setFechaPagoReal(e.target.value)}
              required
            />
          </div>

          <div className={styles.formActions}>
            <button
              type="button"
              className={styles.btnSecondary}
              onClick={() => onClose(false)}
              disabled={saving}
            >
              Cancelar
            </button>
            <button
              type="submit"
              className={styles.btnSuccess}
              disabled={saving || cajasFiltradas.length === 0}
            >
              {saving ? 'Procesando...' : 'Confirmar pago'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
