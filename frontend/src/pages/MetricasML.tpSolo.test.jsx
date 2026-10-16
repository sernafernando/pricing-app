/**
 * Métricas ML for a `tplink.solo` user (metricas-ml-tplink-mode P6b): the board the backend locks to the TP
 * store group (P5b), with TP costs always on, no Total Gauss anywhere, Markup TP, and only the groupings the
 * backend takes (Producto, Publicación, Agrupado by tienda).
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import MetricasML from './MetricasML';
import api, { productosAPI } from '../services/api';
import { BOARD_RESPONSE, GROUP_BOARD_RESPONSE } from '../test/visual/metricasMlFixtures';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';
import { withTpSolo } from '../components/metricasMl/tpFixtures';

const mockPermisos = vi.hoisted(() => ({ current: [] }));
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: mockPermisos.current,
    tienePermiso: (code) => mockPermisos.current.includes(code),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));
vi.mock('../utils/ventasMlExport', async (importOriginal) => ({
  ...(await importOriginal()),
  exportMetricasCsv: vi.fn().mockResolvedValue(undefined),
}));
const { exportMetricasCsv } = await import('../utils/ventasMlExport');

let boardFailure;

beforeEach(() => {
  seedTiendasOficiales();
  // With the profit view too: TP mode, not a missing permission, is what hides the toggle.
  mockPermisos.current = ['ml_metricas.ver', 'ml_metricas.ver_ganancia', 'tplink.solo'];
  boardFailure = null;
  exportMetricasCsv.mockClear();
  api.get.mockReset();
  api.get.mockImplementation((url, config) => {
    if (url === '/ml-metricas/board') {
      if (boardFailure) return Promise.reject({ response: { status: boardFailure, data: { detail: 'x' } } });
      const group = config?.params?.group_by === 'group';
      return Promise.resolve({ data: withTpSolo(group ? GROUP_BOARD_RESPONSE : undefined) });
    }
    return Promise.resolve({ data: { rows: [], total: 0 } });
  });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
});

afterAll(resetTiendasOficiales);

const boardCalls = () => api.get.mock.calls.filter(([url]) => url === '/ml-metricas/board');
const lastBoardParams = () => boardCalls().at(-1)[1].params;

describe('MetricasML for a tplink.solo user', () => {
  it('always asks for TP costs, with no toggle to turn them off', async () => {
    await renderWithRouter(<MetricasML />);
    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(0));
    expect(lastBoardParams().costos_tp).toBe(true);
    expect(lastBoardParams()).not.toHaveProperty('pms');
    expect(screen.queryByRole('switch', { name: 'Costos TP' })).not.toBeInTheDocument();
  });

  it('shows Total TP and Markup TP, and Total Gauss nowhere: card, column or column picker', async () => {
    await renderWithRouter(<MetricasML />);
    expect(await screen.findByRole('columnheader', { name: 'Total TP' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Markup TP/ })).toBeInTheDocument();
    expect(screen.getByText('Markup TP', { selector: 'span' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    const picker = within(screen.getByRole('group', { name: 'Elegir columnas visibles' }));
    expect(picker.getByText('Total TP')).toBeInTheDocument();
    expect(picker.queryByText(/Total Gauss/)).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /Total Gauss/ })).not.toBeInTheDocument();
    const kpis = within(screen.getByRole('region', { name: 'Indicadores del período' }));
    expect(kpis.queryByText(/Total Gauss/)).not.toBeInTheDocument();
  });

  it('has no PM filter button, and keeps the other product filters', async () => {
    await renderWithRouter(<MetricasML />);
    expect(await screen.findByRole('button', { name: 'Marca' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'PM' })).not.toBeInTheDocument();
  });

  it('describes the ads positions in terms of Total TP', async () => {
    await renderWithRouter(<MetricasML />);
    expect(await screen.findByText('No se resta publicidad de Total TP ni del markup.')).toBeInTheDocument();
    expect(screen.queryByText(/Total Gauss/)).not.toBeInTheDocument();
  });

  it('reads an unknown Total TP as an incomplete dash, with the warning count', async () => {
    await renderWithRouter(<MetricasML />);
    const cells = await screen.findAllByTestId('total-tp-cell');
    expect(within(cells[2]).getByText('—')).toBeInTheDocument();
    expect(within(cells[2]).getByText('incompleto')).toBeInTheDocument();
    expect(within(cells[1]).getByTitle('2 ventas de la tienda TP-Link sin costo TP: el Total TP está incompleto')).toBeInTheDocument();
  });

  it('groups "Agrupado" only by tienda', async () => {
    await renderWithRouter(<MetricasML />);
    await userEvent.click(within(await screen.findByRole('group', { name: 'Agrupar por' })).getByRole('button', { name: 'Agrupado' }));
    await waitFor(() => expect(lastBoardParams().group_by).toBe('group'));
    expect(lastBoardParams().dimension).toBe('tienda');
    const dimensions = within(screen.getByRole('group', { name: 'Dimensión' })).getAllByRole('button');
    expect(dimensions.map((button) => button.textContent)).toEqual(['Tienda']);
    const groups = within(screen.getByRole('group', { name: 'Agrupar por' })).getAllByRole('button');
    expect(groups.map((button) => button.textContent)).toEqual(['Producto', 'Publicación', 'Agrupado']);
  });

  it('exports the CSV with TP costs and without PMs', async () => {
    await renderWithRouter(<MetricasML />);
    await userEvent.click(await screen.findByRole('button', { name: /Exportar CSV/ }));
    await waitFor(() => expect(exportMetricasCsv).toHaveBeenCalled());
    const params = exportMetricasCsv.mock.calls[0][0];
    expect(params.costos_tp).toBe(true);
    expect(params).not.toHaveProperty('pms');
    expect(params.sort).not.toBe('total_gauss');
  });

  it('a 503 is a board error, never the "Costos TP" toggle note', async () => {
    boardFailure = 503;
    await renderWithRouter(<MetricasML />);
    expect(await screen.findByText('Error al cargar las métricas.')).toBeInTheDocument();
    expect(screen.queryByText(/Se desactivó "Costos TP"/)).not.toBeInTheDocument();
    expect(boardCalls().every(([, config]) => config.params.costos_tp === true)).toBe(true);
  });
});

describe('MetricasML without tplink.solo', () => {
  it('still offers the Costos TP toggle and every dimension', async () => {
    mockPermisos.current = ['ml_metricas.ver', 'ml_metricas.ver_ganancia'];
    api.get.mockImplementation((url, config) =>
      Promise.resolve({ data: config?.params?.group_by === 'group' ? GROUP_BOARD_RESPONSE : BOARD_RESPONSE }),
    );
    await renderWithRouter(<MetricasML />);
    expect(await screen.findByRole('switch', { name: 'Costos TP' })).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole('group', { name: 'Agrupar por' })).getByRole('button', { name: 'Agrupado' }));
    const dimensions = within(await screen.findByRole('group', { name: 'Dimensión' })).getAllByRole('button');
    expect(dimensions.map((button) => button.textContent)).toContain('PM');
    // The PM filter button, besides the PM dimension.
    expect(screen.getAllByRole('button', { name: 'PM' })).toHaveLength(2);
    expect(screen.getByText('No se resta publicidad de Total Gauss ni del markup.')).toBeInTheDocument();
  });
});
