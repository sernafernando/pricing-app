import { useId, useState } from 'react';
import { X } from 'lucide-react';
import { productosAPI } from '../../services/api';
import { sellInAPI } from '../../services/sellInAPI';
import { toLocalDateString } from '../../utils/dateUtils';
import { SegmentedControl } from '../kit';
import SellInBuscador from './SellInBuscador';
import SellInPreview from './SellInPreview';
import { apiMessage, formatMonto, sumaManual } from './sellInFormat';
import styles from './SellInPanel.module.css';

const MONEDAS = [
  { value: 'USD', label: 'USD' },
  { value: 'ARS', label: 'ARS' },
];
const FORMULAS = [
  { value: 'proporcional', label: 'Proporcional (por defecto)' },
  { value: 'por_unidad', label: 'Por unidad' },
  { value: 'manual', label: 'Manual' },
];

const buscarProductos = (search) =>
  productosAPI.listar({ search, page_size: 10 }).then(({ data }) =>
    (data?.productos ?? []).map((p) => ({ key: p.item_id, label: `${p.codigo} · ${p.descripcion}`, sub: p.marca, producto: p })),
  );

const buscarProveedores = (search) =>
  sellInAPI
    .proveedores(search)
    .then(({ data }) => (data?.proveedores ?? []).map((p) => ({ key: p.id, label: p.nombre, sub: p.cuit, proveedor: p })));

/**
 * Right panel to load a sell in for a purchase (Stitch `02`): amount,
 * currency and FX rate, the items and quantities, the split formula, a
 * server preview, and save. Any change to what the split depends on drops the
 * preview, so what gets saved is always what was last seen.
 */
export default function SellInCreatePanel({ onCreated, onClose }) {
  const id = useId();
  const [datos, setDatos] = useState({ fechaCompra: toLocalDateString(), fechaIngreso: '', cuentaDesde: 'compra', pedido: '', descripcion: '' });
  const [proveedor, setProveedor] = useState(null);
  const [reparto, setReparto] = useState({ moneda: 'USD', montoTotal: '', tipoCambio: '', formula: 'proporcional' });
  const [lineas, setLineas] = useState([]);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const setDato = (patch) => setDatos((prev) => ({ ...prev, ...patch }));
  const invalidar = () => {
    setPreview(null);
    setError(null);
  };
  const setRepartoCampo = (patch) => {
    setReparto((prev) => ({ ...prev, ...patch }));
    invalidar();
  };
  const setLinea = (itemId, patch) => {
    setLineas((prev) => prev.map((l) => (l.item_id === itemId ? { ...l, ...patch } : l)));
    invalidar();
  };
  const agregarProducto = ({ producto }) => {
    setLineas((prev) =>
      prev.some((l) => l.item_id === producto.item_id)
        ? prev
        : [...prev, { item_id: producto.item_id, codigo: producto.codigo, descripcion: producto.descripcion, cantidad: '1', montoManual: '' }],
    );
    invalidar();
  };
  const quitarLinea = (itemId) => {
    setLineas((prev) => prev.filter((l) => l.item_id !== itemId));
    invalidar();
  };

  const { moneda, montoTotal, tipoCambio, formula } = reparto;
  const manual = formula === 'manual';
  const body = {
    moneda,
    monto_total: montoTotal,
    tipo_cambio: tipoCambio || null,
    formula,
    lineas: lineas.map((l) => ({
      item_id: l.item_id,
      cantidad: Number.parseInt(l.cantidad, 10) || 0,
      ...(manual ? { monto_manual: l.montoManual || '0' } : {}),
    })),
  };

  const calcular = async () => {
    if (lineas.length === 0) {
      setError('Agregá al menos un producto.');
      return;
    }
    const suma = sumaManual(lineas.map((l) => l.montoManual));
    if (manual && suma !== sumaManual([montoTotal])) {
      setError(`Los montos manuales suman ${formatMonto(suma, moneda)} y el total es ${formatMonto(montoTotal || 0, moneda)}.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { data } = await sellInAPI.preview(body);
      setPreview(data);
    } catch (err) {
      setError(apiMessage(err, 'No se pudo calcular la vista previa.'));
    } finally {
      setBusy(false);
    }
  };

  const guardar = async () => {
    setBusy(true);
    setError(null);
    try {
      const { data } = await sellInAPI.crear({
        ...body,
        fecha_compra: datos.fechaCompra,
        fecha_ingreso: datos.fechaIngreso || null,
        cuenta_desde: datos.cuentaDesde,
        proveedor_id: proveedor?.id ?? null,
        pedido_compra_id: datos.pedido ? Number(datos.pedido) : null,
        descripcion: datos.descripcion.trim() || null,
      });
      onCreated(data);
    } catch (err) {
      setError(apiMessage(err, 'No se pudo guardar el sell in.'));
    } finally {
      setBusy(false);
    }
  };

  const equivale = moneda === 'USD' && Number(montoTotal) > 0 && Number(tipoCambio) > 0 ? Number(montoTotal) * Number(tipoCambio) : null;

  return (
    <div className={styles.panel}>
      <header className={styles.panelHeader}>
        <h2>Nuevo sell in · Por compra</h2>
        <button type="button" className={styles.close} aria-label="Cerrar" onClick={onClose}>
          <X size={18} />
        </button>
      </header>

      <div className={styles.panelBody}>
        <section className={styles.section}>
          <h3>Compra</h3>
          <div className={styles.grid2}>
            <label className={styles.field} htmlFor={`${id}-fc`}>
              <span className={styles.label}>Fecha de compra</span>
              <input id={`${id}-fc`} type="date" className={styles.input} value={datos.fechaCompra} onChange={(e) => setDato({ fechaCompra: e.target.value })} />
            </label>
            <label className={styles.field} htmlFor={`${id}-fi`}>
              <span className={styles.label}>Fecha de ingreso</span>
              <input id={`${id}-fi`} type="date" className={styles.input} value={datos.fechaIngreso} onChange={(e) => setDato({ fechaIngreso: e.target.value })} />
            </label>
            <label className={styles.field} htmlFor={`${id}-cd`}>
              <span className={styles.label}>Cuenta desde</span>
              <select id={`${id}-cd`} className={styles.select} value={datos.cuentaDesde} onChange={(e) => setDato({ cuentaDesde: e.target.value })}>
                <option value="compra">Fecha de compra</option>
                <option value="ingreso">Fecha de ingreso</option>
              </select>
            </label>
            <label className={styles.field} htmlFor={`${id}-pc`}>
              <span className={styles.label}>Pedido de compra (N°)</span>
              <input id={`${id}-pc`} type="number" min="1" className={styles.input} value={datos.pedido} onChange={(e) => setDato({ pedido: e.target.value })} />
            </label>
          </div>
          <label className={styles.field} htmlFor={`${id}-ds`}>
            <span className={styles.label}>Descripción</span>
            <input id={`${id}-ds`} type="text" className={styles.input} value={datos.descripcion} onChange={(e) => setDato({ descripcion: e.target.value })} />
          </label>
          {proveedor ? (
            <div className={styles.chosen}>
              <span className={styles.label}>Proveedor</span>
              <span>{proveedor.nombre}</span>
              <button type="button" className={styles.close} aria-label="Quitar proveedor" onClick={() => setProveedor(null)}>
                <X size={14} />
              </button>
            </div>
          ) : (
            <SellInBuscador
              label="Proveedor"
              placeholder="Buscar proveedor (opcional)…"
              buscar={buscarProveedores}
              onPick={(opcion) => setProveedor(opcion.proveedor)}
              errorMessage="No se pudieron buscar proveedores."
            />
          )}
        </section>

        <section className={styles.section}>
          <h3>Monto</h3>
          <div className={styles.grid2}>
            <label className={styles.field} htmlFor={`${id}-mt`}>
              <span className={styles.label}>Monto total</span>
              <input id={`${id}-mt`} type="number" min="0" step="0.01" className={styles.input} value={montoTotal} onChange={(e) => setRepartoCampo({ montoTotal: e.target.value })} />
            </label>
            <div className={styles.field}>
              <span className={styles.label}>Moneda</span>
              <SegmentedControl label="Moneda" options={MONEDAS} value={moneda} onChange={(value) => setRepartoCampo({ moneda: value })} />
            </div>
          </div>
          <label className={styles.field} htmlFor={`${id}-tc`}>
            <span className={styles.label}>Tipo de cambio</span>
            <input id={`${id}-tc`} type="number" min="0" step="0.01" className={styles.input} value={tipoCambio} onChange={(e) => setRepartoCampo({ tipoCambio: e.target.value })} />
          </label>
          <p className={styles.hint}>
            {equivale !== null ? (
              <>
                Equivale a <strong>{formatMonto(equivale, 'ARS')}</strong>
              </>
            ) : (
              'Obligatorio en USD; en ARS, solo si algún producto tiene el costo en dólares.'
            )}
          </p>
        </section>

        <section className={styles.section}>
          <h3>Productos</h3>
          <SellInBuscador label="Agregar producto" placeholder="Buscar por código o descripción…" buscar={buscarProductos} onPick={agregarProducto} errorMessage="No se pudieron buscar productos." />
          {lineas.map((l) => (
            <div key={l.item_id} className={styles.linea}>
              <span className={styles.lineaNombre}>
                <span className={styles.mono}>{l.codigo}</span> {l.descripcion}
              </span>
              <input type="number" min="1" className={styles.inputSm} aria-label={`Cantidad de ${l.codigo}`} value={l.cantidad} onChange={(e) => setLinea(l.item_id, { cantidad: e.target.value })} />
              {manual && (
                <input type="number" min="0" step="0.01" className={styles.inputSm} aria-label={`Monto manual de ${l.codigo}`} placeholder="Monto" value={l.montoManual} onChange={(e) => setLinea(l.item_id, { montoManual: e.target.value })} />
              )}
              <button type="button" className={styles.close} aria-label={`Quitar ${l.codigo}`} onClick={() => quitarLinea(l.item_id)}>
                <X size={14} />
              </button>
            </div>
          ))}
        </section>

        <section className={styles.section}>
          <h3>Reparto entre ítems</h3>
          <SegmentedControl label="Reparto" options={FORMULAS} value={formula} onChange={(value) => setRepartoCampo({ formula: value })} />
          <p className={styles.hint}>En manual, los montos deben sumar el total.</p>
        </section>

        <section className={styles.section}>
          <div className={styles.sectionHead}>
            <h3>Vista previa por ítem</h3>
            <button type="button" className="btn-tesla outline sm" onClick={calcular} disabled={busy}>
              Calcular vista previa
            </button>
          </div>
          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}
          {preview && <SellInPreview preview={preview} />}
        </section>
      </div>

      <footer className={styles.panelFooter}>
        <button type="button" className="btn-tesla outline sm" onClick={onClose}>
          Cancelar
        </button>
        <button type="button" className="btn-tesla primary sm" onClick={guardar} disabled={!preview || busy}>
          Guardar sell in
        </button>
      </footer>
    </div>
  );
}
