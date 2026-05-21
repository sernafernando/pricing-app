import { useCallback, useEffect, useState } from 'react';
import { X, Wallet, AlertTriangle, Landmark, Copy, Check } from 'lucide-react';
import { Link } from 'react-router-dom';
import api from '../../services/api';
import useComprasOP from '../../hooks/useComprasOP';
import styles from './ModalEjecutarPago.module.css';

/**
 * ModalEjecutarPago — selecciona fuente de fondos (caja O banco empresa) + fecha
 * y dispara POST /pagar.
 *
 * Las cajas se filtran por empresa. Los bancos empresa activos de la empresa
 * de la OP se agregan como grupo separado en el selector (AD-15). Si el backend
 * devuelve 422, mostramos el mensaje inline.
 */
export default function ModalEjecutarPago({ op, onClose }) {
  const opApi = useComprasOP();

  const today = () => new Date().toISOString().split('T')[0];

  const [cajas, setCajas] = useState([]);
  const [bancosEmpresa, setBancosEmpresa] = useState([]);
  // fuenteKey: '' | 'caja:<id>' | 'banco:<id>'
  const [fuenteKey, setFuenteKey] = useState('');
  const [fechaPagoReal, setFechaPagoReal] = useState(today());
  const [loadingCajas, setLoadingCajas] = useState(false);
  const [loadingBancosEmpresa, setLoadingBancosEmpresa] = useState(false);
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

  const fetchBancosEmpresa = useCallback(async () => {
    if (!op?.empresa_id) return;
    setLoadingBancosEmpresa(true);
    try {
      const { data } = await api.get(
        `/administracion/bancos?solo_activos=true&empresa_id=${op.empresa_id}`
      );
      setBancosEmpresa(Array.isArray(data?.items) ? data.items : Array.isArray(data) ? data : []);
    } catch {
      setBancosEmpresa([]);
    } finally {
      setLoadingBancosEmpresa(false);
    }
  }, [op?.empresa_id]);

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
    fetchBancosEmpresa();
  }, [fetchBancosEmpresa]);

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

  // Cajas válidas: filtradas por empresa.
  const cajasFiltradas = cajas.filter((c) => {
    if (c.empresa_id && op.empresa_id && c.empresa_id !== op.empresa_id) return false;
    return true;
  });

  // Parsed fuente seleccionada: { tipo: 'caja'|'banco', id, moneda }
  const fuenteSeleccionada = (() => {
    if (!fuenteKey) return null;
    const [tipo, idStr] = fuenteKey.split(':');
    const id = Number(idStr);
    if (tipo === 'caja') {
      const c = cajasFiltradas.find((c) => c.id === id);
      return c ? { tipo: 'caja', id, moneda: c.moneda, nombre: c.nombre } : null;
    }
    if (tipo === 'banco') {
      const b = bancosEmpresa.find((b) => b.id === id);
      return b ? { tipo: 'banco', id, moneda: b.moneda, nombre: b.banco } : null;
    }
    return null;
  })();

  const esCrossMoneda =
    fuenteSeleccionada?.tipo === 'caja' &&
    fuenteSeleccionada.moneda &&
    fuenteSeleccionada.moneda !== op.moneda;
  const requiereTC = op.moneda === 'USD' || esCrossMoneda;
  const tcNum = parseFloat(tipoCambioOverride);
  const tcValido = Number.isFinite(tcNum) && tcNum > 0;

  // Monto equivalente en moneda de la caja seleccionada (info display).
  const montoEnCaja = (() => {
    if (!fuenteSeleccionada || fuenteSeleccionada.tipo !== 'caja') return null;
    const monto = Number(op.monto_total) || 0;
    if (fuenteSeleccionada.moneda === op.moneda) return { valor: monto, moneda: op.moneda };
    if (!tcValido) return null;
    if (op.moneda === 'USD' && fuenteSeleccionada.moneda === 'ARS') {
      return { valor: monto * tcNum, moneda: 'ARS' };
    }
    if (op.moneda === 'ARS' && fuenteSeleccionada.moneda === 'USD') {
      return { valor: monto / tcNum, moneda: 'USD' };
    }
    return null;
  })();

  const hayFuentes = cajasFiltradas.length > 0 || bancosEmpresa.length > 0;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!fuenteKey) {
      setError('Seleccioná una fuente de fondos (caja o banco).');
      return;
    }
    if (!fechaPagoReal) {
      setError('La fecha de pago es requerida.');
      return;
    }
    if (esCrossMoneda && !tcValido) {
      setError(
        `Caja en ${fuenteSeleccionada.moneda} ≠ OP en ${op.moneda}. Ingresá un tipo de cambio > 0 para convertir.`
      );
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const tcToSend = requiereTC && tcValido ? tcNum : null;
      await opApi.pagar(op.id, fuenteSeleccionada, fechaPagoReal, tcToSend);
      onClose(true);
    } catch (err) {
      const res = err.response;
      const detail = res?.data?.detail || '';
      const asText = typeof detail === 'string' ? detail : JSON.stringify(detail);
      if (res?.status === 422 && asText.includes('OP_CAJA_MONEDA_MISMATCH')) {
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
            <label className={styles.formLabel}>Fuente de fondos *</label>
            {loadingCajas || loadingBancosEmpresa ? (
              <div className={styles.loading}>Cargando fuentes de fondos...</div>
            ) : !hayFuentes ? (
              <div className={styles.warning}>
                <AlertTriangle size={14} /> No hay cajas ni bancos disponibles para la empresa{' '}
                {op.empresa_nombre || `#${op.empresa_id}`}. Creá una caja o banco antes de pagar.
              </div>
            ) : (
              <select
                className={styles.select}
                value={fuenteKey}
                onChange={(e) => setFuenteKey(e.target.value)}
                required
              >
                <option value="">Seleccionar...</option>
                {cajasFiltradas.length > 0 && (
                  <optgroup label="Cajas">
                    {cajasFiltradas.map((c) => (
                      <option key={`caja:${c.id}`} value={`caja:${c.id}`}>
                        {c.nombre} — {c.moneda} — saldo:{' '}
                        {Number(c.saldo_actual || 0).toLocaleString('es-AR', {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}
                        {c.moneda && c.moneda !== op.moneda ? ' — cross-moneda' : ''}
                      </option>
                    ))}
                  </optgroup>
                )}
                {bancosEmpresa.length > 0 && (
                  <optgroup label="Cuentas bancarias">
                    {bancosEmpresa.map((b) => (
                      <option key={`banco:${b.id}`} value={`banco:${b.id}`}>
                        {b.banco} — {b.moneda} — saldo:{' '}
                        {Number(b.saldo_actual || 0).toLocaleString('es-AR', {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}
                      </option>
                    ))}
                  </optgroup>
                )}
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
              disabled={saving || !hayFuentes}
            >
              {saving ? 'Procesando...' : 'Confirmar pago'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
