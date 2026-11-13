/**
 * TacticalLinea — one line of the Nuevo tactical grid, as the approved design draws it: its scope (Productos | Marca |
 * Categoría, and Factura on sell in), what it includes (product or invoice chips with their picker, or a brand or
 * category), its amount and kind, its unit and money caps, whether several products share the cap, what it can
 * charge at most, and copy / delete. A total amount over products, a brand or a category asks how it is split among
 * the line's products and has no caps (sell out S1, sell in S4); on sell in in USD it needs a fixed exchange rate.
 */
import { Copy, Trash2, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import TacticalPicker from './TacticalPicker';
import { productosAPI } from '../../services/api';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import { etiquetaFactura, facturasCubiertas } from '../tacticals/tacticalsFormat';
import {
  REPARTOS,
  TOTAL_USD_SIN_TC_FIJO,
  alcancesDe,
  alternarFactura,
  conAlcance,
  conModo,
  dinero,
  esCompartida,
  maximoACobrar,
  modosDe,
  modosNoDisponibles,
  puedeCompartir,
  repartePorCriterio,
} from './tacticalLineas';
import Seg from './Seg';
import styles from './TacticalLinea.module.css';

const ALCANCES = { productos: 'Productos', marca: 'Marca', categoria: 'Categoría', factura: 'Factura' };
const MODOS = { por_unidad: 'por unidad', porcentaje: '%', monto_total: 'monto total' };

const AYUDA_REPARTO = {
  iguales: 'Cada producto de la línea recibe la misma parte del total.',
  unidades: 'Cada unidad vendida en el rango recibe la misma parte: sigue las ventas y devoluciones.',
  costo: 'Cada producto recibe una parte según su costo.',
};

function Reparto({ linea, n, cambiar }) {
  return (
    <div className={`${styles.field} ${styles.reparto}`}>
      <select
        className={styles.select}
        aria-label={`Reparto del monto total, línea ${n}`}
        value={linea.reparto}
        onChange={(e) => cambiar({ reparto: e.target.value })}
      >
        <option value="">Elegí cómo repartir</option>
        {REPARTOS.map((r) => (
          <option key={r.value} value={r.value}>
            {r.label}
          </option>
        ))}
      </select>
      <span className={styles.help}>{AYUDA_REPARTO[linea.reparto] ?? 'El total se reparte entre los productos de la línea.'}</span>
    </div>
  );
}

const dia = (iso) => (iso ? iso.split('-').reverse().join('/') : '');
const numeroFactura = (f) => f.numero_factura || f.numero;

const PRODUCTOS = {
  titulo: 'Agregar productos a la línea',
  buscarLabel: 'Buscar productos',
  placeholder: 'Buscar por código o descripción',
  vacio: 'No hay productos para',
  minimo: 2,
  buscar: tacticalsAPI.buscarProductos,
  claveDe: (p) => p.item_id,
  fila: (p) => ({
    codigo: p.codigo,
    descripcion: p.descripcion,
    meta: `Marca ${p.marca || '—'} · ${p.categoria || '—'}`,
  }),
  singular: 'seleccionado',
  plural: 'seleccionados',
};

const FACTURAS = {
  titulo: 'Agregar facturas a la línea',
  buscarLabel: 'Buscar facturas',
  placeholder: 'Buscar por número, proveedor o fecha',
  nota: 'El monto se reparte entre los productos de la factura según lo facturado.',
  vacio: 'No hay facturas para',
  minimo: 0,
  buscar: tacticalsAPI.buscarFacturas,
  claveDe: (f) => f.id,
  fila: (f) => ({
    codigo: numeroFactura(f),
    descripcion: f.proveedor_nombre || `Proveedor ${f.proveedor_id}`,
    // Without its supplier invoice yet: a % or per unit line waits for it (sell in factura pendiente S4).
    meta: `${dia(f.fecha)} · Operación ${f.numero}${f.fecha_factura === null ? ' · Esperando factura' : ''}`,
    importe: dinero(f.moneda, Number(f.monto)),
  }),
  singular: 'seleccionada',
  plural: 'seleccionadas',
};

/**
 * Which invoices of an operation the line applies to (varias facturas S3): "Todas las facturas" (also those linked
 * later) or a pick of them. With one invoice or none there is nothing to pick; a saved pick still reads as it is.
 */
function FacturasDeOperacion({ operacion, n, cambiar }) {
  const lista = operacion.facturas ?? [];
  const elegidas = operacion.facturasCt?.length ? operacion.facturasCt : null;
  if (lista.length < 2) {
    if (elegidas) {
      const conocidas = [...lista, ...(operacion.facturasElegidas ?? [])];
      const etiquetas = elegidas.map((ct) => conocidas.find((f) => f.ct_transaction_id === ct) ?? { ct_transaction_id: ct });
      return <span className={styles.help}>{facturasCubiertas(etiquetas)}</span>;
    }
    const unica = lista.length === 1 ? ` · ${etiquetaFactura(lista[0])}` : '';
    return <span className={styles.help}>{`Todas las facturas${unica}`}</span>;
  }
  return (
    <div className={styles.facturasOp} role="group" aria-label={`Facturas de ${numeroFactura(operacion)}, línea ${n}`}>
      <label className={styles.facturaOp}>
        <input type="checkbox" checked={elegidas == null} onChange={() => cambiar(null)} />
        Todas las facturas
      </label>
      {lista.map((f) => (
        <label key={f.ct_transaction_id} className={styles.facturaOp}>
          <input
            type="checkbox"
            checked={Boolean(elegidas?.includes(f.ct_transaction_id))}
            onChange={() => cambiar(alternarFactura(elegidas, f.ct_transaction_id))}
          />
          {etiquetaFactura(f)}
        </label>
      ))}
    </div>
  );
}

/** The categories a brand has products in (SISO S3); empty while loading, on an error or without a brand. */
function useCategoriasDe(marca) {
  const [categorias, setCategorias] = useState({ marca: '', lista: [] });
  useEffect(() => {
    if (!marca) return undefined;
    let activo = true;
    productosAPI
      .categorias({ marca })
      .then(({ data }) => activo && setCategorias({ marca, lista: data?.categorias ?? [] }))
      .catch(() => activo && setCategorias({ marca, lista: [] }));
    return () => {
      activo = false;
    };
  }, [marca]);
  return categorias.marca === marca ? categorias.lista : [];
}

/** A brand line's optional category: empty is the whole brand (SISO S3: "los routers solo de tp-link"). */
function CategoriaDeMarca({ linea, n, cambiar }) {
  const opciones = useCategoriasDe(linea.marca);
  return (
    <select
      className={styles.select}
      aria-label={`Categoría de la marca, línea ${n}`}
      value={linea.categoria}
      disabled={!linea.marca}
      onChange={(e) => cambiar({ categoria: e.target.value })}
    >
      <option value="">Todas las categorías</option>
      {linea.categoria && !opciones.includes(linea.categoria) && (
        <option value={linea.categoria}>{linea.categoria}</option>
      )}
      {opciones.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

function ayudaDe(linea) {
  if (linea.alcance === 'categoria') return 'Aplica a todos los productos de la categoría.';
  return linea.categoria
    ? 'Aplica a los productos de la marca en esa categoría.'
    : 'Aplica a todos los productos de la marca.';
}

function Incluye({ linea, n, marcas, categorias, abierto, onAbrir, onCerrar, cambiar }) {
  if (linea.alcance === 'marca' || linea.alcance === 'categoria') {
    const marca = linea.alcance === 'marca';
    const opciones = marca ? marcas : categorias;
    const valor = marca ? linea.marca : linea.categoria;
    return (
      <div className={styles.field}>
        <select
          className={styles.select}
          aria-label={marca ? 'Marca de la línea' : 'Categoría de la línea'}
          value={valor}
          onChange={(e) => cambiar(marca ? { marca: e.target.value, categoria: '' } : { categoria: e.target.value })}
        >
          <option value="">{marca ? 'Elegí una marca' : 'Elegí una categoría'}</option>
          {valor && !opciones.includes(valor) && <option value={valor}>{valor}</option>}
          {opciones.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
        {marca && <CategoriaDeMarca linea={linea} n={n} cambiar={cambiar} />}
        <span className={styles.help}>{ayudaDe(linea)}</span>
      </div>
    );
  }
  const facturas = linea.alcance === 'factura';
  const config = facturas ? FACTURAS : PRODUCTOS;
  const items = facturas ? linea.facturas : linea.productos;
  const quitar = (clave) =>
    cambiar(
      facturas
        ? { facturas: linea.facturas.filter((f) => f.id !== clave) }
        : { productos: linea.productos.filter((p) => p.item_id !== clave) },
    );
  return (
    <div className={styles.chips}>
      {items.map((item) => {
        const texto = facturas
          ? `${numeroFactura(item)} · ${item.proveedor_nombre || item.proveedor_id} · ${dia(item.fecha)}`
          : item.descripcion;
        const nombre = facturas ? numeroFactura(item) : item.descripcion;
        const chip = (
          <span key={config.claveDe(item)} className={`${styles.chip} ${facturas ? styles.chipFactura : ''}`}>
            <span className={styles.chipText} title={texto}>
              {texto}
            </span>
            <button
              type="button"
              className={styles.chipX}
              aria-label={`Quitar ${nombre}`}
              onClick={() => quitar(config.claveDe(item))}
            >
              <X size={10} aria-hidden="true" />
            </button>
          </span>
        );
        if (!facturas) return chip;
        const elegir = (facturasCt) =>
          cambiar({ facturas: linea.facturas.map((f) => (f.id === item.id ? { ...f, facturasCt } : f)) });
        return (
          <div key={item.id} className={styles.operacion}>
            {chip}
            <FacturasDeOperacion operacion={item} n={n} cambiar={elegir} />
          </div>
        );
      })}
      <button
        type="button"
        className={styles.add}
        aria-expanded={abierto}
        // The picker closes on a mousedown outside it; this button toggles it itself, so it keeps that event.
        onMouseDown={(e) => abierto && e.stopPropagation()}
        onClick={abierto ? onCerrar : onAbrir}
      >
        {facturas ? '+ Factura' : '+ Producto'}
      </button>
      {abierto && (
        <TacticalPicker
          {...config}
          inicial={items}
          onCerrar={onCerrar}
          onAgregar={(elegidos) => {
            // The picker opens with the line's items checked: what is checked when it adds is the line.
            cambiar(facturas ? { facturas: elegidos } : { productos: elegidos });
            onCerrar();
          }}
        />
      )}
    </div>
  );
}

export default function TacticalLinea({
  linea,
  n,
  tipo,
  moneda,
  tcModo,
  marcas,
  categorias,
  abierto,
  onAbrir,
  onCerrar,
  onCambiar,
  onDuplicar,
  onEliminar,
  contadores = 1, // caps per line: one per store or channel when the cap is not shared (`contadoresDelTope`)
}) {
  const cambiar = (cambios) => onCambiar({ ...linea, ...cambios });
  const max = maximoACobrar(linea, contadores);
  const compartible = puedeCompartir(linea);
  const compartida = esCompartida(linea);
  const porCriterio = repartePorCriterio(linea);

  return (
    <div className={styles.row} role="group" aria-label={`Línea ${n}`}>
      <div className={styles.idx}>{n}</div>

      <div>
        <Seg
          size="xs"
          label={`Alcance de la línea ${n}`}
          options={alcancesDe(tipo).map((value) => ({ value, label: ALCANCES[value] }))}
          value={linea.alcance}
          onChange={(alcance) => {
            if (abierto) onCerrar();
            onCambiar(conAlcance(linea, alcance));
          }}
        />
      </div>

      <div className={styles.includes}>
        <Incluye
          linea={linea}
          n={n}
          marcas={marcas}
          categorias={categorias}
          abierto={abierto}
          onAbrir={onAbrir}
          onCerrar={onCerrar}
          cambiar={cambiar}
        />
        {porCriterio && <Reparto linea={linea} n={n} cambiar={cambiar} />}
      </div>

      {/* Amounts and caps are text read as typed in Argentina ("3000,5", "1.500"): a number input would read the dot
          as a decimal point. */}
      <div className={styles.monto}>
        <input
          className={styles.num}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          placeholder="—"
          aria-label={`Monto de la línea ${n}`}
          value={linea.monto}
          onChange={(e) => cambiar({ monto: e.target.value })}
        />
        <Seg
          size="xxs"
          label={`Unidad del monto, línea ${n}`}
          options={modosDe(tipo).map((value) => ({ value, label: MODOS[value] }))}
          value={linea.modo}
          disabled={modosNoDisponibles(tipo, linea.alcance, moneda, tcModo)}
          motivo={TOTAL_USD_SIN_TC_FIJO}
          onChange={(modo) => onCambiar(conModo(linea, modo))}
        />
      </div>

      {/* A total amount split by criterion has no caps: the cells stay so the line keeps its columns. */}
      <div>
        {!porCriterio && (
          <input
            className={styles.num}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            placeholder="—"
            aria-label={`Tope de unidades, línea ${n}`}
            value={linea.topeUnidades}
            onChange={(e) => cambiar({ topeUnidades: e.target.value })}
          />
        )}
      </div>

      <div>
        {!porCriterio && (
          <input
            className={styles.num}
            type="text"
            inputMode="decimal"
            autoComplete="off"
            placeholder="—"
            aria-label={`Tope de monto en ${moneda}, línea ${n}`}
            value={linea.topeMonto}
            onChange={(e) => cambiar({ topeMonto: e.target.value })}
          />
        )}
      </div>

      <div>
        {linea.alcance !== 'factura' && !porCriterio && (
          <button
            type="button"
            className={`${styles.pill} ${compartida ? styles.pillShared : ''}`}
            disabled={!compartible}
            title={
              compartible
                ? 'Por producto: cada producto de la línea tiene sus propios topes. Compartido: un solo tope para todos.'
                : 'Se puede compartir el tope cuando la línea tiene más de un producto.'
            }
            onClick={() => cambiar({ compartido: !compartida })}
          >
            {compartida ? 'Compartido' : 'Por producto'}
          </button>
        )}
      </div>

      <div className={styles.max}>{max != null ? dinero(moneda, max) : '—'}</div>

      <div className={styles.actions}>
        <button type="button" className={styles.icon} title="Duplicar línea" aria-label={`Duplicar línea ${n}`} onClick={onDuplicar}>
          <Copy size={15} aria-hidden="true" />
        </button>
        <button
          type="button"
          className={`${styles.icon} ${styles.iconDanger}`}
          title="Eliminar línea"
          aria-label={`Eliminar línea ${n}`}
          onClick={onEliminar}
        >
          <Trash2 size={15} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
