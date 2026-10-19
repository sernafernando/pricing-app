import { useEffect, useId, useRef, useState } from 'react';
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

// `PEDIDOS_MAX` in `backend/app/schemas/sell_in.py`.
const PEDIDOS_MAX = 50;

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
 *
 * It may come from several Compras operations: each change of that set asks
 * `GET /prefill` and fills what is empty or still holds an untouched prefill
 * (supplier, receipt date, products); removing every operation clears what
 * they filled. Typed products are replaced only after an inline confirmation,
 * and the operations' currency is only offered, since a sell in keeps its own.
 */
export default function SellInCreatePanel({ onCreated, onClose }) {
  const id = useId();
  const [datos, setDatos] = useState({ fechaCompra: toLocalDateString(), fechaIngreso: '', cuentaDesde: 'compra', descripcion: '' });
  const [proveedor, setProveedor] = useState(null);
  const [reparto, setReparto] = useState({ moneda: 'USD', montoTotal: '', tipoCambio: '', formula: 'proporcional' });
  const [lineas, setLineas] = useState([]);
  const [pedidos, setPedidos] = useState([]);
  const [pedidoTexto, setPedidoTexto] = useState('');
  // What the last prefill answered: its currency (offered) and products waiting for the user's go-ahead.
  const [monedaOperaciones, setMonedaOperaciones] = useState(null);
  const [lineasPendientes, setLineasPendientes] = useState(null);
  const [prefillError, setPrefillError] = useState(null);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  // Bumped on every change the split depends on: a preview answer carries the
  // version it was asked for, and one that arrives after an edit is dropped.
  const versionRef = useRef(0);
  // Only the answer for the latest set of operations is applied.
  const prefillRef = useRef(0);
  // What is on screen as last rendered: a prefill answer decides on it, not on its request's closure.
  const actualRef = useRef({ proveedor, fechaIngreso: datos.fechaIngreso, lineas });
  useEffect(() => {
    actualRef.current = { proveedor, fechaIngreso: datos.fechaIngreso, lineas };
  }, [proveedor, datos.fechaIngreso, lineas]);
  // Which fields hold what a prefill put there, untouched since: the next prefill (or none) may replace
  // them. Once the user edits one it is theirs and is never overwritten silently.
  const prefilladoRef = useRef({ proveedor: false, fechaIngreso: false, lineas: false });
  const marcarPropio = (campo) => {
    prefilladoRef.current[campo] = false;
  };

  const setDato = (patch) => setDatos((prev) => ({ ...prev, ...patch }));
  const invalidar = () => {
    versionRef.current += 1;
    setPreview(null);
    setError(null);
  };
  const setRepartoCampo = (patch) => {
    setReparto((prev) => ({ ...prev, ...patch }));
    invalidar();
  };
  const elegirProveedor = (valor) => {
    marcarPropio('proveedor');
    setProveedor(valor);
  };
  const setLinea = (itemId, patch) => {
    marcarPropio('lineas');
    setLineas((prev) => prev.map((l) => (l.item_id === itemId ? { ...l, ...patch } : l)));
    invalidar();
  };
  const agregarProducto = ({ producto }) => {
    marcarPropio('lineas');
    setLineas((prev) =>
      prev.some((l) => l.item_id === producto.item_id)
        ? prev
        : [...prev, { item_id: producto.item_id, codigo: producto.codigo, descripcion: producto.descripcion, cantidad: '1', montoManual: '' }],
    );
    invalidar();
  };
  const quitarLinea = (itemId) => {
    marcarPropio('lineas');
    setLineas((prev) => prev.filter((l) => l.item_id !== itemId));
    invalidar();
  };

  const pedirPrefill = async (ids) => {
    const token = ++prefillRef.current;
    setPrefillError(null);
    setLineasPendientes(null);
    setMonedaOperaciones(null);
    if (ids.length === 0) {
      aplicarPrefill({ proveedor: null, fechaIngreso: '', lineas: [] });
      return;
    }
    try {
      const { data } = await sellInAPI.prefill(ids);
      if (token !== prefillRef.current) return;
      setMonedaOperaciones(data.moneda);
      aplicarPrefill({
        proveedor: { id: data.proveedor_id, nombre: data.proveedor_nombre ?? `Proveedor #${data.proveedor_id}` },
        fechaIngreso: data.fecha_ingreso ?? '',
        lineas: data.items.map((item) => ({
          item_id: item.item_id,
          codigo: item.codigo ?? '',
          descripcion: item.descripcion ?? '',
          cantidad: String(item.cantidad),
          montoManual: '',
        })),
      });
    } catch (err) {
      if (token === prefillRef.current) setPrefillError(apiMessage(err, 'No se pudieron leer las operaciones.'));
    }
  };
  /**
   * Puts what the operations say (empty values when there are none left) into every field that is
   * empty or still holds an untouched prefill. Lines the user edited are only offered for replacing.
   */
  const aplicarPrefill = (valores) => {
    const actual = actualRef.current;
    const prefillado = prefilladoRef.current;
    if (!actual.proveedor || prefillado.proveedor) {
      setProveedor(valores.proveedor);
      prefillado.proveedor = valores.proveedor !== null;
    }
    if (!actual.fechaIngreso || prefillado.fechaIngreso) {
      setDato({ fechaIngreso: valores.fechaIngreso });
      prefillado.fechaIngreso = valores.fechaIngreso !== '';
    }
    if (actual.lineas.length === 0 || prefillado.lineas) {
      if (actual.lineas.length > 0 || valores.lineas.length > 0) {
        setLineas(valores.lineas);
        invalidar();
      }
      prefillado.lineas = valores.lineas.length > 0;
    } else if (valores.lineas.length > 0) {
      setLineasPendientes(valores.lineas);
    }
  };
  const cambiarPedidos = (ids) => {
    setPedidos(ids);
    pedirPrefill(ids);
  };
  const agregarPedido = () => {
    const numero = Number(pedidoTexto);
    setPedidoTexto('');
    if (!Number.isInteger(numero) || numero < 1 || pedidos.includes(numero) || pedidos.length >= PEDIDOS_MAX) return;
    cambiarPedidos([...pedidos, numero]);
  };
  const reemplazarLineas = () => {
    setLineas(lineasPendientes);
    setLineasPendientes(null);
    prefilladoRef.current.lineas = true;
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
    // The backend refuses it too (`compras.py`: "Una compra en USD necesita el tipo de cambio").
    if (moneda === 'USD' && !(Number(tipoCambio) > 0)) {
      setError('Una compra en USD necesita el tipo de cambio.');
      return;
    }
    const suma = sumaManual(lineas.map((l) => l.montoManual));
    if (manual && suma !== sumaManual([montoTotal])) {
      setError(`Los montos manuales suman ${formatMonto(suma, moneda)} y el total es ${formatMonto(montoTotal || 0, moneda)}.`);
      return;
    }
    const version = versionRef.current;
    const pedido = body;
    setBusy(true);
    setError(null);
    try {
      const { data } = await sellInAPI.preview(pedido);
      // Saved with the exact body that was previewed, never the inputs as they are by then.
      if (version === versionRef.current) setPreview({ data, body: pedido });
    } catch (err) {
      if (version === versionRef.current) setError(apiMessage(err, 'No se pudo calcular la vista previa.'));
    } finally {
      setBusy(false);
    }
  };

  const guardar = async () => {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      const { data } = await sellInAPI.crear({
        ...preview.body,
        fecha_compra: datos.fechaCompra,
        fecha_ingreso: datos.fechaIngreso || null,
        cuenta_desde: datos.cuentaDesde,
        proveedor_id: proveedor?.id ?? null,
        pedido_compra_ids: pedidos,
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
              <input id={`${id}-fi`} type="date" className={styles.input} value={datos.fechaIngreso} onChange={(e) => {
                  marcarPropio('fechaIngreso');
                  setDato({ fechaIngreso: e.target.value });
                }} />
            </label>
            <label className={styles.field} htmlFor={`${id}-cd`}>
              <span className={styles.label}>Cuenta desde</span>
              <select id={`${id}-cd`} className={styles.select} value={datos.cuentaDesde} onChange={(e) => setDato({ cuentaDesde: e.target.value })}>
                <option value="compra">Fecha de compra</option>
                <option value="ingreso">Fecha de ingreso</option>
              </select>
            </label>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={`${id}-pc`}>
                Pedido de compra (N°)
              </label>
              <div className={styles.inline}>
                <input
                  id={`${id}-pc`}
                  type="number"
                  min="1"
                  className={styles.input}
                  value={pedidoTexto}
                  onChange={(e) => setPedidoTexto(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      agregarPedido();
                    }
                  }}
                />
                <button type="button" className="btn-tesla outline sm" onClick={agregarPedido} disabled={!pedidoTexto || pedidos.length >= PEDIDOS_MAX}>
                  Agregar operación
                </button>
              </div>
            </div>
          </div>
          {pedidos.length > 0 && (
            <ul className={styles.chips} aria-label="Operaciones de compra">
              {pedidos.map((numero) => (
                <li key={numero} className={styles.chip}>
                  <span>N° {numero}</span>
                  <button
                    type="button"
                    className={styles.close}
                    aria-label={`Quitar operación ${numero}`}
                    onClick={() => cambiarPedidos(pedidos.filter((n) => n !== numero))}
                  >
                    <X size={12} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {prefillError && (
            <p className={styles.error} role="alert">
              {prefillError}
            </p>
          )}
          <label className={styles.field} htmlFor={`${id}-ds`}>
            <span className={styles.label}>Descripción</span>
            <input id={`${id}-ds`} type="text" className={styles.input} value={datos.descripcion} onChange={(e) => setDato({ descripcion: e.target.value })} />
          </label>
          {proveedor ? (
            <div className={styles.chosen}>
              <span className={styles.label}>Proveedor</span>
              <span>{proveedor.nombre}</span>
              <button type="button" className={styles.close} aria-label="Quitar proveedor" onClick={() => elegirProveedor(null)}>
                <X size={14} />
              </button>
            </div>
          ) : (
            <SellInBuscador
              label="Proveedor"
              placeholder="Buscar proveedor (opcional)…"
              buscar={buscarProveedores}
              onPick={(opcion) => elegirProveedor(opcion.proveedor)}
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
              {monedaOperaciones && monedaOperaciones !== moneda && (
                <p className={styles.hint}>
                  Las operaciones están en {monedaOperaciones}.{' '}
                  <button type="button" className={styles.linkButton} onClick={() => setRepartoCampo({ moneda: monedaOperaciones })}>
                    Usar {monedaOperaciones}
                  </button>
                </p>
              )}
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
          {lineasPendientes && (
            <div className={styles.confirm}>
              <p className={styles.hint}>Ya hay productos cargados. ¿Reemplazarlos por los de las operaciones?</p>
              <div className={styles.confirmActions}>
                <button type="button" className="btn-tesla outline sm" onClick={() => setLineasPendientes(null)}>
                  Mantener los actuales
                </button>
                <button type="button" className="btn-tesla primary sm" onClick={reemplazarLineas}>
                  Reemplazar productos
                </button>
              </div>
            </div>
          )}
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
          {preview && <SellInPreview preview={preview.data} />}
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
