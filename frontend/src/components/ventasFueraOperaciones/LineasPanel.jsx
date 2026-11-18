import { Check, Package, Pencil, Undo2, X } from 'lucide-react';
import { StatusPill, TableShell } from '../kit';
import { formatPct } from '../kit/kpiFormat';
import { comprobante, dinero, entero, fecha } from '../ventasFueraPdf/formato';
import { CAUSAS_SIN_PRODUCTO, ORIGEN_PRODUCTO } from '../../utils/ventasFueraOperaciones';
import styles from './LineasPanel.module.css';

const enRevision = (linea) => linea.override_estado === 'revisar' || linea.override?.estado === 'revisar';
const conCorreccion = (linea) => Boolean(linea.override);

function Articulo({ linea, children }) {
  const causa = CAUSAS_SIN_PRODUCTO[linea.sin_producto_causa];
  const origen = ORIGEN_PRODUCTO[linea.item_origen];
  return (
    <div className={styles.articulo}>
      <span className={styles.nombre}>{linea.producto || linea.articulo}</span>
      {linea.producto && <span className={styles.suave}>{linea.articulo}</span>}
      <div className={styles.flags}>
        {linea.sin_producto && (
          <StatusPill tone="warning" title={causa}>
            Sin producto
          </StatusPill>
        )}
        {conCorreccion(linea) && !enRevision(linea) && (
          <StatusPill tone="info" title={linea.override.usuario ? `Corregido por ${linea.override.usuario}` : undefined}>
            Manual
          </StatusPill>
        )}
        {enRevision(linea) && (
          <StatusPill tone="danger" title="La línea cambió en una carga nueva: la corrección no se aplicó">
            Revisar
          </StatusPill>
        )}
      </div>
      {linea.sin_producto && causa && <span className={styles.causa}>{causa}</span>}
      {!linea.sin_producto && origen && <span className={styles.suave}>{origen}</span>}
      {children}
    </div>
  );
}

function Acciones({ linea, onCosto, onProducto, onQuitar, onConfirmar, ocupado }) {
  const n = linea.renglon;
  return (
    <div className={styles.acciones}>
      <button type="button" className={styles.accion} onClick={() => onCosto(linea)} aria-label={`Editar costo de la línea ${n}`} disabled={ocupado}>
        <Pencil size={13} aria-hidden="true" />
        Costo
      </button>
      <button type="button" className={styles.accion} onClick={() => onProducto(linea)} aria-label={`Asignar producto de la línea ${n}`} disabled={ocupado}>
        <Package size={13} aria-hidden="true" />
        Producto
      </button>
      {enRevision(linea) && (
        <button type="button" className={styles.accion} onClick={() => onConfirmar(linea)} aria-label={`Confirmar corrección de la línea ${n}`} disabled={ocupado}>
          <Check size={13} aria-hidden="true" />
          Confirmar
        </button>
      )}
      {conCorreccion(linea) && (
        <button type="button" className={styles.accion} onClick={() => onQuitar(linea)} aria-label={`Quitar corrección de la línea ${n}`} disabled={ocupado}>
          <Undo2 size={13} aria-hidden="true" />
          Quitar corrección
        </button>
      )}
    </div>
  );
}

/**
 * The lines of one PDF document (drill-down of Operaciones por Fuera): product or article with its flags (Sin
 * producto and why, Manual, Revisar), quantities and money, and with `puedeCorregir` the fixes of each line.
 */
export default function LineasPanel({
  operacion,
  conGanancia,
  costoLabel,
  puedeCorregir,
  error,
  ocupado,
  onClose,
  onCosto,
  onProducto,
  onQuitar,
  onConfirmar,
}) {
  const columns = [
    { key: 'renglon', fit: true, header: '#', width: 40, align: 'right', render: (l) => l.renglon },
    {
      key: 'articulo',
      header: 'Artículo',
      width: 220,
      fill: true,
      // The fixes sit under the article, not in a last column: in the narrow panel that column scrolled out of view.
      render: (l) => (
        <Articulo linea={l}>
          {puedeCorregir && (
            <Acciones linea={l} onCosto={onCosto} onProducto={onProducto} onQuitar={onQuitar} onConfirmar={onConfirmar} ocupado={ocupado} />
          )}
        </Articulo>
      ),
    },
    { key: 'cantidad', fit: true, header: 'Cant.', width: 60, align: 'right', render: (l) => entero(l.cantidad) },
    { key: 'precio', fit: true, header: 'Precio', width: 120, align: 'right', render: (l) => dinero(l.precio) },
    {
      key: 'costo',
      fit: true,
      header: costoLabel,
      width: 120,
      align: 'right',
      render: (l) => (
        <span title={l.precio_costo_pdf != null ? `Precio Costo del PDF: ${dinero(l.precio_costo_pdf)}` : undefined}>
          {dinero(l.costo)}
        </span>
      ),
    },
    ...(conGanancia
      ? [
          { key: 'total_gauss', fit: true, header: 'Total Gauss', width: 120, align: 'right', render: (l) => dinero(l.total_gauss) },
          { key: 'markup', fit: true, header: 'Markup', width: 80, align: 'right', render: (l) => formatPct(l.markup) },
        ]
      : []),
  ];

  return (
    <div className={styles.panel}>
      <header className={styles.header}>
        <div className={styles.titulos}>
          <h2 className={styles.titulo}>{comprobante(operacion)}</h2>
          <p className={styles.sub}>
            {fecha(operacion.fecha)} · {operacion.cliente} · {operacion.empresa} · {operacion.vendedor}
          </p>
          <p className={styles.sub}>
            {operacion.condicion_venta}
            {operacion.cheque && Number(operacion.recargo_financiero) ? ` · Recargo financiero ${dinero(operacion.recargo_financiero)}` : ''}
          </p>
        </div>
        <button type="button" className={styles.cerrar} onClick={onClose} aria-label="Cerrar líneas">
          <X size={16} aria-hidden="true" />
        </button>
      </header>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <TableShell
        columns={columns}
        rows={operacion.lineas || []}
        getRowKey={(l) => l.id}
        ariaLabel="Líneas"
        emptyMessage="El comprobante no tiene líneas"
      />
    </div>
  );
}
