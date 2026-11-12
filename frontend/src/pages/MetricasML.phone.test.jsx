/**
 * Métricas ML on a phone (handoffs `mobile-metricas-pubml-tarea` T1): cards instead of the board table, the filters
 * in a bottom sheet, "Cargar 20 más" instead of pages -- the same board requests and filters as the desktop. The
 * layout itself is the visual suite's job (`src/test/visual/metricasMlPhone.visual.test.jsx`).
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import MetricasML from './MetricasML';
import api, { productosAPI } from '../services/api';
import { BOARD_RESPONSE, BOARD_ROWS, EPSON_PUBLICATIONS } from '../test/visual/metricasMlFixtures';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';
import { exportMetricasCsv } from '../utils/ventasMlExport';

vi.mock('../hooks/useIsPhone', () => ({ default: () => true }));

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../utils/ventasMlExport', async (importOriginal) => ({
  ...(await importOriginal()),
  exportMetricasCsv: vi.fn(() => Promise.resolve()),
}));
vi.mock('../utils/googleSheetsExport', async (importOriginal) => ({
  ...(await importOriginal()),
  exportMetricasSheets: vi.fn(),
  loadGoogleIdentity: vi.fn(() => Promise.resolve(true)),
}));

// The second page of 20: the same rows under other keys, so they append instead of being dropped as repeats.
const SECOND_PAGE = BOARD_ROWS.slice(0, 2).map((row, i) => ({
  ...row,
  key: `p2-${i}`,
  product_item_id: 9000 + i,
  title: `Segunda página ${i + 1}`,
}));

beforeEach(() => {
  seedTiendasOficiales([{ store_id: 57997, nombre: 'Gauss', clave: null, orden: 0, activa: true }]);
  api.get.mockReset();
  api.get.mockImplementation((url, config) => {
    if (url === '/ml-metricas/board') {
      if (config?.params?.offset === 20) return Promise.resolve({ data: { ...BOARD_RESPONSE, rows: SECOND_PAGE } });
      return Promise.resolve({ data: BOARD_RESPONSE });
    }
    if (url === '/ml-metricas/board/products/4101/publications') return Promise.resolve({ data: EPSON_PUBLICATIONS });
    if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
});

afterAll(resetTiendasOficiales);

const boardCalls = () => api.get.mock.calls.filter(([url]) => url === '/ml-metricas/board');
const lastBoardParams = () => boardCalls().at(-1)[1].params;
const EPSON = 'Impresora Multifunción Epson EcoTank L3250 Color Negro';

const renderPhone = async () => {
  await renderWithRouter(<MetricasML />);
  await screen.findByText(EPSON);
};

describe('MetricasML on a phone', () => {
  it('shows product cards and the KPI cards instead of the board table, 20 at a time', async () => {
    await renderPhone();

    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    const products = screen.getByRole('region', { name: 'Productos' });
    expect(within(products).getAllByRole('article')).toHaveLength(BOARD_ROWS.length);
    const kpis = screen.getByRole('region', { name: 'Indicadores' });
    expect(within(kpis).getByText('Unidades vendidas')).toBeInTheDocument();
    expect(within(kpis).getByText('Facturado bruto')).toBeInTheDocument();
    expect(lastBoardParams()).toMatchObject({ limit: 20, offset: 0 });
  });

  it('says on each card its SKU, brand and publications, and the three figures', async () => {
    await renderPhone();

    const card = screen.getByRole('article', { name: EPSON });
    expect(within(card).getByText('EPS-L3250 · Epson · 3 publicaciones')).toBeInTheDocument();
    expect(within(card).getByText('Unid. período')).toBeInTheDocument();
    expect(within(card).getByText('342')).toBeInTheDocument();
    expect(within(card).getByText('21,6%')).toBeInTheDocument();
    expect(within(card).getByText('$ 204,3 M')).toBeInTheDocument();
  });

  it('expands a card on tap, and lists its publications from "Ver sus n publicaciones"', async () => {
    await renderPhone();
    const card = screen.getByRole('article', { name: EPSON });

    await userEvent.click(within(card).getByRole('button', { name: new RegExp(`^${EPSON}`) }));
    expect(within(card).getByText('Ventas (unidades)')).toBeInTheDocument();
    expect(within(card).getByText('Mín / Máx 90D')).toBeInTheDocument();
    expect(within(card).getByText('Total Gauss')).toBeInTheDocument();
    // The board's cost is the period's total in pesos (the markup's denominator), as the desktop Costo column
    // shows it -- never presented as a unit cost.
    expect(within(card).getByText('Costo del período')).toBeInTheDocument();
    expect(within(card).queryByText('Costo')).not.toBeInTheDocument();
    expect(within(card).getByText('$ 160.181.992,06')).toBeInTheDocument();
    expect(within(card).getByText('c/ sell in $ 156.941.992,06')).toBeInTheDocument();

    await userEvent.click(within(card).getByRole('button', { name: 'Ver sus 3 publicaciones' }));
    expect(await within(card).findByText(/MLA2060835678/)).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/ml-metricas/board/products/4101/publications', expect.anything());

    await userEvent.click(within(card).getByRole('button', { name: 'Menos datos' }));
    expect(within(card).queryByText('Ventas (unidades)')).not.toBeInTheDocument();
  });

  it('"Cargar 20 más" asks the next 20 with the same filters and appends them', async () => {
    await renderPhone();
    const before = lastBoardParams();

    await userEvent.click(screen.getByRole('button', { name: 'Cargar 20 más' }));

    expect(await screen.findByText('Segunda página 1')).toBeInTheDocument();
    expect(screen.getByText(EPSON)).toBeInTheDocument();
    expect(lastBoardParams()).toEqual({ ...before, offset: 20 });
  });

  it('opens the filters as a sheet; a filter there reloads the board, "Ver N productos" closes it', async () => {
    await renderPhone();

    await userEvent.click(screen.getByRole('button', { name: /^Filtros/ }));
    const sheet = screen.getByRole('dialog', { name: 'Filtros' });
    await userEvent.click(within(within(sheet).getByRole('group', { name: 'Filtrar por stock' })).getByRole('button', { name: /Con stock/ }));
    await waitFor(() => expect(lastBoardParams().stock).toBe('con_stock'));

    await userEvent.click(within(sheet).getByRole('button', { name: 'Ver 471 productos' }));
    expect(screen.queryByRole('dialog', { name: 'Filtros' })).not.toBeInTheDocument();
    expect(screen.getByText('Con stock', { selector: 'li' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Filtros/ })).toHaveTextContent('1');
  });

  it('"Limpiar" in the sheet clears the filters', async () => {
    await renderPhone();
    await userEvent.click(screen.getByRole('button', { name: /^Filtros/ }));
    const sheet = screen.getByRole('dialog', { name: 'Filtros' });
    await userEvent.click(within(sheet).getByRole('button', { name: /Sin ventas 30d/ }));
    await waitFor(() => expect(lastBoardParams().alerts).toBe('sin_ventas_30d'));

    await userEvent.click(within(sheet).getByRole('button', { name: 'Limpiar' }));
    await waitFor(() => expect(lastBoardParams().alerts).toBeUndefined());
  });

  it('keeps Producto / Publicación / Cálculo folded until tapped', async () => {
    await renderPhone();
    await userEvent.click(screen.getByRole('button', { name: /^Filtros/ }));
    const sheet = screen.getByRole('dialog', { name: 'Filtros' });
    const calculo = within(sheet).getByRole('button', { name: /^Cálculo/ });
    expect(calculo).toHaveAttribute('aria-expanded', 'false');
    expect(within(sheet).queryByRole('group', { name: 'Comparar con' })).not.toBeInTheDocument();

    await userEvent.click(calculo);
    expect(calculo).toHaveAttribute('aria-expanded', 'true');
    await userEvent.click(within(within(sheet).getByRole('group', { name: 'Comparar con' })).getByRole('button', { name: 'Mismo período año pasado' }));
    await waitFor(() => expect(lastBoardParams().comparar_con).toBe('anio_anterior'));
  });

  it('a period chip and the sort button change the same params as the desktop', async () => {
    await renderPhone();

    await userEvent.click(screen.getByRole('button', { name: '7d' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true'));
    const { date_from: from, date_to: to } = lastBoardParams();
    expect((Date.parse(to) - Date.parse(from)) / 86400000).toBe(6);

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Ordenar por' }), 'units:asc');
    await waitFor(() => expect(lastBoardParams()).toMatchObject({ sort: 'units', sort_dir: 'asc', offset: 0 }));
  });

  it('exports the CSV from the "⋯" menu', async () => {
    await renderPhone();

    await userEvent.click(screen.getByRole('button', { name: /^Más acciones/ }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Exportar CSV' }));

    await waitFor(() => expect(exportMetricasCsv).toHaveBeenCalledWith(expect.objectContaining({ sort: lastBoardParams().sort })));
  });
});
