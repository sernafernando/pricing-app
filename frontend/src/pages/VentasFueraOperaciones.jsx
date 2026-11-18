/**
 * Operaciones por Fuera — /ventas-fuera-listado (ODD `vpf-operaciones` S2, S3, S3d, S3e, S4-L2).
 *
 * The sales loaded from the GBP PDFs, one row per document like the Ventas ML operations screen: filters, totals
 * of the filtered set, why lines have no product (counts by cause), and the lines of a document in the side panel.
 * With `ventas_fuera.subir_pdf` each line can be fixed: the cost through the old ModalEditarCosto (same behaviour,
 * saved as the line override), the product (optionally remembered for next uploads), remove the fix, or confirm a
 * fix that a re-upload flagged for review. Fixes are stored apart from the PDF rows, so they survive re-uploads.
 *
 * Total Gauss and markup come null without `ventas_fuera.ver_ganancia`: then their columns and cards are hidden.
 */
import { useEffect, useState } from 'react';
import { AlertTriangle, Search } from 'lucide-react';
import api from '../services/api';
import { usePermisos } from '../contexts/PermisosContext';
import DateRangeFilter from '../components/DateRangeFilter';
import ModalEditarCosto from '../components/ModalEditarCosto';
import { FacetChips, Pagination, SegmentedControl, SplitPanelLayout, StatusPill, SwitchChip, TableShell } from '../components/kit';
import { formatPct } from '../components/kit/kpiFormat';
import { comprobante, dinero, entero, fecha, mensajeError } from '../components/ventasFueraPdf/formato';
import LineasPanel from '../components/ventasFueraOperaciones/LineasPanel';
import AsignarProductoModal from '../components/ventasFueraOperaciones/AsignarProductoModal';
import { currentMonthRange } from '../utils/dateRangePresets';
import {
  buildListadoParams,
  CAUSAS_SIN_PRODUCTO,
  facetas,
  lineaParaModalCosto,
  ORDENES,
  PAGE_SIZE,
} from '../utils/ventasFueraOperaciones';
import styles from './VentasFueraOperaciones.module.css';

const BASE = '/ventas-fuera-pdf';

const TIPOS = [
  { value: '', label: 'Todos' },
  { value: 'Fc', label: 'Fc' },
  { value: 'Nc', label: 'Nc' },
  { value: 'Nd', label: 'Nd' },
];

const BASES_COSTO = [
  { value: 'costo_d', label: 'Costo D', title: 'Precio Costo × 1,065' },
  { value: 'costo', label: 'Costo', title: 'Precio Costo del PDF' },
];

const lineasTexto = (n) => `${entero(n)} ${Number(n) === 1 ? 'línea' : 'líneas'}`;

function Marcas({ operacion }) {
  return (
    <div className={styles.marcas}>
      {operacion.tipo === 'Nc' && <StatusPill tone="purple">Nc</StatusPill>}
      {operacion.cheque && (
        <StatusPill tone="neutral" title={`Recargo financiero: ${dinero(operacion.recargo_financiero)}`}>
          Cheque
        </StatusPill>
      )}
      {operacion.sin_producto_lineas > 0 && (
        <StatusPill tone="warning">{`${entero(operacion.sin_producto_lineas)} sin producto`}</StatusPill>
      )}
      {operacion.revisar_lineas > 0 && <StatusPill tone="danger">{`${entero(operacion.revisar_lineas)} a revisar`}</StatusPill>}
    </div>
  );
}

function productoDe(operacion) {
  const lineas = operacion.lineas || [];
  if (lineas.length === 1) return lineas[0].producto || lineas[0].articulo;
  return lineasTexto(lineas.length);
}

const unidadesDe = (operacion) => (operacion.lineas || []).reduce((suma, l) => suma + (Number(l.cantidad) || 0), 0);

function Totales({ totales, conGanancia, costoLabel }) {
  if (!totales) return null;
  const tarjetas = [
    { label: 'Comprobantes', valor: entero(totales.documentos), sub: `${entero(totales.unidades)} unidades en ${lineasTexto(totales.lineas)}` },
    { label: 'Venta', valor: dinero(totales.venta), sub: 'Suma de las líneas' },
    { label: costoLabel, valor: dinero(totales.costo), sub: 'Líneas en pesos con costo' },
    ...(conGanancia
      ? [
          { label: 'Total Gauss', valor: dinero(totales.total_gauss), sub: 'Venta − costo' },
          { label: 'Markup', valor: formatPct(totales.markup), sub: 'Venta / costo − 1' },
        ]
      : []),
    { label: 'Sin producto', valor: entero(totales.sin_producto_lineas), sub: `${dinero(totales.sin_producto_venta)} de venta`, aviso: totales.sin_producto_lineas > 0 },
    { label: 'A revisar', valor: entero(totales.revisar_lineas), sub: 'Correcciones que una carga nueva cambió', aviso: totales.revisar_lineas > 0 },
  ];
  return (
    <section className={styles.kpis} aria-label="Totales">
      {tarjetas.map((t) => (
        <div key={t.label} className={styles.kpi} data-aviso={t.aviso ? '' : undefined}>
          <span className={styles.kpiLabel}>{t.label}</span>
          <span className={styles.kpiValor}>{t.valor}</span>
          <span className={styles.kpiSub}>{t.sub}</span>
        </div>
      ))}
    </section>
  );
}

function ResumenSinProducto({ resumen }) {
  if (!resumen?.length) return null;
  return (
    <section className={styles.resumen} aria-label="Líneas sin producto por causa">
      <h2 className={styles.resumenTitulo}>
        <AlertTriangle size={14} aria-hidden="true" />
        Por qué hay líneas sin producto
      </h2>
      <ul className={styles.resumenLista}>
        {resumen.map((r) => (
          <li key={r.causa} className={styles.resumenItem}>
            <span>{CAUSAS_SIN_PRODUCTO[r.causa] || r.causa}</span>
            <span className={styles.resumenCifra}>{`${lineasTexto(r.lineas)} · ${dinero(r.venta)}`}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function VentasFueraOperaciones() {
  const { tienePermiso } = usePermisos();
  const puedeCorregir = tienePermiso('ventas_fuera.subir_pdf');

  const [rango, setRango] = useState(() => ({ ...currentMonthRange(), filtro: 'mesActual' }));
  const [filtros, setFiltros] = useState({ empresa: '', vendedor: '', q: '', tipo: '', sinProducto: false, revisar: false, costo: 'costo_d', sort: 'fecha_desc' });
  const [busqueda, setBusqueda] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [recarga, setRecarga] = useState(0);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [resumen, setResumen] = useState([]);

  const [seleccionId, setSeleccionId] = useState(null);
  const [lineaCosto, setLineaCosto] = useState(null);
  const [lineaProducto, setLineaProducto] = useState(null);
  const [errorPanel, setErrorPanel] = useState(null);
  const [ocupado, setOcupado] = useState(false);

  const { desde, hasta } = rango;

  useEffect(() => {
    let vigente = true;
    setLoading(true);
    setError(null);
    api
      .get(`${BASE}/operaciones/listado`, {
        params: buildListadoParams({ desde, hasta, ...filtros, page, pageSize }),
        paramsSerializer: { indexes: null },
      })
      .then((response) => {
        if (vigente) setData(response.data);
      })
      .catch((err) => {
        if (vigente) setError(mensajeError(err, 'No se pudieron cargar las operaciones.'));
      })
      .finally(() => {
        if (vigente) setLoading(false);
      });
    return () => {
      vigente = false;
    };
  }, [desde, hasta, filtros, page, pageSize, recarga]);

  useEffect(() => {
    let vigente = true;
    api
      .get(`${BASE}/sin-producto/resumen`, { params: { desde, hasta } })
      .then((response) => {
        if (vigente) setResumen(response.data || []);
      })
      .catch(() => {
        // The summary is a help, not the page: without it the list still works.
        if (vigente) setResumen([]);
      });
    return () => {
      vigente = false;
    };
  }, [desde, hasta, recarga]);

  const cambiarFiltro = (cambios) => {
    setFiltros((actual) => ({ ...actual, ...cambios }));
    setPage(1);
  };

  const operaciones = data?.operaciones || [];
  const totales = data?.totales;
  const conGanancia = totales ? totales.total_gauss !== null && totales.total_gauss !== undefined : false;
  const costoLabel = filtros.costo === 'costo' ? 'Costo' : 'Costo D';
  const empresas = facetas(data?.facets?.empresas);
  const vendedores = facetas(data?.facets?.vendedores);
  const seleccion = operaciones.find((op) => op.id === seleccionId) || null;

  const recargar = () => setRecarga((n) => n + 1);

  const accionLinea = async (llamada) => {
    setErrorPanel(null);
    setOcupado(true);
    try {
      await llamada();
      recargar();
    } catch (err) {
      setErrorPanel(mensajeError(err, 'No se pudo guardar la corrección.'));
    } finally {
      setOcupado(false);
    }
  };

  const override = (linea) => `${BASE}/lineas/${linea.id}/override`;

  const columns = [
    { key: 'comprobante', fit: true, header: 'Comprobante', width: 170, render: (op) => <span className={styles.num}>{comprobante(op)}</span> },
    { key: 'fecha', fit: true, header: 'Fecha', width: 96, render: (op) => <span className={styles.num}>{fecha(op.fecha)}</span> },
    { key: 'empresa', header: 'Empresa', width: 150, render: (op) => op.empresa },
    { key: 'vendedor', header: 'Vendedor', width: 130, render: (op) => op.vendedor },
    { key: 'cliente', header: 'Cliente', width: 170, render: (op) => op.cliente },
    { key: 'producto', header: 'Producto', width: 200, fill: true, render: (op) => productoDe(op) },
    { key: 'cantidad', fit: true, header: 'Cant.', width: 64, align: 'right', render: (op) => entero(unidadesDe(op)) },
    { key: 'venta', fit: true, header: 'Venta', width: 124, align: 'right', render: (op) => dinero(op.venta) },
    { key: 'costo', fit: true, header: costoLabel, width: 124, align: 'right', render: (op) => dinero(op.costo) },
    ...(conGanancia
      ? [
          { key: 'total_gauss', fit: true, header: 'Total Gauss', width: 124, align: 'right', render: (op) => dinero(op.total_gauss) },
          { key: 'markup', fit: true, header: 'Markup', width: 80, align: 'right', render: (op) => formatPct(op.markup) },
        ]
      : []),
    { key: 'marcas', header: 'Marcas', width: 190, render: (op) => <Marcas operacion={op} /> },
  ];

  // The cost modal gets its `operacion` built once per opening: it resets its fields when that object changes.
  const panel = seleccion && (
    <LineasPanel
      operacion={seleccion}
      conGanancia={conGanancia}
      costoLabel={costoLabel}
      puedeCorregir={puedeCorregir}
      error={errorPanel}
      ocupado={ocupado}
      onClose={() => setSeleccionId(null)}
      onCosto={(linea) => setLineaCosto({ linea, operacion: lineaParaModalCosto(linea, seleccion) })}
      onProducto={(linea) => setLineaProducto(linea)}
      onQuitar={(linea) => accionLinea(() => api.delete(override(linea)))}
      onConfirmar={(linea) => accionLinea(() => api.post(`${override(linea)}/confirmar`))}
    />
  );

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <h1>Operaciones por Fuera</h1>
          <p className={styles.description}>
            Ventas cargadas desde los PDF de GBP, comprobante por comprobante. Tocá uno para ver sus líneas
            {puedeCorregir ? ' y corregir el costo o el producto.' : '.'}
          </p>
        </div>
      </header>

      <section className={styles.filtros} aria-label="Filtros">
        <div className={styles.filaFiltros}>
          <div className={styles.rango}>
            <DateRangeFilter
              fechaDesde={desde}
              fechaHasta={hasta}
              filtroActivo={rango.filtro}
              onChange={({ desde: d, hasta: h, filtro }) => {
                setRango({ desde: d, hasta: h, filtro });
                setPage(1);
              }}
            />
          </div>
          <form
            className={styles.buscador}
            role="search"
            onSubmit={(e) => {
              e.preventDefault();
              cambiarFiltro({ q: busqueda });
            }}
          >
            <input
              type="search"
              className={styles.input}
              aria-label="Buscar"
              placeholder="Cliente, artículo, código o número"
              value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
            />
            <button type="submit" className={styles.btnBuscar} aria-label="Aplicar búsqueda">
              <Search size={14} aria-hidden="true" />
            </button>
          </form>
          <label className={styles.orden}>
            <span>Orden</span>
            <select className={styles.select} value={filtros.sort} onChange={(e) => cambiarFiltro({ sort: e.target.value })}>
              {ORDENES.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className={styles.filaFiltros}>
          <SegmentedControl label="Tipo" options={TIPOS} value={filtros.tipo} onChange={(tipo) => cambiarFiltro({ tipo })} />
          <SwitchChip label="Sin producto" checked={filtros.sinProducto} onChange={(sinProducto) => cambiarFiltro({ sinProducto })} />
          <SwitchChip label="Revisar" checked={filtros.revisar} onChange={(revisar) => cambiarFiltro({ revisar })} />
          <SegmentedControl label="Costo" options={BASES_COSTO} value={filtros.costo} onChange={(costo) => cambiarFiltro({ costo })} />
        </div>
        {empresas.options.length > 0 && (
          <div className={styles.facetas}>
            <span className={styles.facetaLabel}>Empresa</span>
            <FacetChips
              label="Empresa"
              options={empresas.options}
              labels={{}}
              counts={empresas.counts}
              total={data?.total}
              activeValue={filtros.empresa}
              onChange={(empresa) => cambiarFiltro({ empresa })}
            />
          </div>
        )}
        {vendedores.options.length > 0 && (
          <div className={styles.facetas}>
            <span className={styles.facetaLabel}>Vendedor</span>
            <FacetChips
              label="Vendedor"
              options={vendedores.options}
              labels={{}}
              counts={vendedores.counts}
              total={data?.total}
              allLabel="Todos"
              activeValue={filtros.vendedor}
              onChange={(vendedor) => cambiarFiltro({ vendedor })}
            />
          </div>
        )}
      </section>

      <Totales totales={totales} conGanancia={conGanancia} costoLabel={costoLabel} />
      <ResumenSinProducto resumen={resumen} />

      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      <SplitPanelLayout
        open={Boolean(seleccion)}
        panel={panel}
        onClose={() => setSeleccionId(null)}
        width="xl"
        ariaLabel="Líneas del comprobante"
        resizeKey="ventas-fuera-operaciones"
      >
        <section className={styles.tabla} aria-busy={loading || undefined}>
          {loading && !data ? (
            <p className={styles.estado}>Cargando operaciones…</p>
          ) : (
            <TableShell
              columns={columns}
              rows={operaciones}
              getRowKey={(op) => op.id}
              onRowClick={(op) => {
                setErrorPanel(null);
                setSeleccionId(op.id);
              }}
              selectedKey={seleccionId ?? undefined}
              getRowTone={(op) => (op.revisar_lineas > 0 ? { marker: 'var(--tone-danger-fg)', label: 'Tiene correcciones a revisar' } : null)}
              ariaLabel="Operaciones"
              emptyMessage="No hay operaciones con estos filtros"
            />
          )}
          <Pagination
            total={data?.total ?? 0}
            offset={(page - 1) * pageSize}
            pageSize={pageSize}
            onOffsetChange={(offset) => setPage(Math.floor(offset / pageSize) + 1)}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
            pageSizeOptions={[50, 100, 200]}
            summary={
              <span>
                {data?.total
                  ? `mostrando ${entero((page - 1) * pageSize + 1)}-${entero(Math.min(page * pageSize, data.total))} de ${entero(data.total)} comprobantes`
                  : 'Sin comprobantes'}
              </span>
            }
          />
        </section>
      </SplitPanelLayout>

      {lineaCosto && (
        <ModalEditarCosto
          mostrar
          operacion={lineaCosto.operacion}
          onClose={() => setLineaCosto(null)}
          onSave={recargar}
          guardarCosto={(costoUnitario) => api.put(override(lineaCosto.linea), { costo_unitario: costoUnitario })}
        />
      )}
      {lineaProducto && (
        <AsignarProductoModal
          linea={lineaProducto}
          onClose={() => setLineaProducto(null)}
          onAsignar={async (itemId, recordarMapeo) => {
            await api.put(override(lineaProducto), { item_id: itemId, recordar_mapeo: recordarMapeo });
            setLineaProducto(null);
            recargar();
          }}
        />
      )}
    </div>
  );
}
