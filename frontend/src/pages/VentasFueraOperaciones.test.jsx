/**
 * Operaciones por Fuera (/ventas-fuera-listado; ODD `vpf-operaciones` S2, S3, S3d, S3e, S4-L2): the PDF sales listed
 * per document like Ventas ML, with filters, totals, the "Sin producto" summary by cause, the lines of a document
 * and the manual fixes (cost through the reused ModalEditarCosto, product, remove, confirm) for subir_pdf only.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../services/api';
import VentasFueraOperaciones from './VentasFueraOperaciones';
import { currentMonthRange } from '../utils/dateRangePresets';
import {
  LISTADO,
  LISTADO_SIN_GANANCIA,
  RESUMEN_SIN_PRODUCTO,
  PRODUCTOS_ERP,
} from '../components/ventasFueraOperaciones/fixtures';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

const { permisos } = vi.hoisted(() => ({ permisos: { actuales: new Set() } }));
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [...permisos.actuales],
    tienePermiso: (codigo) => permisos.actuales.has(codigo),
    tieneAlgunPermiso: (codigos) => codigos.some((c) => permisos.actuales.has(c)),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const LISTADO_URL = '/ventas-fuera-pdf/operaciones/listado';
const VER = 'ventas_fuera.ver_metricas_pdf';
const SUBIR = 'ventas_fuera.subir_pdf';

let listado = LISTADO;
function routeGet(url) {
  if (url === LISTADO_URL) return Promise.resolve({ data: listado });
  if (url === '/ventas-fuera-pdf/sin-producto/resumen') return Promise.resolve({ data: RESUMEN_SIN_PRODUCTO });
  if (url === '/buscar-productos-erp') return Promise.resolve({ data: PRODUCTOS_ERP });
  return Promise.resolve({ data: {} });
}

const listadoCalls = () => api.get.mock.calls.filter(([url]) => url === LISTADO_URL);
const lastParams = () => listadoCalls().at(-1)[1].params;

async function renderPage(codigos = [VER, SUBIR]) {
  permisos.actuales = new Set(codigos);
  const user = userEvent.setup();
  render(<VentasFueraOperaciones />);
  await screen.findByRole('row', { name: /Fc A 00008-00018044/ });
  return user;
}

async function abrirDocumento(user, comprobante = 'Fc A 00008-00018044') {
  await user.click(screen.getByText(comprobante));
  return screen.findByRole('complementary', { name: 'Líneas del comprobante' });
}

const filaLinea = (panel, renglon) => within(panel).getByRole('row', { name: new RegExp(`^${renglon} `) });

beforeEach(() => {
  vi.clearAllMocks();
  listado = LISTADO;
  api.get.mockImplementation(routeGet);
  api.put.mockResolvedValue({ data: {} });
  api.post.mockResolvedValue({ data: {} });
  api.delete.mockResolvedValue({ data: {} });
});

describe('Operaciones por Fuera: list', () => {
  it('asks the listado for this month, Costo D, page 1 of 50, newest first, with repeated array params', async () => {
    await renderPage();
    const { desde, hasta } = currentMonthRange();
    const [, config] = listadoCalls()[0];
    expect(config.params).toEqual({ desde, hasta, costo: 'costo_d', page: 1, page_size: 50, sort: 'fecha_desc' });
    expect(config.paramsSerializer).toEqual({ indexes: null });
    expect(screen.getByText('Operaciones por Fuera', { selector: 'h1' })).toBeInTheDocument();
  });

  it('renders one row per document with date, company, salesperson, client, product, qty, sale, cost, Total Gauss and markup', async () => {
    await renderPage();
    const fila = screen.getByRole('row', { name: /Fc A 00008-00018044/ });
    for (const texto of ['12/11/2026', 'Empresa Demo SA', 'Vendedor Uno', 'Cliente Ejemplo SRL', '3 líneas', '8', '$ 100.000,00', '$ 74.550,00', '$ 25.450,00', '34,1%']) {
      expect(within(fila).getByText(texto)).toBeInTheDocument();
    }
    const nc = screen.getByRole('row', { name: /Nc B 00003-00001207/ });
    expect(within(nc).getByText('Mouse de muestra')).toBeInTheDocument();
    expect(within(nc).getByText('-$ 12.000,00')).toBeInTheDocument();
  });

  it('shows the flags of each document: Nc, Cheque with its surcharge, Sin producto and Revisar', async () => {
    await renderPage();
    const fila = screen.getByRole('row', { name: /Fc A 00008-00018044/ });
    expect(within(fila).getByText('Cheque')).toHaveAttribute('title', 'Recargo financiero: $ 4.000,00');
    expect(within(fila).getByText('1 sin producto')).toBeInTheDocument();
    expect(within(fila).getByText('1 a revisar')).toBeInTheDocument();
    expect(within(screen.getByRole('row', { name: /Nc B 00003-00001207/ })).getByText('Nc')).toBeInTheDocument();
  });

  it('shows the totals of the filtered set from the API', async () => {
    await renderPage();
    const kpis = screen.getByRole('region', { name: 'Totales' });
    for (const texto of ['3', '11 unidades en 5 líneas', '$ 96.000,00', '$ 64.965,00', '$ 23.035,00', '35,5%', '2', '$ 23.000,00 de venta', '1']) {
      expect(within(kpis).getByText(texto)).toBeInTheDocument();
    }
  });

  it('explains the Sin producto lines with counts by cause', async () => {
    await renderPage();
    const resumen = screen.getByRole('region', { name: 'Líneas sin producto por causa' });
    const { desde, hasta } = currentMonthRange();
    expect(api.get).toHaveBeenCalledWith('/ventas-fuera-pdf/sin-producto/resumen', { params: { desde, hasta } });
    expect(within(resumen).getByText('Artículo manual, sin código')).toBeInTheDocument();
    expect(within(resumen).getByText('1 línea · $ 15.000,00')).toBeInTheDocument();
    expect(within(resumen).getByText('Código que no está en el catálogo')).toBeInTheDocument();
  });

  it('hides Total Gauss and markup when the API sends them null (no ver_ganancia)', async () => {
    listado = LISTADO_SIN_GANANCIA;
    await renderPage([VER]);
    expect(screen.queryByRole('columnheader', { name: 'Total Gauss' })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Markup' })).not.toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Totales' })).queryByText('Total Gauss')).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Costo D' })).toBeInTheDocument();
  });
});

describe('Operaciones por Fuera: filters build the contract query', () => {
  it('empresa, vendedor, tipo, Sin producto, Revisar, cost basis and search', async () => {
    const user = await renderPage();
    await user.click(within(screen.getByRole('group', { name: 'Empresa' })).getByRole('button', { name: /Otra Empresa Inventada/ }));
    await waitFor(() => expect(lastParams().empresas).toEqual(['Otra Empresa Inventada']));
    await user.click(within(screen.getByRole('group', { name: 'Vendedor' })).getByRole('button', { name: /Vendedora Dos/ }));
    await waitFor(() => expect(lastParams().vendedores).toEqual(['Vendedora Dos']));
    await user.click(within(screen.getByRole('group', { name: 'Tipo' })).getByRole('button', { name: 'Nc' }));
    await waitFor(() => expect(lastParams().tipo).toBe('Nc'));
    await user.click(screen.getByRole('switch', { name: 'Sin producto' }));
    await waitFor(() => expect(lastParams().sin_producto).toBe(true));
    await user.click(screen.getByRole('switch', { name: 'Revisar' }));
    await waitFor(() => expect(lastParams().revisar).toBe(true));
    await user.click(within(screen.getByRole('group', { name: 'Costo' })).getByRole('button', { name: 'Costo' }));
    await waitFor(() => expect(lastParams().costo).toBe('costo'));
    await user.type(screen.getByRole('searchbox', { name: 'Buscar' }), 'monitor{Enter}');
    await waitFor(() => expect(lastParams().q).toBe('monitor'));
    expect(lastParams()).toMatchObject({ page: 1, empresas: ['Otra Empresa Inventada'], tipo: 'Nc' });
  });

  it('sort goes to the API', async () => {
    const user = await renderPage();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Orden' }), 'importe_desc');
    await waitFor(() => expect(lastParams().sort).toBe('importe_desc'));
  });
});

describe('Operaciones por Fuera: lines of a document', () => {
  it('drills into a document and lists its lines with flags and the cause of each Sin producto', async () => {
    const user = await renderPage();
    const panel = await abrirDocumento(user);
    expect(within(panel).getByRole('heading', { name: 'Fc A 00008-00018044' })).toBeInTheDocument();
    expect(within(panel).getByText(/Cliente Ejemplo SRL/)).toBeInTheDocument();

    const manual = filaLinea(panel, 1);
    expect(within(manual).getByText('Monitor de prueba 24"')).toBeInTheDocument();
    expect(within(manual).getByText('Manual')).toBeInTheDocument();

    const sinProducto = filaLinea(panel, 2);
    expect(within(sinProducto).getByText('Sin producto')).toHaveAttribute('title', 'Artículo manual, sin código');
    expect(within(sinProducto).getByText('Artículo manual, sin código')).toBeInTheDocument();

    const revisar = filaLinea(panel, 3);
    expect(within(revisar).getByText('Revisar')).toBeInTheDocument();
    expect(within(revisar).getByText('Producto recordado')).toBeInTheDocument();
  });

  it('shows no fix action without ventas_fuera.subir_pdf', async () => {
    const user = await renderPage([VER]);
    const panel = await abrirDocumento(user);
    expect(within(panel).queryByRole('button', { name: /costo de la línea/ })).not.toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: /producto de la línea/ })).not.toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: /Quitar corrección/ })).not.toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: /Confirmar/ })).not.toBeInTheDocument();
  });
});

describe('Operaciones por Fuera: manual fixes (subir_pdf)', () => {
  it('Costo opens the old ModalEditarCosto and saves its value as the line override, then reloads', async () => {
    const user = await renderPage();
    const panel = await abrirDocumento(user);
    await user.click(within(filaLinea(panel, 2)).getByRole('button', { name: 'Editar costo de la línea 2' }));
    expect(screen.getByText('Editar Costo de Operacion')).toBeInTheDocument();
    const antes = listadoCalls().length;
    await user.type(screen.getByPlaceholderText('Ej: 150000'), '10000');
    await user.click(screen.getByRole('button', { name: 'Guardar Costo' }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith('/ventas-fuera-pdf/lineas/9002/override', { costo_unitario: 10000 * 1.065 }),
    );
    await waitFor(() => expect(listadoCalls().length).toBeGreaterThan(antes));
    expect(screen.queryByText('Editar Costo de Operacion')).not.toBeInTheDocument();
  });

  it('Producto searches the ERP catalog and assigns it, remembering the mapping', async () => {
    const user = await renderPage();
    const panel = await abrirDocumento(user);
    await user.click(within(filaLinea(panel, 2)).getByRole('button', { name: 'Asignar producto de la línea 2' }));
    // ModalTesla portals to <body> with no dialog role: its controls are found by name.
    await screen.findByRole('searchbox', { name: 'Buscar producto' });
    const modal = document.body;
    await user.type(within(modal).getByRole('searchbox', { name: 'Buscar producto' }), 'servicio{Enter}');
    expect(api.get).toHaveBeenCalledWith('/buscar-productos-erp', { params: { q: 'servicio' } });
    await user.click(await within(modal).findByRole('button', { name: /SRV-01/ }));
    expect(within(modal).getByRole('checkbox', { name: 'Recordar para próximas cargas' })).toBeChecked();
    const antes = listadoCalls().length;
    await user.click(within(modal).getByRole('button', { name: 'Asignar' }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith('/ventas-fuera-pdf/lineas/9002/override', { item_id: 7101, recordar_mapeo: true }),
    );
    await waitFor(() => expect(listadoCalls().length).toBeGreaterThan(antes));
  });

  it('Producto without remembering sends recordar_mapeo false', async () => {
    const user = await renderPage();
    const panel = await abrirDocumento(user);
    await user.click(within(filaLinea(panel, 2)).getByRole('button', { name: 'Asignar producto de la línea 2' }));
    // ModalTesla portals to <body> with no dialog role: its controls are found by name.
    await screen.findByRole('searchbox', { name: 'Buscar producto' });
    const modal = document.body;
    await user.type(within(modal).getByRole('searchbox', { name: 'Buscar producto' }), 'servicio{Enter}');
    await user.click(await within(modal).findByRole('button', { name: /SRV-02/ }));
    await user.click(within(modal).getByRole('checkbox', { name: 'Recordar para próximas cargas' }));
    await user.click(within(modal).getByRole('button', { name: 'Asignar' }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith('/ventas-fuera-pdf/lineas/9002/override', { item_id: 7102, recordar_mapeo: false }),
    );
  });

  it('Quitar corrección deletes the override and reloads', async () => {
    const user = await renderPage();
    const panel = await abrirDocumento(user);
    const antes = listadoCalls().length;
    await user.click(within(filaLinea(panel, 1)).getByRole('button', { name: 'Quitar corrección de la línea 1' }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/ventas-fuera-pdf/lineas/9001/override'));
    await waitFor(() => expect(listadoCalls().length).toBeGreaterThan(antes));
  });

  it('Confirmar appears only on a line to review and posts the confirmation', async () => {
    const user = await renderPage();
    const panel = await abrirDocumento(user);
    expect(within(filaLinea(panel, 1)).queryByRole('button', { name: /Confirmar/ })).not.toBeInTheDocument();
    await user.click(within(filaLinea(panel, 3)).getByRole('button', { name: 'Confirmar corrección de la línea 3' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/ventas-fuera-pdf/lineas/9003/override/confirmar'));
  });

  it('a failed fix shows the API message on the page, no browser alert', async () => {
    api.delete.mockRejectedValue({ response: { data: { detail: 'La línea no existe' } } });
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    const user = await renderPage();
    const panel = await abrirDocumento(user);
    await user.click(within(filaLinea(panel, 1)).getByRole('button', { name: 'Quitar corrección de la línea 1' }));
    expect(await within(panel).findByRole('alert')).toHaveTextContent('La línea no existe');
    expect(alertSpy).not.toHaveBeenCalled();
  });
});
