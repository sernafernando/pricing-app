import { useEffect, useId, useState } from 'react';
import { X } from 'lucide-react';
import { productosAPI } from '../../services/api';
import { SegmentedControl } from '../kit';
import SellInBonoModelos from './SellInBonoModelos';
import SellInBuscador from './SellInBuscador';
import SellInOperacionPicker from './SellInOperacionPicker';
import styles from './SellInPanel.module.css';

const MONEDAS = [
  { value: 'USD', label: 'USD' },
  { value: 'ARS', label: 'ARS' },
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

/**
 * The fields of a bonus (Stitch `03`, "Definición"): what it reaches (a brand from the brand filter's
 * list, a catalog category, some models from the product search, or one Compras operation), how it
 * pays (an amount per invoiced unit or a % of the invoiced net), the currency (USD by default) and the
 * supplier-invoice date range. Controlled; `disabled` makes it read-only.
 */
export default function SellInBonoForm({ valores, onChange, marcas, disabled = false }) {
  const id = useId();
  const set = (patch) => onChange({ ...valores, ...patch });
  const categorias = useCategorias(valores.alcance === 'categoria' && !disabled);
  const porcentaje = valores.tipo === 'porcentaje';

  const agregarModelo = ({ producto }) => {
    if (valores.modelos.some((m) => m.itemId === producto.item_id)) return;
    set({ modelos: [...valores.modelos, { itemId: producto.item_id, label: `${producto.codigo} · ${producto.descripcion}`, montoUnit: '', porcentaje: '' }] });
  };

  return (
    <>
      <div className={styles.field}>
        <span className={styles.label}>Alcance</span>
        {disabled ? (
          <span>{ALCANCES.find((a) => a.value === valores.alcance)?.label}</span>
        ) : (
          <SegmentedControl label="Alcance" options={ALCANCES} value={valores.alcance} onChange={(alcance) => set({ alcance })} />
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
        {disabled ? (
          <span>{TIPOS.find((t) => t.value === valores.tipo)?.label}</span>
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
          {disabled ? (
            <span>{valores.moneda}</span>
          ) : (
            <SegmentedControl
              label="Moneda"
              options={MONEDAS}
              value={valores.moneda}
              // The money cap is in the bonus's currency: another currency needs it entered again.
              onChange={(moneda) => set(moneda === valores.moneda ? { moneda } : { moneda, topeMonto: '' })}
            />
          )}
        </div>
      </div>
      <div className={styles.grid2}>
        <label className={styles.field} htmlFor={`${id}-desde`}>
          <span className={styles.label}>Factura desde</span>
          <input id={`${id}-desde`} type="date" className={styles.input} value={valores.fechaDesde} disabled={disabled} onChange={(e) => set({ fechaDesde: e.target.value })} />
        </label>
        <label className={styles.field} htmlFor={`${id}-hasta`}>
          <span className={styles.label}>Factura hasta</span>
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
        {AYUDA[valores.alcance]}{' '}
        {porcentaje
          ? 'Paga el porcentaje de lo facturado de cada producto, neto de notas de crédito; si se facturó en la otra moneda, se convierte al tipo de cambio de la operación.'
          : 'Cuenta las unidades facturadas, netas de notas de crédito.'}
      </p>
      {(valores.topeUnidades !== '' || valores.topeMonto !== '') && (
        <p className={styles.hint}>
          El tope es uno solo para todos los productos y compras del bono: se reparte por fecha de factura, la compra que lo
          alcanza cobra lo que queda y las siguientes no cobran.
        </p>
      )}
    </>
  );
}
