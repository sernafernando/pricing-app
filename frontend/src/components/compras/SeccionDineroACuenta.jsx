/**
 * SeccionDineroACuenta — lista read-only de filas de dinero a cuenta del proveedor.
 *
 * Muestra el real-money overpay disponible: monto original, saldo consumible,
 * moneda, estado y OP de origen. Gated por permiso ver_cuentas_corrientes.
 *
 * PR2 — T2.11. Solo lectura. Los consumos se implementan en PR4.
 *
 * References: design §4.2, tasks T2.11, spec FR-2.1..FR-2.4.
 */

import { useCallback, useEffect, useState } from 'react';
import { Banknote, Info } from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import api from '../../services/api';
import styles from './SeccionDineroACuenta.module.css';

function formatARS(value) {
  if (value == null) return '—';
  return new Intl.NumberFormat('es-AR', {
    style: 'currency',
    currency: 'ARS',
    minimumFractionDigits: 2,
  }).format(Number(value));
}

function formatUSD(value) {
  if (value == null) return '—';
  return new Intl.NumberFormat('es-AR', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
  }).format(Number(value));
}

function formatMonto(value, moneda) {
  if (moneda === 'USD') return formatUSD(value);
  return formatARS(value);
}

const ESTADO_LABEL = {
  disponible: 'Disponible',
  consumido_parcial: 'Parcial',
  consumido: 'Consumido',
};

const ESTADO_TONE = {
  disponible: styles.estadoDisponible,
  consumido_parcial: styles.estadoParcial,
  consumido: styles.estadoConsumido,
};

/**
 * @param {{ proveedorId: number }} props
 */
export default function SeccionDineroACuenta({ proveedorId }) {
  const { tienePermiso } = usePermisos();
  const canVer = tienePermiso('administracion.ver_cuentas_corrientes');

  const [filas, setFilas] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchDineroACuenta = useCallback(async () => {
    if (!proveedorId || !canVer) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get(
        `/administracion/compras/proveedores/${proveedorId}/dinero-a-cuenta`,
        { params: { estado: 'disponible' } }
      );
      setFilas(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('SeccionDineroACuenta: fetch failed', err);
      setError('No se pudo cargar el dinero a cuenta.');
      setFilas([]);
    } finally {
      setLoading(false);
    }
  }, [proveedorId, canVer]);

  useEffect(() => {
    fetchDineroACuenta();
  }, [fetchDineroACuenta]);

  if (!canVer) return null;
  if (loading) return null;
  if (error) return null; // non-blocking: CC still works
  if (filas.length === 0) return null;

  return (
    <section className={styles.seccion} aria-label="Dinero a cuenta disponible">
      <header className={styles.header}>
        <Banknote size={14} className={styles.headerIcon} aria-hidden="true" />
        <span className={styles.headerTitle}>Dinero a cuenta disponible</span>
        <span className={styles.headerCount}>{filas.length}</span>
        <span className={styles.headerHint} title="Saldo real-money disponible como medio de pago">
          <Info size={12} aria-hidden="true" />
        </span>
      </header>

      <table className={styles.table} role="table" aria-label="Filas de dinero a cuenta">
        <thead>
          <tr>
            <th className={styles.th}>OP origen</th>
            <th className={styles.th}>Moneda</th>
            <th className={styles.thRight}>Monto original</th>
            <th className={styles.thRight}>Saldo disponible</th>
            <th className={styles.th}>Estado</th>
          </tr>
        </thead>
        <tbody>
          {filas.map((fila) => (
            <tr key={fila.id} className={styles.row}>
              <td className={styles.td}>
                {fila.origen_op_numero || `#${fila.origen_op_id}`}
              </td>
              <td className={styles.td}>{fila.moneda}</td>
              <td className={`${styles.td} ${styles.right}`}>
                {formatMonto(fila.monto, fila.moneda)}
              </td>
              <td className={`${styles.td} ${styles.right} ${styles.saldoDisponible}`}>
                {formatMonto(fila.saldo_disponible, fila.moneda)}
              </td>
              <td className={styles.td}>
                <span className={`${styles.estadoBadge} ${ESTADO_TONE[fila.estado] || ''}`}>
                  {ESTADO_LABEL[fila.estado] || fila.estado}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
