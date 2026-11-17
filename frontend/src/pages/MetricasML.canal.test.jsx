/**
 * vpf-metricas-canal-fe T2 (S1, S2, S5, S6, S10, C3, C4): the board's channel. Who sees which channel, what each
 * channel shows and hides (README table of the approved mockups), what the board is asked for and what the URL keeps.
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router-dom';
import { renderWithRouter } from '../test/renderWithRouter';
import MetricasML from './MetricasML';
import api, { productosAPI } from '../services/api';
import { BOARD_RESPONSE } from '../test/visual/metricasMlFixtures';
import { FUERA_BOARD_RESPONSE, TODO_BOARD_RESPONSE } from '../test/visual/metricasMlCanalFixtures';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';

const ALL = [
  'ml_metricas.ver',
  'ml_metricas.ver_ganancia',
  'ventas_fuera.ver_metricas_pdf',
  'ventas_fuera.ver_ganancia',
  'ventas_fuera.subir_pdf',
];
const perms = vi.hoisted(() => ({ granted: [] }));

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: perms.granted, tienePermiso: (code) => perms.granted.includes(code), cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

// The upload modal has its own tests (SubirPdfModal.test.jsx); here it only proves the board opens it, closes it and
// reloads after a finished upload.
vi.mock('../components/ventasFueraPdf/SubirPdfModal', () => ({
  default: ({ isOpen, onClose, onCargado }) =>
    isOpen ? (
      <div role="dialog" aria-label="Subir PDF de ventas por fuera">
        <button type="button" onClick={() => onCargado({ carga_id: 1 })}>
          Simular carga
        </button>
        <button type="button" onClick={onClose}>
          Cerrar
        </button>
      </div>
    ) : null,
}));

const answerFor = (params) => {
  if (params?.canal === 'fuera') return FUERA_BOARD_RESPONSE;
  if (params?.canal === 'todo') return TODO_BOARD_RESPONSE;
  return BOARD_RESPONSE;
};

beforeEach(() => {
  perms.granted = [...ALL];
  seedTiendasOficiales();
  api.get.mockReset();
  api.get.mockImplementation((url, config) => {
    if (url === '/ml-metricas/board') return Promise.resolve({ data: answerFor(config?.params) });
    if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
});

afterAll(resetTiendasOficiales);

const boardCalls = () => api.get.mock.calls.filter(([url]) => url === '/ml-metricas/board');
const lastBoardParams = () => boardCalls().at(-1)[1].params;

function LocationProbe() {
  return <output data-testid="location">{useLocation().search}</output>;
}

const renderAt = (search = '') =>
  renderWithRouter(
    <>
      <MetricasML />
      <LocationProbe />
    </>,
    { initialEntries: [`/metricas-ml${search}`] },
  );
const location = () => screen.getByTestId('location').textContent;
const canalGroup = () => screen.queryByRole('group', { name: 'Canal' });

describe('MetricasML canal: who sees which channel (S5 / C4)', () => {
  it('with both permissions offers ML, Por fuera and Todo, ML first and chosen, and asks exactly what it asked before', async () => {
    await renderAt();

    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(0));
    const group = await screen.findByRole('group', { name: 'Canal' });
    expect(within(group).getAllByRole('button').map((b) => b.textContent)).toEqual(['ML', 'Por fuera', 'Todo']);
    expect(within(group).getByRole('button', { name: 'ML' })).toHaveAttribute('aria-pressed', 'true');
    for (const key of ['canal', 'costo', 'empresas', 'vendedores']) expect(lastBoardParams()).not.toHaveProperty(key);
    expect(location()).toBe('');
  });

  it('a PDF-only viewer is locked to Por fuera: no selector, canal=fuera asked and written', async () => {
    perms.granted = ['ventas_fuera.ver_metricas_pdf'];
    await renderAt();

    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(0));
    expect(boardCalls()[0][1].params).toMatchObject({ canal: 'fuera', costo: 'costo_d' });
    expect(canalGroup()).toBeNull();
    await waitFor(() => expect(location()).toBe('?canal=fuera'));
    expect(screen.queryByText(/No tenés permiso/)).not.toBeInTheDocument();
  });

  it('an ML-only viewer sees no selector and the board as always, even on a link to Por fuera', async () => {
    perms.granted = ['ml_metricas.ver', 'ml_metricas.ver_ganancia'];
    await renderAt('?canal=fuera');

    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(0));
    expect(boardCalls()[0][1].params).not.toHaveProperty('canal');
    expect(canalGroup()).toBeNull();
    expect(await screen.findByRole('heading', { name: 'Métricas ML' })).toBeInTheDocument();
  });

  it('without either permission the page says so and asks nothing', async () => {
    perms.granted = [];
    await renderAt();

    expect(screen.getByText(/No tenés permiso para ver Métricas/)).toBeInTheDocument();
    expect(boardCalls()).toHaveLength(0);
  });

  it('?canal=fuera opens Por fuera (the menu links there)', async () => {
    await renderAt('?canal=fuera');

    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(0));
    expect(boardCalls()[0][1].params).toMatchObject({ canal: 'fuera', costo: 'costo_d' });
    expect(within(await screen.findByRole('group', { name: 'Canal' })).getByRole('button', { name: 'Por fuera' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('heading', { name: 'Métricas' })).toBeInTheDocument();
  });

  it('choosing Todo asks canal=todo with Costo D and writes it in the URL', async () => {
    await renderAt();
    const group = await screen.findByRole('group', { name: 'Canal' });

    await userEvent.click(within(group).getByRole('button', { name: 'Todo' }));

    await waitFor(() => expect(lastBoardParams()).toMatchObject({ canal: 'todo', costo: 'costo_d' }));
    expect(location()).toBe('?canal=todo');
  });

  it('Por fuera has no publication view: choosing it while grouped by publication goes by product', async () => {
    await renderAt('?agrupar=publication');
    const group = await screen.findByRole('group', { name: 'Canal' });

    await userEvent.click(within(group).getByRole('button', { name: 'Por fuera' }));

    await waitFor(() => expect(lastBoardParams()).toMatchObject({ canal: 'fuera', group_by: 'product' }));
    const agrupar = screen.getByRole('group', { name: 'Agrupar por' });
    expect(within(agrupar).getAllByRole('button').map((b) => b.textContent)).toEqual(['Producto', 'Agrupado']);
  });
});

describe('MetricasML canal: the controls of each channel (README table)', () => {
  it('Por fuera hides Tienda ML, Publicación, Publicidad, Costos TP and Por tipo de envío', async () => {
    await renderAt('?canal=fuera');
    await screen.findByRole('group', { name: 'Empresa' });

    expect(screen.queryByRole('group', { name: 'Filtrar por tienda oficial' })).toBeNull();
    expect(screen.queryByRole('group', { name: 'Filtrar por estado de publicación' })).toBeNull();
    expect(screen.queryByRole('group', { name: 'Publicidad' })).toBeNull();
    expect(screen.queryByText('Costos TP')).toBeNull();
    expect(screen.queryByRole('region', { name: 'Por tipo de envío' })).toBeNull();
    expect(screen.getByRole('group', { name: 'Costo por fuera' })).toBeInTheDocument();
  });

  it('Todo keeps the ML controls, says which ones filter ML only, and adds Costo, Empresa and Vendedor', async () => {
    await renderAt('?canal=todo');
    await screen.findByRole('group', { name: 'Empresa' });

    expect(screen.getByRole('group', { name: 'Filtrar por tienda oficial' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Publicidad' })).toBeInTheDocument();
    expect(screen.getByText('Costos TP')).toBeInTheDocument();
    expect(screen.getByText('Tienda ML:')).toBeInTheDocument();
    expect(screen.getByText('Publicación (solo ML):')).toBeInTheDocument();
    expect(screen.getByText('Solo resta en ventas ML.')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Por tipo de envío' })).getByText('· solo ventas ML')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Costo por fuera' })).toBeInTheDocument();
    expect(screen.getByLabelText('Vendedor')).toBeInTheDocument();
  });

  it('ML shows no Costo, Empresa, Vendedor nor Canal column (as today)', async () => {
    await renderAt();
    await screen.findByRole('group', { name: 'Canal' });

    expect(screen.queryByRole('group', { name: 'Costo por fuera' })).toBeNull();
    expect(screen.queryByRole('group', { name: 'Empresa' })).toBeNull();
    expect(screen.queryByLabelText('Vendedor')).toBeNull();
    expect(screen.queryByRole('columnheader', { name: 'Canal' })).toBeNull();
    expect(screen.getByText('Tienda:')).toBeInTheDocument();
  });

  it('the cost selector asks costo=costo, keeps it in the URL and explains Costo D', async () => {
    await renderAt('?canal=fuera');
    const group = await screen.findByRole('group', { name: 'Costo por fuera' });
    expect(screen.getByText(/Costo D = Precio Costo × 1,065/)).toBeInTheDocument();

    await userEvent.click(within(group).getByRole('button', { name: 'Costo' }));

    await waitFor(() => expect(lastBoardParams()).toMatchObject({ canal: 'fuera', costo: 'costo' }));
    expect(location()).toBe('?canal=fuera&costo=costo');
  });

  it('the Empresa chips count each one\'s documents and filter by it', async () => {
    await renderAt('?canal=fuera');
    const group = await screen.findByRole('group', { name: 'Empresa' });

    expect(within(group).getByRole('button', { name: 'Todas · 152' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(within(group).getByRole('button', { name: 'Empresa Norte · 152' }));

    await waitFor(() => expect(lastBoardParams()).toMatchObject({ empresas: 'Empresa Norte' }));
    expect(location()).toContain('empresas=Empresa+Norte');
  });

  it('the Vendedor filter asks for one salesperson', async () => {
    await renderAt('?canal=todo');
    const select = await screen.findByLabelText('Vendedor');

    await userEvent.selectOptions(select, 'Vendedor Dos');

    await waitFor(() => expect(lastBoardParams()).toMatchObject({ canal: 'todo', vendedores: 'Vendedor Dos' }));
    expect(location()).toContain('vendedores=Vendedor+Dos');
  });
});

describe('MetricasML canal: C5 additions', () => {
  it('Por fuera shows the salespeople with most documents as chips and filters by one', async () => {
    await renderAt('?canal=fuera');
    const group = await screen.findByRole('group', { name: 'Vendedores' });

    await userEvent.click(within(group).getByRole('button', { name: 'Vendedora Uno · 96' }));

    await waitFor(() => expect(lastBoardParams()).toMatchObject({ canal: 'fuera', vendedores: 'Vendedora Uno' }));
  });

  it('Por fuera shows "Costo (Costo D)" from rows[].costo, and its label follows the cost selector', async () => {
    await renderAt('?canal=fuera');
    expect(await screen.findByRole('columnheader', { name: 'Costo (Costo D)' })).toBeInTheDocument();
    expect(screen.getByText('$ 19.400.000,00')).toBeInTheDocument();

    await userEvent.click(within(screen.getByRole('group', { name: 'Costo por fuera' })).getByRole('button', { name: 'Costo' }));

    expect(await screen.findByRole('columnheader', { name: 'Costo (Costo)' })).toBeInTheDocument();
  });

  it('Todo shows no channel cost column (mockup 1)', async () => {
    await renderAt('?canal=todo');
    await screen.findByRole('columnheader', { name: 'Canal' });
    expect(screen.queryByText('$ 27.067.500,00')).toBeNull();
    expect(screen.queryByRole('columnheader', { name: /^Costo \(/ })).toBeNull();
  });

  it('Por fuera without ventas_fuera.ver_ganancia shows no cost column (S6)', async () => {
    perms.granted = ['ml_metricas.ver', 'ml_metricas.ver_ganancia', 'ventas_fuera.ver_metricas_pdf'];
    await renderAt('?canal=fuera');
    await screen.findByText('Notebook de prueba 15" R7 16GB');
    expect(screen.queryByRole('columnheader', { name: /^Costo \(/ })).toBeNull();
  });
});

describe('MetricasML canal: table, alerts, freshness and upload', () => {
  it('Todo adds the Canal column; Por fuera does not', async () => {
    await renderAt('?canal=todo');
    expect(await screen.findByRole('columnheader', { name: 'Canal' })).toBeInTheDocument();
    expect(screen.getAllByText('ML + fuera').length).toBeGreaterThan(0);
  });

  it('"Sin producto (12)" filters the sin producto rows; ML has no such chip', async () => {
    await renderAt('?canal=fuera');
    const chip = await screen.findByRole('button', { name: /Sin producto \(12\)/ });

    await userEvent.click(chip);

    await waitFor(() => expect(lastBoardParams().alerts).toBe('sin_producto'));
    expect(location()).toContain('alertas=sin_producto');
  });

  it('ML keeps its three alerts and no Sin producto chip', async () => {
    await renderAt();
    const alerts = await screen.findByRole('group', { name: 'Alertas' });
    await waitFor(() => expect(within(alerts).getAllByRole('button')).toHaveLength(3));
    expect(within(alerts).queryByRole('button', { name: /Sin producto/ })).toBeNull();
  });

  it('Por fuera says the cheque surcharge left out and that it has no ML commission nor shipping', async () => {
    await renderAt('?canal=fuera');

    expect(await screen.findByText('Recargo cheque fuera de la venta: $ 412.300,50')).toBeInTheDocument();
    expect(screen.getByText('Por fuera no tiene comisión ML ni envío: Total Gauss = venta − costo.')).toBeInTheDocument();
  });

  it('says how many fuera lines have an unknown Venta (L21)', async () => {
    await renderAt('?canal=todo');

    expect(await screen.findByText(/3 líneas por fuera sin venta conocida/)).toBeInTheDocument();
  });

  it('Todo says the freshness of ML and of the last PDF; Por fuera the last PDF and its salesperson', async () => {
    await renderAt('?canal=todo');
    expect(await screen.findByText(/^ML hace 3 min · PDF \d\d\/11 \d\d:10$/)).toBeInTheDocument();
  });

  it('Por fuera says the last PDF and its salesperson', async () => {
    await renderAt('?canal=fuera');
    expect(await screen.findByText(/^último PDF: \d\d\/11 \d\d:10 · Vendedora Uno$/)).toBeInTheDocument();
  });

  it('"Subir PDF de ventas" shows only with ventas_fuera.subir_pdf', async () => {
    await renderAt('?canal=fuera');
    expect(await screen.findByRole('button', { name: /Subir PDF de ventas/ })).toBeInTheDocument();
  });

  it('"Subir PDF de ventas" opens the upload modal, a finished upload reloads the board and Cerrar closes it', async () => {
    await renderAt('?canal=fuera');
    await userEvent.click(await screen.findByRole('button', { name: /Subir PDF de ventas/ }));

    const dialog = await screen.findByRole('dialog', { name: 'Subir PDF de ventas por fuera' });
    const before = boardCalls().length;
    await userEvent.click(within(dialog).getByRole('button', { name: 'Simular carga' }));
    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(before));
    expect(lastBoardParams()).toMatchObject({ canal: 'fuera' });

    await userEvent.click(within(dialog).getByRole('button', { name: 'Cerrar' }));
    expect(screen.queryByRole('dialog', { name: 'Subir PDF de ventas por fuera' })).toBeNull();
  });

  it('without ventas_fuera.subir_pdf there is no upload button', async () => {
    perms.granted = ALL.filter((code) => code !== 'ventas_fuera.subir_pdf');
    await renderAt('?canal=fuera');
    await screen.findByRole('group', { name: 'Empresa' });
    expect(screen.queryByRole('button', { name: /Subir PDF de ventas/ })).toBeNull();
  });
});

describe('MetricasML canal: margin per channel (S6)', () => {
  it('Por fuera without ventas_fuera.ver_ganancia shows no Total Gauss column even if the answer says it may', async () => {
    perms.granted = ['ml_metricas.ver', 'ml_metricas.ver_ganancia', 'ventas_fuera.ver_metricas_pdf'];
    await renderAt('?canal=fuera');

    await screen.findByRole('group', { name: 'Empresa' });
    await screen.findByText('Notebook de prueba 15" R7 16GB');
    expect(screen.queryByRole('columnheader', { name: /Total Gauss/ })).toBeNull();
    expect(screen.queryByRole('group', { name: 'Publicidad' })).toBeNull();
  });

  it('Todo needs both: with ventas_fuera.ver_ganancia only, no margin; ML with ml_metricas.ver_ganancia keeps it', async () => {
    perms.granted = ['ml_metricas.ver', 'ventas_fuera.ver_metricas_pdf', 'ventas_fuera.ver_ganancia'];
    await renderAt('?canal=todo');
    await screen.findByRole('columnheader', { name: 'Canal' });
    expect(screen.queryByRole('columnheader', { name: /Total Gauss/ })).toBeNull();
  });

  it('ML with ml_metricas.ver_ganancia keeps its margin columns', async () => {
    perms.granted = ['ml_metricas.ver', 'ml_metricas.ver_ganancia', 'ventas_fuera.ver_metricas_pdf'];
    await renderAt();
    expect(await screen.findByRole('columnheader', { name: /Total Gauss/ })).toBeInTheDocument();
  });
});
