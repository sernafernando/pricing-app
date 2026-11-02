import { X } from 'lucide-react';
import { sellInAPI } from '../../services/sellInAPI';
import { buscarProductos } from '../sellOut/sellOutBuscar';
import SellInBuscador from './SellInBuscador';
import pageStyles from '../../pages/SellIn.module.css';
import styles from './SellInPanel.module.css';

// The supplier search of the purchase form (SellInCreatePanel): `GET /administracion/proveedores`.
const buscarProveedores = (search) =>
  sellInAPI
    .proveedores(search)
    .then(({ data }) => (data?.proveedores ?? []).map((p) => ({ key: p.id, label: p.nombre, sub: p.cuit, proveedor: p })));

/** One filter: what is picked with a way to clear it, or the search to pick it. */
function Filtro({ label, valor, texto, quitar, buscador }) {
  return (
    <div className={pageStyles.pickerSlot}>
      <span className={pageStyles.filterLabel}>{label}</span>
      {valor ? (
        <div className={styles.chosen}>
          <span>{texto}</span>
          <button type="button" className={styles.close} aria-label={quitar.label} onClick={quitar.onClick}>
            <X size={14} />
          </button>
        </div>
      ) : (
        buscador
      )}
    </div>
  );
}

/**
 * The Sell in list's product and supplier filters (`item_id`, `proveedor_id` on the purchases, their summary and
 * "todo lo filtrado"). `producto` is a catalog row (`item_id`, `codigo`, `descripcion`), `proveedor` a supplier
 * (`id`, `nombre`); `onChange({ producto })` / `onChange({ proveedor })` with the picked one, or null to clear it.
 * `conProveedor` false hides the supplier filter: without a supplier-read permission its search answers 403.
 */
export default function SellInFiltrosExtra({ producto, proveedor, onChange, conProveedor = true }) {
  return (
    <>
      <Filtro
        label="Producto"
        valor={producto}
        texto={producto && `${producto.codigo} · ${producto.descripcion}`}
        quitar={{ label: 'Quitar producto', onClick: () => onChange({ producto: null }) }}
        buscador={
          <SellInBuscador
            label="Producto"
            placeholder="Buscar por código o descripción…"
            buscar={buscarProductos}
            onPick={(opcion) => onChange({ producto: opcion.producto })}
            errorMessage="No se pudieron buscar productos."
          />
        }
      />
      {conProveedor && (
      <Filtro
        label="Proveedor"
        valor={proveedor}
        texto={proveedor?.nombre}
        quitar={{ label: 'Quitar proveedor', onClick: () => onChange({ proveedor: null }) }}
        buscador={
          <SellInBuscador
            label="Proveedor"
            placeholder="Buscar proveedor…"
            buscar={buscarProveedores}
            onPick={(opcion) => onChange({ proveedor: opcion.proveedor })}
            errorMessage="No se pudieron buscar proveedores."
          />
        }
      />
      )}
    </>
  );
}
