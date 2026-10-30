import { useEffect, useId, useState } from 'react';
import { X } from 'lucide-react';
import { productosAPI } from '../../services/api';
import { SegmentedControl } from '../kit';
import SellInBonoModelos from './SellInBonoModelos';
import SellInBuscador from './SellInBuscador';
import SellInOperacionPicker from './SellInOperacionPicker';
import { BASE_COSTO, BASE_FACTURA, conBase, conMoneda, esBonoCosto } from './sellInBonoValores';
import styles from './SellInPanel.module.css';

const MONEDAS = [
  { value: 'USD', label: 'USD' },
  { value: 'ARS', label: 'ARS' },
];

const BASES = [
  { value: BASE_FACTURA, label: 'Sobre facturas' },
  { value: BASE_COSTO, label: 'Sobre el costo de la venta' },
];

const ALCANCES = [
  { value: 'marca', label: 'Marca' },
  { value: 'categoria', label: 'Categoría' },
  { value: 'modelos', label: 'Modelos' },
  { value: 'factura', label: 'Factura' },
];

// Same wording as the "Forma del monto" of a sell in per purchase (T3g).
const TIPOS = [
  { value: 'por_unidad', label: 'Monto por unidad' },
  { value: 'porcentaje', label: '% de lo facturado' },
];

const AYUDA = {
  marca: 'Se aplica sola a cada compra de la marca cuya fecha de factura del proveedor cae en el rango, al vincularse la factura.',
  categoria: 'Se aplica sola a cada compra con productos de la categoría cuya fecha de factura del proveedor cae en el rango, al vincularse la factura.',
  modelos:
    'Se aplica sola a cada compra con alguno de los modelos cuya fecha de factura del proveedor cae en el rango, al vincularse la factura; cada modelo usa su valor propio o, si no tiene, el del bono.',
  factura: 'Se aplica a todos los productos de esa operación cuando su fecha de factura del proveedor cae en el rango.',
};

// A cost bonus applies to the sales of its scope by sale date: there is no purchase or invoice to wait for.
const AYUDA_COSTO = {
  marca: 'Se aplica sola a cada venta de la marca cuya fecha de venta cae en el rango, sobre el costo de esa venta, sin vincular compras ni facturas.',
  categoria: 'Se aplica sola a cada venta de productos de la categoría cuya fecha de venta cae en el rango, sobre el costo de esa venta, sin vincular compras ni facturas.',
  modelos:
    'Se aplica sola a cada venta de alguno de los modelos cuya fecha de venta cae en el rango, sobre el costo de esa venta, sin vincular compras ni facturas; cada modelo usa su valor propio o, si no tiene, el del bono.',
};

const AYUDA_MONTO = {
  costo: 'Paga el porcentaje del costo sin IVA registrado en cada venta; una venta sin costo conocido queda pendiente.',
  porcentaje:
    'Paga el porcentaje de lo facturado de cada producto, neto de notas de crédito; si se facturó en la otra moneda, se convierte al tipo de cambio de la operación.',
  por_unidad: 'Cuenta las unidades facturadas, netas de notas de crédito.',
};

const buscarProductos = (search) =>
  productosAPI.listar({ search, page_size: 10 }).then(({ data }) =>
    (data?.productos ?? []).map((p) => ({ key: p.item_id, label: `${p.codigo} · ${p.descripcion}`, sub: p.marca, producto: p })),
  );

/** The catalog categories (`GET /categorias`), asked only once a category bonus is being edited; empty on failure. */
function useCategorias(enabled) {
  const [categorias, setCategorias] = useState([]);
  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    productosAPI
      .categorias()
      .then((response) => active && setCategorias(response.data?.categorias ?? []))
      .catch(() => active && setCategorias([]));
    return () => {
      active = false;
    };
  }, [enabled]);
  return categorias;
}

/** A select that keeps the stored value even when it is no longer in the list. */
function Opciones({ id, label, vacio, valor, opciones, disabled, onChange }) {
  const todas = valor && !opciones.includes(valor) ? [valor, ...opciones] : opciones;
  return (
    <label className={styles.field} htmlFor={id}>
      <span className={styles.label}>{label}</span>
      <select id={id} className={styles.select} value={valor} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        <option value="">{vacio}</option>
        {todas.map((opcion) => (
          <option key={opcion} value={opcion}>
            {opcion}
          </option>
        ))}
      </select>
    </label>
  );
}

/** "Sobre facturas" / "Sobre el costo de la venta": chosen on a new bonus, read-only afterwards (it never changes). */
function Base({ valores, editable, onChange }) {
  return (
    <div className={styles.field}>
      <span className={styles.label}>Base del bono</span>
      {editable ? (
        <SegmentedControl label="Base del bono" options={BASES} value={valores.base} onChange={(base) => onChange(conBase(valores, base))} />
      ) : (
        <span>{BASES.find((b) => b.value === valores.base)?.label}</span>
      )}
      {esBonoCosto(valores) && (
        <p className={styles.hint}>Para operaciones viejas que no tienen la factura cargada: baja el costo de las ventas sin vincular compras ni facturas.</p>
      )}
    </div>
  );
}

/**
 * The fields of a bonus (Stitch `03`, "Definición"): what it reaches (a brand from the brand filter's
 * list, a catalog category, some models from the product search, or one Compras operation), how it
 * pays (an amount per invoiced unit or a % of the invoiced net), the currency (USD by default) and the
 * supplier-invoice date range. A cost bonus (`base`; API T25d, this form T25e) is a % in ARS of each sale's cost by sale date, with no
 * invoice scope and an "Incluye IVA" flag. Controlled; `disabled` makes it read-only; `baseEditable` (a new bonus) lets
 * the base be chosen.
 */
export default function SellInBonoForm({ valores, onChange, marcas, disabled = false, baseEditable = true }) {
  const id = useId();
  const set = (patch) => onChange({ ...valores, ...patch });
  const categorias = useCategorias(valores.alcance === 'categoria' && !disabled);
  const porcentaje = valores.tipo === 'porcentaje';
  const costo = esBonoCosto(valores);
  // A cost bonus is always a % in ARS (the backend refuses the rest), so its kind and currency are fixed.
  const fijo = disabled || costo;
  const alcances = costo ? ALCANCES.filter((a) => a.value !== 'factura') : ALCANCES;
  const fechas = costo ? 'Venta' : 'Factura';

  const agregarModelo = ({ producto }) => {
    if (valores.modelos.some((m) => m.itemId === producto.item_id)) return;
    set({ modelos: [...valores.modelos, { itemId: producto.item_id, label: `${producto.codigo} · ${producto.descripcion}`, montoUnit: '', porcentaje: '' }] });
  };

  return (
    <>
      <Base valores={valores} editable={baseEditable && !disabled} onChange={onChange} />
      <div className={styles.field}>
        <span className={styles.label}>Alcance</span>
        {disabled ? (
          <span>{ALCANCES.find((a) => a.value === valores.alcance)?.label}</span>
        ) : (
          <SegmentedControl label="Alcance" options={alcances} value={valores.alcance} onChange={(alcance) => set({ alcance })} />
        )}
      </div>
      {valores.alcance === 'marca' && (
        <Opciones id={`${id}-marca`} label="Marca" vacio="Elegir marca…" valor={valores.marca} opciones={marcas} disabled={disabled} onChange={(marca) => set({ marca })} />
      )}
      {valores.alcance === 'categoria' && (
        <Opciones
          id={`${id}-categoria`}
          label="Categoría del bono"
          vacio="Elegir categoría…"
          valor={valores.categoria}
          opciones={categorias}
          disabled={disabled}
          onChange={(categoria) => set({ categoria })}
        />
      )}
      {valores.alcance === 'modelos' && (
        <div className={styles.field}>
          {!disabled && (
            <SellInBuscador label="Agregar modelo" placeholder="Buscar por código o descripción…" buscar={buscarProductos} onPick={agregarModelo} errorMessage="No se pudieron buscar productos." />
          )}
          <SellInBonoModelos valores={valores} disabled={disabled} onChange={(modelos) => set({ modelos })} />
        </div>
      )}
      {valores.alcance === 'factura' &&
        (valores.pedido ? (
          <ul className={styles.chips} aria-label="Operación del bono">
            <li className={styles.chip}>
              <span>N° {valores.pedido.numero}</span>
              {!disabled && (
                <button type="button" className={styles.close} aria-label={`Quitar operación ${valores.pedido.numero}`} onClick={() => set({ pedido: null })}>
                  <X size={12} />
                </button>
              )}
            </li>
          </ul>
        ) : (
          !disabled && <SellInOperacionPicker label="Pedido de compra (N°)" excluir={[]} onPick={(operacion) => set({ pedido: { id: operacion.id, numero: operacion.numero } })} />
        ))}
      <div className={styles.field}>
        <span className={styles.label}>Forma del monto</span>
        {fijo ? (
          <span>{costo ? '% del costo de la venta' : TIPOS.find((t) => t.value === valores.tipo)?.label}</span>
        ) : (
          <SegmentedControl label="Forma del monto" options={TIPOS} value={valores.tipo} onChange={(tipo) => set({ tipo })} />
        )}
      </div>
      <div className={styles.grid2}>
        {porcentaje ? (
          <label className={styles.field} htmlFor={`${id}-pct`}>
            <span className={styles.label}>Porcentaje</span>
            <input
              id={`${id}-pct`}
              type="number"
              min="0"
              max="100"
              step="0.0001"
              className={styles.input}
              value={valores.porcentaje}
              disabled={disabled}
              onChange={(e) => set({ porcentaje: e.target.value })}
            />
          </label>
        ) : (
          <label className={styles.field} htmlFor={`${id}-monto`}>
            <span className={styles.label}>Monto por unidad</span>
            <input
              id={`${id}-monto`}
              type="number"
              min="0"
              step="0.01"
              className={styles.input}
              value={valores.montoUnit}
              disabled={disabled}
              onChange={(e) => set({ montoUnit: e.target.value })}
            />
          </label>
        )}
        <div className={styles.field}>
          <span className={styles.label}>Moneda</span>
          {fijo ? (
            <span>{valores.moneda}</span>
          ) : (
            <SegmentedControl
              label="Moneda"
              options={MONEDAS}
              value={valores.moneda}
              // The money cap is in the bonus's currency (`conMoneda`): emptied away from it, restored back on it.
              onChange={(moneda) => onChange(conMoneda(valores, moneda))}
            />
          )}
        </div>
      </div>
      {costo && !disabled && <p className={styles.hint}>Un bono sobre el costo es siempre un porcentaje en pesos: el costo de cada venta está en pesos.</p>}
      {costo && (
        <div className={styles.field}>
          <label className={styles.check}>
            <input type="checkbox" checked={valores.incluyeIva} disabled={disabled} onChange={(e) => set({ incluyeIva: e.target.checked })} />
            Incluye IVA
          </label>
          <p className={styles.hint}>
            Tildado: el porcentaje cargado incluye IVA y se divide por el IVA de cada producto (3 % con IVA 10,5 % queda 2,71 %). Sin tildar: se usa tal
            cual.
          </p>
        </div>
      )}
      <div className={styles.field}>
        <label className={styles.check}>
          <input type="checkbox" checked={valores.acumulable} disabled={disabled} onChange={(e) => set({ acumulable: e.target.checked })} />
          Acumulable con otros bonos
        </label>
        {!valores.acumulable && (
          <p className={styles.hint}>
            No acumulable: no cobra sobre las unidades que ya cobró un bono anterior, y los bonos posteriores tampoco cobran sobre las suyas.
          </p>
        )}
      </div>
      <div className={styles.grid2}>
        <label className={styles.field} htmlFor={`${id}-desde`}>
          <span className={styles.label}>{`${fechas} desde`}</span>
          <input id={`${id}-desde`} type="date" className={styles.input} value={valores.fechaDesde} disabled={disabled} onChange={(e) => set({ fechaDesde: e.target.value })} />
        </label>
        <label className={styles.field} htmlFor={`${id}-hasta`}>
          <span className={styles.label}>{`${fechas} hasta`}</span>
          <input id={`${id}-hasta`} type="date" className={styles.input} value={valores.fechaHasta} disabled={disabled} onChange={(e) => set({ fechaHasta: e.target.value })} />
        </label>
      </div>
      <div className={styles.grid2}>
        <label className={styles.field} htmlFor={`${id}-tope-u`}>
          <span className={styles.label}>Tope de unidades (opcional)</span>
          <input
            id={`${id}-tope-u`}
            type="number"
            min="1"
            step="1"
            className={styles.input}
            value={valores.topeUnidades}
            disabled={disabled}
            onChange={(e) => set({ topeUnidades: e.target.value })}
          />
        </label>
        <label className={styles.field} htmlFor={`${id}-tope-m`}>
          <span className={styles.label}>{`Tope de monto en ${valores.moneda} (opcional)`}</span>
          <input
            id={`${id}-tope-m`}
            type="number"
            min="0.01"
            step="0.01"
            className={styles.input}
            value={valores.topeMonto}
            disabled={disabled}
            onChange={(e) => set({ topeMonto: e.target.value })}
          />
        </label>
      </div>
      <label className={styles.field} htmlFor={`${id}-desc`}>
        <span className={styles.label}>Descripción</span>
        <input id={`${id}-desc`} type="text" className={styles.input} value={valores.descripcion} disabled={disabled} onChange={(e) => set({ descripcion: e.target.value })} />
      </label>
      <p className={styles.hint}>
        {costo ? AYUDA_COSTO[valores.alcance] : AYUDA[valores.alcance]}{' '}
        {costo ? AYUDA_MONTO.costo : porcentaje ? AYUDA_MONTO.porcentaje : AYUDA_MONTO.por_unidad}
      </p>
      {(valores.topeUnidades !== '' || valores.topeMonto !== '') && (
        <p className={styles.hint}>
          {costo
            ? 'El tope es uno solo para todos los productos y ventas del bono: se reparte por fecha de venta, la venta que lo alcanza cobra lo que queda y las siguientes no cobran.'
            : 'El tope es uno solo para todos los productos y compras del bono: se reparte por fecha de factura, la compra que lo alcanza cobra lo que queda y las siguientes no cobran.'}
        </p>
      )}
    </>
  );
}
