import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router-dom';
import { renderWithRouter } from '../test/renderWithRouter';
import { productosAPI } from '../services/api';
import { sellInAPI, sellInBonosAPI } from '../services/sellInAPI';
import { ALCANCE, BONO, BONOS_LISTA, COMPRA_BONO, LISTA, PRODUCTOS, RESUMEN } from '../components/sellIn/sellInFixtures';
import { sellOutAPI, sellOutProgramasAPI } from '../services/sellOutAPI';
import { offsetGruposAPI } from '../services/offsetGruposAPI';
import {
  CAMPANA_MIGRADA,
  CAMPANAS_DEL_PROGRAMA,
  CAMPANAS_LISTA,
  CONSUMOS_USD,
  GRUPOS_POR_PROGRAMA,
  PROGRAMAS_LISTA,
  PROGRAMAS_VACIO,
  RENOVACION_MIGRADA,
  SUGERENCIAS,
  SUGERENCIAS_VACIO,
} from '../components/sellOut/sellOutFixtures';
import SellIn from './SellIn';

vi.mock('../services/sellInAPI', () => ({
  sellInAPI: {
    listar: vi.fn(),
    resumen: vi.fn(),
    detalle: vi.fn(),
    preview: vi.fn(),
    crear: vi.fn(),
    anular: vi.fn(),
    anularMasivo: vi.fn(),
    proveedores: vi.fn(),
  },
  sellInBonosAPI: {
    listar: vi.fn(),
    detalle: vi.fn(),
    alcance: vi.fn(),
    crear: vi.fn(),
    editar: vi.fn(),
    anular: vi.fn(),
    anularMasivo: vi.fn(),
  },
}));

vi.mock('../services/sellOutAPI', () => ({
  sellOutAPI: {
    listar: vi.fn(),
    detalle: vi.fn(),
    crear: vi.fn(),
    editar: vi.fn(),
    grupos: vi.fn(),
    consumos: vi.fn(),
    anularVarias: vi.fn(),
    renovacion: vi.fn(),
    porPrograma: vi.fn(),
  },
  sellOutProgramasAPI: { listar: vi.fn(), crear: vi.fn(), asignar: vi.fn(), sugerencias: vi.fn() },
}));

vi.mock('../services/offsetGruposAPI', () => ({
  offsetGruposAPI: { listar: vi.fn(), alcance: vi.fn(), opciones: vi.fn(), crear: vi.fn() },
}));

const mockTienePermiso = vi.fn();
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: (codigo) => mockTienePermiso(codigo), cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const lastParams = (fn) => fn.mock.calls[fn.mock.calls.length - 1][0];
// The bonus list's own requests, leaving out the active bonuses the summary cards ask for.
const listadosDeBonos = () => sellInBonosAPI.listar.mock.calls.filter(([params]) => params?.estado !== 'activa').length;

beforeEach(() => {
  vi.clearAllMocks();
  mockTienePermiso.mockReturnValue(true);
  sellInAPI.listar.mockResolvedValue({ data: LISTA });
  sellInAPI.resumen.mockResolvedValue({ data: RESUMEN });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: ['Mercusys', 'TP-Link'] } });
  sellInBonosAPI.listar.mockResolvedValue({ data: BONOS_LISTA });
  sellInBonosAPI.detalle.mockResolvedValue({ data: BONO });
  sellInBonosAPI.alcance.mockResolvedValue({ data: ALCANCE });
  sellOutAPI.listar.mockResolvedValue({ data: CAMPANAS_LISTA });
  sellOutAPI.detalle.mockResolvedValue({ data: CAMPANA_MIGRADA });
  sellOutAPI.consumos.mockResolvedValue({ data: CONSUMOS_USD });
  sellOutAPI.grupos.mockResolvedValue({ data: [{ id: 1, nombre: 'TP-Link redes', descripcion: null, filtros: [] }] });
  sellOutAPI.porPrograma.mockResolvedValue({ data: GRUPOS_POR_PROGRAMA });
  sellOutProgramasAPI.listar.mockResolvedValue({ data: PROGRAMAS_VACIO });
  sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS_VACIO });
  offsetGruposAPI.listar.mockResolvedValue({ data: [{ id: 1, nombre: 'TP-Link redes', descripcion: null, filtros: [] }] });
  offsetGruposAPI.alcance.mockResolvedValue({ data: [{ grupo_id: 1, productos: 3, campanas: [] }] });
  offsetGruposAPI.opciones.mockResolvedValue({ data: { marcas: [], categorias: [], subcategorias: [] } });
});

/** Prints where the router is, so a test can read the tab the URL keeps. */
function Ubicacion() {
  const { search } = useLocation();
  return <output data-testid="ubicacion">{search}</output>;
}

const bonosPorEstado = (params) =>
  params?.estado === 'activa' ? { data: { items: [BONO], total: 1, page: 1, page_size: 200 } } : { data: BONOS_LISTA };

describe('SellIn page — Sell in / Sell out tabs (Stitch 01 and 04)', () => {
  it('is one "Sell in / Sell out" page with both tabs counted, Sell in selected and no campaigns in it', async () => {
    renderWithRouter(<SellIn />);
    expect(screen.getByRole('heading', { name: 'Sell in / Sell out', level: 1 })).toBeInTheDocument();
    const tabs = screen.getByRole('tablist', { name: 'Sell in / Sell out' });
    expect(await within(tabs).findByRole('tab', { name: 'Sell in · 4' })).toHaveAttribute('aria-selected', 'true');
    expect(await within(tabs).findByRole('tab', { name: 'Sell out · 2' })).toHaveAttribute('aria-selected', 'false');
    const panel = screen.getByRole('tabpanel', { name: /Sell in/ });
    expect(await within(panel).findByText('Bonificación Q4 switches')).toBeInTheDocument();
    expect(within(panel).getByRole('region', { name: 'Bonos de marca' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Campañas de sell out' })).not.toBeInTheDocument();
  });

  it('the Sell out tab shows the campaigns, hides the sell ins and keeps itself in the URL', async () => {
    const user = userEvent.setup();
    renderWithRouter(
      <>
        <SellIn />
        <Ubicacion />
      </>,
      { initialEntries: ['/sell-in'] },
    );
    await screen.findByText('Bonificación Q4 switches');
    await user.click(screen.getByRole('tab', { name: /Sell out/ }));
    expect(screen.getByRole('tab', { name: /Sell out/ })).toHaveAttribute('aria-selected', 'true');
    const panel = screen.getByRole('tabpanel', { name: /Sell out/ });
    expect(await within(panel).findByText('RB 8180')).toBeInTheDocument();
    expect(screen.queryByText('Bonificación Q4 switches')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Bonos de marca' })).not.toBeInTheDocument();
    expect(screen.getByTestId('ubicacion')).toHaveTextContent('?tab=sell-out');
    await user.click(screen.getByRole('tab', { name: /Sell in/ }));
    expect(await screen.findByText('Bonificación Q4 switches')).toBeInTheDocument();
    expect(screen.getByTestId('ubicacion')).toHaveTextContent(/^$/);
  });

  it('opens on the Sell out tab when the URL says so (a reload keeps the tab)', async () => {
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    expect(screen.getByRole('tab', { name: /Sell out/ })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText('RB 8180')).toBeInTheDocument();
  });

  it('without sell_out.ver there is no Sell out tab, and ?tab=sell-out falls back to Sell in', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'sell_out.ver');
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    expect(await screen.findByText('Bonificación Q4 switches')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /Sell out/ })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Sell in/ })).toHaveAttribute('aria-selected', 'true');
  });

  it('moves between tabs with the arrow keys, and only the selected tab is in the Tab order', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    const sellIn = screen.getByRole('tab', { name: /Sell in/ });
    expect(sellIn).toHaveAttribute('tabindex', '0');
    expect(sellIn).toHaveAttribute('aria-controls', 'sell-in-panel');
    expect(screen.getByRole('tab', { name: /Sell out/ })).toHaveAttribute('tabindex', '-1');
    expect(screen.getByRole('tab', { name: /Sell out/ })).not.toHaveAttribute('aria-controls');
    sellIn.focus();
    await user.keyboard('{ArrowRight}');
    const sellOut = screen.getByRole('tab', { name: /Sell out/ });
    expect(sellOut).toHaveAttribute('aria-selected', 'true');
    expect(sellOut).toHaveFocus();
    expect(await screen.findByText('RB 8180')).toBeInTheDocument();
    await user.keyboard('{ArrowLeft}');
    expect(screen.getByRole('tab', { name: /Sell in/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: /Sell in/ })).toHaveFocus();
  });

  it('the Tipo chips say what each count covers', async () => {
    renderWithRouter(<SellIn />);
    const chips = await screen.findByRole('group', { name: 'Tipo' });
    expect(await within(chips).findByRole('button', { name: 'Bono de marca · 2' })).toHaveAttribute(
      'title',
      'Los bonos de marca con los filtros de arriba, salvo Aplicación, Producto y Proveedor',
    );
    expect(within(chips).getByRole('button', { name: 'Por compra · 2' })).toHaveAttribute('title', 'Los sell in por compra con los filtros de arriba');
  });

  it('a tab whose list failed shows "—" instead of waiting forever', async () => {
    sellOutAPI.listar.mockRejectedValue(new Error('boom'));
    sellInAPI.resumen.mockRejectedValue(new Error('boom'));
    renderWithRouter(<SellIn />);
    expect(await screen.findByRole('tab', { name: 'Sell out · —' })).toBeInTheDocument();
    expect(await screen.findByRole('tab', { name: 'Sell in · —' })).toBeInTheDocument();
  });

  it('the header action follows the tab: "Nuevo sell in" on Sell in, "Nueva campaña" on Sell out', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    expect(screen.getByRole('button', { name: /Nuevo sell in/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Nueva campaña/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: /Sell out/ }));
    expect(screen.getByRole('button', { name: /Nueva campaña/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Nuevo sell in/ })).not.toBeInTheDocument();
  });

  it('the Tipo chips count purchases and brand bonuses and show one list or both', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    const chips = await screen.findByRole('group', { name: 'Tipo' });
    expect(await within(chips).findByRole('button', { name: 'Todos · 4' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(chips).getByRole('button', { name: 'Por compra · 2' })).toBeInTheDocument();
    expect(within(chips).getByRole('button', { name: 'Bono de marca · 2' })).toBeInTheDocument();
    await screen.findByText('Bonificación Q4 switches');

    await user.click(within(chips).getByRole('button', { name: 'Bono de marca · 2' }));
    expect(screen.queryByText('Bonificación Q4 switches')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Bonos de marca' })).toBeInTheDocument();

    await user.click(within(chips).getByRole('button', { name: 'Por compra · 2' }));
    expect(screen.getByText('Bonificación Q4 switches')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Bonos de marca' })).not.toBeInTheDocument();
  });

  it('when the active bonuses cannot be read, their cards say so instead of disappearing', async () => {
    sellInBonosAPI.listar.mockImplementation(async (params) => {
      if (params?.estado === 'activa') throw new Error('boom');
      return { data: BONOS_LISTA };
    });
    renderWithRouter(<SellIn />);
    const cards = await screen.findByRole('region', { name: 'Resumen' });
    const vigentes = (await within(cards).findByText('Bonos de marca vigentes')).parentElement;
    expect(vigentes).toHaveTextContent('—');
    expect(vigentes).toHaveTextContent('No se pudieron cargar');
    expect(within(cards).getByText('Compras alcanzadas').parentElement).toHaveTextContent('—');
  });

  it('saving a brand bonus asks the active bonuses again, so its cards follow the list', async () => {
    const user = userEvent.setup();
    const vigentesPedidos = () => sellInBonosAPI.listar.mock.calls.filter(([params]) => params?.estado === 'activa').length;
    sellInBonosAPI.crear.mockResolvedValue({ data: BONO });
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await waitFor(() => expect(vigentesPedidos()).toBe(1));
    await waitFor(() => expect(screen.getByRole('option', { name: 'TP-Link' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Nuevo sell in/ }));
    const panel = screen.getByRole('complementary', { name: 'Nuevo sell in' });
    await user.click(within(panel).getByRole('button', { name: 'Bono de marca' }));
    await user.selectOptions(within(panel).getByLabelText('Marca'), 'TP-Link');
    await user.type(within(panel).getByLabelText('Monto por unidad'), '3');
    await user.type(within(panel).getByLabelText('Factura desde'), '2026-09-01');
    await user.type(within(panel).getByLabelText('Factura hasta'), '2026-11-30');
    await user.click(within(panel).getByRole('button', { name: 'Guardar bono' }));
    await waitFor(() => expect(vigentesPedidos()).toBe(2));
  });

  it('the summary adds the active brand bonuses, their brands and the purchases they reached', async () => {
    sellInBonosAPI.listar.mockImplementation(async (params) => bonosPorEstado(params));
    renderWithRouter(<SellIn />);
    const cards = await screen.findByRole('region', { name: 'Resumen' });
    await waitFor(() => expect(sellInBonosAPI.listar).toHaveBeenCalledWith({ estado: 'activa', page: 1, page_size: 200 }));
    const vigentes = (await within(cards).findByText('Bonos de marca vigentes')).parentElement;
    expect(vigentes).toHaveTextContent('1');
    expect(vigentes).toHaveTextContent('1 marca');
    const alcanzadas = within(cards).getByText('Compras alcanzadas').parentElement;
    expect(alcanzadas).toHaveTextContent('18');
    expect(alcanzadas).toHaveTextContent('por bonos de marca');
  });
});

// The bonus list's own page requests: not the active bonuses of the summary cards nor "todo lo filtrado" (200 rows).
const listadosDeLaListaDeBonos = () => sellInBonosAPI.listar.mock.calls.map(([params]) => params).filter((params) => params.page_size !== 200);
// The supplier search's answer (`GET /administracion/proveedores`), as SellInCreatePanel.test.jsx reads it.
const PROVEEDORES = { proveedores: [{ id: 7, nombre: 'TP-Link', cuit: '30-1' }], total: 1, page: 1, page_size: 10 };

describe('SellIn page — the top filters also filter the brand bonuses (S4)', () => {
  it('the bonus list follows search, brand, currency, estado and dates, never Aplicación, and goes back to page 1', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.listar.mockResolvedValue({ data: { ...BONOS_LISTA, total: 500 } });
    renderWithRouter(<SellIn />);
    const bonos = await screen.findByRole('region', { name: 'Bonos de marca' });
    await user.click(await within(bonos).findByRole('button', { name: 'Página 2' }));
    await waitFor(() => expect(listadosDeLaListaDeBonos().at(-1)).toEqual({ page: 2, page_size: 10 }));

    await user.selectOptions(screen.getByLabelText('Moneda'), 'USD');
    await user.selectOptions(screen.getByLabelText('Estado'), 'anulada');
    await waitFor(() => expect(screen.getByRole('option', { name: 'TP-Link' })).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText('Marca'), 'TP-Link');
    await user.type(screen.getByPlaceholderText('Buscar por descripción, proveedor o producto…'), 'rebate');
    await user.click(screen.getByTitle('Seleccionar rango personalizado'));
    await user.type(screen.getByLabelText('Desde'), '2026-10-01');
    await user.type(screen.getByLabelText('Hasta'), '2026-10-31');
    await user.click(screen.getByRole('button', { name: 'Aplicar' }));
    await user.click(within(screen.getByRole('group', { name: 'Aplicación' })).getByRole('button', { name: /Todas/ }));

    const esperados = { q: 'rebate', marcas: 'TP-Link', moneda: 'USD', estado: 'anulada', fecha_desde: '2026-10-01', fecha_hasta: '2026-10-31' };
    await waitFor(() => expect(lastParams(sellInAPI.listar)).toEqual({ ...esperados, aplica: 'todas', page: 1, page_size: 50 }));
    expect(listadosDeLaListaDeBonos().at(-1)).toEqual({ ...esperados, page: 1, page_size: 10 });
  });

  it('the active bonuses of the summary cards still ask only estado=activa, whatever the filters', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.selectOptions(screen.getByLabelText('Moneda'), 'USD');
    await user.selectOptions(screen.getByLabelText('Estado'), 'anulada');
    await waitFor(() => expect(listadosDeLaListaDeBonos().at(-1)).toEqual({ moneda: 'USD', estado: 'anulada', page: 1, page_size: 10 }));

    const vigentes = sellInBonosAPI.listar.mock.calls.map(([params]) => params).filter((params) => params.page_size === 200);
    expect(vigentes.length).toBeGreaterThan(0);
    vigentes.forEach((params) => expect(params).toEqual({ estado: 'activa', page: 1, page_size: 200 }));
  });

  it('the bonuses\' "Seleccionar todo lo filtrado" asks every page with the filters on screen', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.selectOptions(screen.getByLabelText('Moneda'), 'USD');
    await waitFor(() => expect(listadosDeLaListaDeBonos().at(-1)).toEqual({ moneda: 'USD', page: 1, page_size: 10 }));
    sellInBonosAPI.listar.mockClear();

    const bonos = screen.getByRole('region', { name: 'Bonos de marca' });
    await user.click(within(bonos).getByRole('button', { name: 'Seleccionar todo lo filtrado (2)' }));

    expect(await within(bonos).findByText('2 seleccionados')).toBeInTheDocument();
    expect(sellInBonosAPI.listar).toHaveBeenCalledWith({ moneda: 'USD', page: 1, page_size: 200 });
  });

  it('other bonus filters drop the bonuses checked under the previous ones', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await user.click(await screen.findByRole('checkbox', { name: `Seleccionar bono #${BONO.id}` }));
    const bonos = screen.getByRole('region', { name: 'Bonos de marca' });
    expect(within(bonos).getByText('1 seleccionado')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Moneda'), 'USD');
    await waitFor(() => expect(within(bonos).queryByText('1 seleccionado')).not.toBeInTheDocument());
  });
});

describe('SellIn page — what the new Sell in filters show when something is missing (S4)', () => {
  it('a failed bonos reload after a filter change shows the error and not the bonos of the previous filters', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    expect(await screen.findByText('Bono anulado')).toBeInTheDocument();
    sellInBonosAPI.listar.mockImplementation(async (params) =>
      params?.page_size === 200 ? { data: { items: [BONO], total: 1, page: 1, page_size: 200 } } : Promise.reject(new Error('caído')),
    );
    await user.selectOptions(within(screen.getByRole('region', { name: 'Filtros' })).getByLabelText('Moneda'), 'USD');
    expect(await screen.findByText('No se pudieron cargar los bonos de marca.')).toBeInTheDocument();
    expect(screen.queryByText('Bono anulado')).not.toBeInTheDocument();
  });

  it('without a permission to read suppliers there is no Proveedor filter (its search would answer 403); Producto stays', async () => {
    mockTienePermiso.mockImplementation((codigo) => !codigo.startsWith('administracion.'));
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    const filtros = screen.getByRole('region', { name: 'Filtros' });
    expect(within(filtros).queryByRole('group', { name: 'Proveedor' })).not.toBeInTheDocument();
    expect(within(filtros).getByRole('group', { name: 'Producto' })).toBeInTheDocument();
  });
});

describe('SellIn page — Producto and Proveedor filters of the purchases (S4)', () => {
  beforeEach(() => {
    productosAPI.listar.mockResolvedValue({ data: { productos: PRODUCTOS, total: 2, page: 1, page_size: 10 } });
    sellInAPI.proveedores.mockResolvedValue({ data: PROVEEDORES });
  });

  it('filter the purchases, their summary and "todo lo filtrado" by id, and not the bonuses', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    const filtros = screen.getByRole('region', { name: 'Filtros' });

    await user.type(within(within(filtros).getByRole('group', { name: 'Producto' })).getByRole('searchbox'), 'sw');
    await user.click(await within(filtros).findByRole('button', { name: /SW-8 · Switch 8 bocas/ }));
    await user.type(within(within(filtros).getByRole('group', { name: 'Proveedor' })).getByRole('searchbox'), 'tp');
    await user.click(await within(filtros).findByRole('button', { name: /TP-Link/ }));

    await waitFor(() => expect(lastParams(sellInAPI.listar)).toEqual({ aplica: 'si', item_id: 4512, proveedor_id: 7, page: 1, page_size: 50 }));
    expect(lastParams(sellInAPI.resumen)).toEqual({ aplica: 'si', item_id: 4512, proveedor_id: 7 });
    expect(listadosDeLaListaDeBonos().at(-1)).toEqual({ page: 1, page_size: 10 });
    expect(within(filtros).getByText('SW-8 · Switch 8 bocas')).toBeInTheDocument();

    await user.click(screen.getAllByRole('button', { name: 'Seleccionar todo lo filtrado (2)' })[0]);
    expect(lastParams(sellInAPI.listar)).toEqual({ aplica: 'si', item_id: 4512, proveedor_id: 7, page: 1, page_size: 200 });

    await user.click(within(filtros).getByRole('button', { name: 'Quitar producto' }));
    await waitFor(() => expect(lastParams(sellInAPI.listar)).toEqual({ aplica: 'si', proveedor_id: 7, page: 1, page_size: 50 }));
    await user.click(within(filtros).getByRole('button', { name: 'Quitar proveedor' }));
    await waitFor(() => expect(lastParams(sellInAPI.listar)).toEqual({ aplica: 'si', page: 1, page_size: 50 }));
  });
});

describe('SellIn page — Grupos tab (T30)', () => {
  it('with grupos.ver a Grupos tab lists the groups and keeps itself in the URL', async () => {
    const user = userEvent.setup();
    renderWithRouter(
      <>
        <SellIn />
        <Ubicacion />
      </>,
    );
    await screen.findByText('Bonificación Q4 switches');
    expect(offsetGruposAPI.listar).not.toHaveBeenCalled();
    await user.click(screen.getByRole('tab', { name: 'Grupos' }));
    expect(screen.getByRole('tab', { name: 'Grupos' })).toHaveAttribute('aria-selected', 'true');
    const panel = screen.getByRole('tabpanel', { name: 'Grupos' });
    expect(await within(panel).findByText('TP-Link redes')).toBeInTheDocument();
    expect(screen.queryByText('Bonificación Q4 switches')).not.toBeInTheDocument();
    expect(screen.getByTestId('ubicacion')).toHaveTextContent('?tab=grupos');
  });

  it('"Actualizar" on the Grupos tab reloads the groups too', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=grupos'] });
    expect(await screen.findByText('TP-Link redes')).toBeInTheDocument();
    expect(offsetGruposAPI.listar).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: /Actualizar/ }));
    await waitFor(() => expect(offsetGruposAPI.listar).toHaveBeenCalledTimes(2));
    expect(offsetGruposAPI.alcance).toHaveBeenCalledTimes(2);
  });

  // Owner (tactical S9): "hoy no existe un permiso para que se vean los grupos, así que solo yo los veo"; on #2083:
  // "sí, sacalo y dejala solo con grupos.ver" (config.editar_constantes alone no longer shows the tab).
  it('without grupos.ver there is no Grupos tab, even with config.editar_constantes, and ?tab=grupos falls back to Sell in', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'grupos.ver');
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=grupos'] });
    expect(await screen.findByText('Bonificación Q4 switches')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Grupos' })).not.toBeInTheDocument();
    expect(offsetGruposAPI.listar).not.toHaveBeenCalled();
  });

  it('with grupos.ver alone the Grupos tab only reads: no Nuevo grupo, no Editar, nothing to check', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'config.editar_constantes');
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=grupos'] });
    const panel = await screen.findByRole('tabpanel', { name: 'Grupos' });
    expect(await within(panel).findByText('TP-Link redes')).toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: /Nuevo grupo/ })).not.toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: 'Editar' })).not.toBeInTheDocument();
    expect(within(panel).queryByRole('checkbox')).not.toBeInTheDocument();
  });
});

describe('SellIn page — list', () => {
  it('opens on the sell ins that apply, and asks the summary for the same filters', async () => {
    renderWithRouter(<SellIn />);
    expect(await screen.findByText('Bonificación Q4 switches')).toBeInTheDocument();
    expect(lastParams(sellInAPI.listar)).toEqual({ aplica: 'si', page: 1, page_size: 50 });
    expect(lastParams(sellInAPI.resumen)).toEqual({ aplica: 'si' });
  });

  it('counts the Aplican / No aplican / Todas chips from resumen.conteo and filters by aplica', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    const chips = await screen.findByRole('group', { name: 'Aplicación' });
    // The chips render with 0 before resumen answers: wait for its counts.
    expect(await within(chips).findByRole('button', { name: 'Aplican · 3' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(chips).getByRole('button', { name: 'No aplican · 1' })).toBeInTheDocument();
    await user.click(within(chips).getByRole('button', { name: 'Todas · 4' }));
    await waitFor(() => expect(lastParams(sellInAPI.listar)).toEqual({ aplica: 'todas', page: 1, page_size: 50 }));
    await user.click(within(chips).getByRole('button', { name: 'No aplican · 1' }));
    await waitFor(() => expect(lastParams(sellInAPI.listar).aplica).toBe('no'));
  });

  it('shows the summary cards from resumen', async () => {
    renderWithRouter(<SellIn />);
    const cards = await screen.findByRole('region', { name: 'Resumen' });
    await waitFor(() => expect(within(cards).getByText('USD 5,50')).toBeInTheDocument());
    expect(within(cards).getByText('$ 3.000,00')).toBeInTheDocument();
    expect(within(cards).getByText('32')).toBeInTheDocument();
    expect(within(cards).getByText('3')).toBeInTheDocument();
  });

  it('renders supplier, amount, units and only the Activa / Anulada states', async () => {
    renderWithRouter(<SellIn />);
    const fila = (await screen.findByText('Bonificación Q4 switches')).closest('tr');
    expect(within(fila).getByText('TP-Link')).toBeInTheDocument();
    expect(within(fila).getByText('$ 1.000,00')).toBeInTheDocument();
    expect(within(fila).getByText('20 / 20')).toBeInTheDocument();
    expect(within(fila).getByText('Activa')).toBeInTheDocument();
    expect(within(fila).getByText('Aplica')).toBeInTheDocument();

    const anulada = screen.getByText('Descuento access points').closest('tr');
    expect(within(anulada).getByText('USD 2,00')).toBeInTheDocument();
    expect(within(anulada).getByText('TC 1.250,50')).toBeInTheDocument();
    expect(within(anulada).getByText('Anulada')).toBeInTheDocument();
    expect(within(anulada).getByText('No aplica')).toBeInTheDocument();
  });

  it('expands a row into its lines with the cost before and after the sell in', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.click(screen.getAllByRole('button', { name: 'Ver ítems' })[0]);
    const linea = screen.getByText('Switch 8 bocas').closest('tr');
    expect(within(linea).getByText('SW-8')).toBeInTheDocument();
    expect(within(linea).getByText('$ 250,00')).toBeInTheDocument();
    expect(within(linea).getByText('$ 100,00')).toBeInTheDocument();
    expect(within(linea).getByText('$ 75,00')).toBeInTheDocument();
    expect(screen.getByText(/Reparto proporcional/)).toBeInTheDocument();
  });

  it('sends search, brand, currency and estado filters and resets to page 1', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.selectOptions(screen.getByLabelText('Moneda'), 'USD');
    await user.selectOptions(screen.getByLabelText('Estado'), 'anulada');
    await waitFor(() => expect(screen.getByRole('option', { name: 'TP-Link' })).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText('Marca'), 'TP-Link');
    await waitFor(() =>
      expect(lastParams(sellInAPI.listar)).toEqual({
        aplica: 'si',
        moneda: 'USD',
        estado: 'anulada',
        marcas: 'TP-Link',
        page: 1,
        page_size: 50,
      }),
    );
    expect(lastParams(sellInAPI.resumen)).toEqual({ aplica: 'si', moneda: 'USD', estado: 'anulada', marcas: 'TP-Link' });
  });

  it('"Nuevo sell in" opens the create panel beside the list, never a modal', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.click(screen.getByRole('button', { name: /Nuevo sell in/ }));
    const panel = screen.getByRole('complementary', { name: 'Nuevo sell in' });
    expect(within(panel).getByRole('heading', { name: 'Nuevo sell in · Por compra' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('Bonificación Q4 switches')).toBeInTheDocument();
  });

  it('"Detalle" opens the purchase in the side panel', async () => {
    const user = userEvent.setup();
    sellInAPI.detalle.mockResolvedValue({ data: LISTA.items[0] });
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.click(screen.getAllByRole('button', { name: 'Detalle' })[0]);
    const panel = screen.getByRole('complementary', { name: 'Detalle del sell in' });
    expect(await within(panel).findByRole('heading', { name: 'Bonificación Q4 switches' })).toBeInTheDocument();
    expect(sellInAPI.detalle).toHaveBeenCalledWith(1);
  });

  it('offers "Nuevo sell in" only with sell_in.gestionar', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo === 'sell_in.ver');
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    expect(screen.queryByRole('button', { name: /Nuevo sell in/ })).not.toBeInTheDocument();
  });

  it('without sell_in.ver it says so and asks nothing', () => {
    mockTienePermiso.mockReturnValue(false);
    renderWithRouter(<SellIn />);
    expect(screen.getByText(/No tenés permiso para ver sell in/)).toBeInTheDocument();
    expect(sellInAPI.listar).not.toHaveBeenCalled();
  });

  it('shows the API message when the list fails', async () => {
    sellInAPI.listar.mockRejectedValue({ response: { status: 500, data: { detail: 'boom' } } });
    renderWithRouter(<SellIn />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar los sell in.');
  });
});

describe('SellIn page — brand bonuses', () => {
  it('"Actualizar" reloads the brand bonuses too', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByRole('region', { name: 'Bonos de marca' });
    await waitFor(() => expect(listadosDeBonos()).toBe(1));
    await user.click(screen.getByRole('button', { name: /Actualizar/ }));
    await waitFor(() => expect(listadosDeBonos()).toBe(2));
  });

  it('lists the brand bonuses with what they generated, and opens one in the side panel', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    const bonos = await screen.findByRole('region', { name: 'Bonos de marca' });
    const fila = (await within(bonos).findByText('Bono TP-Link USD 3/u')).closest('tr');
    expect(sellInBonosAPI.listar).toHaveBeenCalledWith({ page: 1, page_size: 10 });
    expect(within(fila).getByText('Marca TP-LINK')).toBeInTheDocument();
    expect(within(fila).getByText('USD 3,00 / u')).toBeInTheDocument();
    expect(within(fila).getByText('18 compras · 1.040 u')).toBeInTheDocument();
    expect(within(fila).getByText('Activo')).toBeInTheDocument();
    await user.click(within(fila).getByRole('button', { name: 'Ver bono' }));
    const panel = screen.getByRole('complementary', { name: 'Bono de marca' });
    expect(await within(panel).findByRole('heading', { name: 'Bono TP-Link USD 3/u' })).toBeInTheDocument();
    expect(sellInBonosAPI.detalle).toHaveBeenCalledWith(3);
  });

  it('marks a purchase generated by a bonus and links to that bonus', async () => {
    const user = userEvent.setup();
    sellInAPI.listar.mockResolvedValue({ data: { ...LISTA, items: [COMPRA_BONO], total: 1 } });
    renderWithRouter(<SellIn />);
    const fila = (await screen.findByText('Bono de marca TP-LINK (bono 3)')).closest('tr');
    expect(within(fila).getByText('Bono de marca')).toBeInTheDocument();
    await user.click(within(fila).getByRole('button', { name: 'Ver bono #3' }));
    expect(screen.getByRole('complementary', { name: 'Bono de marca' })).toBeInTheDocument();
    await waitFor(() => expect(sellInBonosAPI.detalle).toHaveBeenCalledWith(3));
  });

  it('a bonus created from the switch opens in the panel and the bonus list reloads', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.crear.mockResolvedValue({ data: BONO });
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await waitFor(() => expect(screen.getByRole('option', { name: 'TP-Link' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Nuevo sell in/ }));
    const panel = screen.getByRole('complementary', { name: 'Nuevo sell in' });
    await user.click(within(panel).getByRole('button', { name: 'Bono de marca' }));
    await user.selectOptions(within(panel).getByLabelText('Marca'), 'TP-Link');
    await user.type(within(panel).getByLabelText('Monto por unidad'), '3');
    await user.type(within(panel).getByLabelText('Factura desde'), '2026-09-01');
    await user.type(within(panel).getByLabelText('Factura hasta'), '2026-11-30');
    await user.click(within(panel).getByRole('button', { name: 'Guardar bono' }));
    expect(await screen.findByRole('complementary', { name: 'Bono de marca' })).toBeInTheDocument();
    await waitFor(() => expect(listadosDeBonos()).toBe(2));
  });
});

describe('SellIn page — purchases generated by a brand bonus', () => {
  it('leaves manual purchases without the badge', async () => {
    renderWithRouter(<SellIn />);
    const fila = (await screen.findByText('Bonificación Q4 switches')).closest('tr');
    expect(within(fila).queryByText('Bono de marca')).not.toBeInTheDocument();
  });
});

describe('SellIn page — sell-out campaigns (T8)', () => {
  it('lists the campaigns with their benefit, validity, credit and state', async () => {
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    const fila = (await within(seccion).findByText('RB 8180')).closest('tr');
    expect(fila).toHaveTextContent('USD 36,00 por unidad');
    expect(fila).toHaveTextContent('01/01/2026 – 31/12/2026');
    expect(fila).toHaveTextContent('30 u');
    expect(fila).toHaveTextContent('Activa');
    expect(within(seccion).getByText('TP-Link 2% noviembre').closest('tr')).toHaveTextContent('Anulada');
    expect(lastParams(sellOutAPI.listar)).toEqual({ page: 1, page_size: 10 });
  });

  it('searches the campaigns by name and goes back to page 1', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    await user.type(within(seccion).getByPlaceholderText('Buscar campaña por nombre…'), 'RB');
    await waitFor(() => expect(lastParams(sellOutAPI.listar)).toEqual({ q: 'RB', page: 1, page_size: 10 }));
  });

  it('filters the campaigns by estado, tipo, moneda, marca and grupo, back on page 1', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const filtros = await screen.findByRole('region', { name: 'Filtros de campañas' });
    await waitFor(() => expect(within(filtros).getByRole('option', { name: 'TP-Link redes' })).toBeInTheDocument());
    await user.selectOptions(within(filtros).getByLabelText('Estado'), 'activa');
    await user.selectOptions(within(filtros).getByLabelText('Tipo'), 'monto_total');
    await user.selectOptions(within(filtros).getByLabelText('Moneda'), 'USD');
    await user.selectOptions(within(filtros).getByLabelText('Marca'), 'TP-Link');
    await user.selectOptions(within(filtros).getByLabelText('Grupo'), '1');
    await waitFor(() =>
      expect(lastParams(sellOutAPI.listar)).toEqual({
        estado: 'activa',
        tipo: 'monto_total',
        moneda: 'USD',
        marca: 'TP-Link',
        grupo_id: 1,
        page: 1,
        page_size: 10,
      }),
    );
  });

  it('filters the campaigns by a period they overlap, and "Todas las fechas" clears it', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const filtros = await screen.findByRole('region', { name: 'Filtros de campañas' });
    await user.click(within(filtros).getByRole('button', { name: 'Mes actual' }));
    await waitFor(() =>
      expect(lastParams(sellOutAPI.listar)).toEqual({
        desde: expect.stringMatching(/^\d{4}-\d{2}-01$/),
        hasta: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
        page: 1,
        page_size: 10,
      }),
    );
    await user.click(within(filtros).getByRole('button', { name: 'Todas las fechas' }));
    await waitFor(() => expect(lastParams(sellOutAPI.listar)).toEqual({ page: 1, page_size: 10 }));
  });

  it('"Ver campaña" opens it in the side panel', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    const fila = (await within(seccion).findByText('RB 8180')).closest('tr');
    await user.click(within(fila).getByRole('button', { name: 'Ver campaña' }));
    expect(await screen.findByRole('heading', { name: 'RB 8180', level: 2 })).toBeInTheDocument();
    expect(sellOutAPI.detalle).toHaveBeenCalledWith(55);
  });

  it('a bulk void of the campaign open in the side panel reads it again, so the panel shows it voided', async () => {
    const user = userEvent.setup();
    sellOutAPI.anularVarias.mockResolvedValue({ data: { anuladas: [55], omitidas: [] } });
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    const fila = (await within(seccion).findByText('RB 8180')).closest('tr');
    await user.click(within(fila).getByRole('button', { name: 'Ver campaña' }));
    await screen.findByRole('heading', { name: 'RB 8180', level: 2 });
    expect(sellOutAPI.detalle).toHaveBeenCalledTimes(1);

    sellOutAPI.detalle.mockResolvedValue({ data: { ...CAMPANA_MIGRADA, estado: 'anulada' } });
    await user.click(within(fila).getByRole('checkbox', { name: 'Seleccionar RB 8180' }));
    await user.click(within(seccion).getByRole('button', { name: 'Anular seleccionadas' }));
    await user.click(within(seccion).getByRole('button', { name: 'Confirmar anulación' }));

    await waitFor(() => expect(sellOutAPI.detalle).toHaveBeenCalledTimes(2));
    expect(sellOutAPI.detalle).toHaveBeenLastCalledWith(55);
  });

  it('a bulk void that answers after the panel was closed does not reopen it', async () => {
    const user = userEvent.setup();
    let responder;
    sellOutAPI.anularVarias.mockReturnValue(new Promise((resolve) => (responder = resolve)));
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    const fila = (await within(seccion).findByText('RB 8180')).closest('tr');
    await user.click(within(fila).getByRole('button', { name: 'Ver campaña' }));
    await screen.findByRole('heading', { name: 'RB 8180', level: 2 });
    await user.click(within(fila).getByRole('checkbox', { name: 'Seleccionar RB 8180' }));
    await user.click(within(seccion).getByRole('button', { name: 'Anular seleccionadas' }));
    await user.click(within(seccion).getByRole('button', { name: 'Confirmar anulación' }));

    await user.click(screen.getByRole('button', { name: 'Cerrar' })); // while the bulk void is in flight
    expect(screen.queryByRole('heading', { name: 'RB 8180', level: 2 })).not.toBeInTheDocument();
    responder({ data: { anuladas: [55], omitidas: [] } });

    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('heading', { name: 'RB 8180', level: 2 })).not.toBeInTheDocument();
  });

  it('a bulk void that answers after a new search reloads the current search, not the old one', async () => {
    const user = userEvent.setup();
    let responder;
    sellOutAPI.anularVarias.mockReturnValue(new Promise((resolve) => (responder = resolve)));
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    const fila = (await within(seccion).findByText('RB 8180')).closest('tr');
    await user.click(within(fila).getByRole('checkbox', { name: 'Seleccionar RB 8180' }));
    await user.click(within(seccion).getByRole('button', { name: 'Anular seleccionadas' }));
    await user.click(within(seccion).getByRole('button', { name: 'Confirmar anulación' }));

    await user.type(screen.getByPlaceholderText('Buscar campaña por nombre…'), 'Epson'); // while it is in flight
    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Epson' })));
    const antes = sellOutAPI.listar.mock.calls.length;
    responder({ data: { anuladas: [55], omitidas: [] } });

    await waitFor(() => expect(sellOutAPI.listar.mock.calls.length).toBeGreaterThan(antes));
    expect(sellOutAPI.listar).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Epson' }));
  });

  it('"Actualizar" reloads the campaigns too', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await screen.findByRole('region', { name: 'Campañas de sell out' });
    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', { name: /Actualizar/ }));
    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenCalledTimes(2));
  });

  it('a group created in Grupos is offered in "Nueva campaña" without reloading the page', async () => {
    const user = userEvent.setup();
    const NUEVO = { id: 3, nombre: 'Mercusys', descripcion: null, filtros: [] };
    offsetGruposAPI.crear.mockResolvedValue({ data: NUEVO });
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=grupos'] });
    expect(await screen.findByText('TP-Link redes')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Nuevo grupo' }));
    const panel = screen.getByRole('complementary', { name: 'Grupo' });
    sellOutAPI.grupos.mockResolvedValue({ data: [{ id: 1, nombre: 'TP-Link redes', descripcion: null, filtros: [] }, NUEVO] });
    offsetGruposAPI.listar.mockResolvedValue({ data: [{ id: 1, nombre: 'TP-Link redes', descripcion: null, filtros: [] }, NUEVO] });
    await user.type(within(panel).getByLabelText('Nombre'), 'Mercusys');
    await user.click(within(panel).getByRole('button', { name: 'Crear grupo' }));
    await waitFor(() => expect(offsetGruposAPI.crear).toHaveBeenCalled());

    await user.click(screen.getByRole('tab', { name: /Sell out/ }));
    await user.click(await screen.findByRole('button', { name: /Nueva campaña/ }));
    expect(await screen.findByRole('checkbox', { name: 'Mercusys' })).toBeInTheDocument();
  });

  it('"Actualizar" also asks again the groups a new campaign can reach', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await waitFor(() => expect(sellOutAPI.grupos).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', { name: /Actualizar/ }));
    await waitFor(() => expect(sellOutAPI.grupos).toHaveBeenCalledTimes(2));
  });

  it('"Nueva campaña" opens the form with the offset groups; saving shows the new campaign and reloads the list', async () => {
    const user = userEvent.setup();
    sellOutAPI.crear.mockResolvedValue({ data: { ...CAMPANA_MIGRADA, id: 95, nombre: 'Epson diciembre' } });
    sellOutAPI.detalle.mockResolvedValue({ data: { ...CAMPANA_MIGRADA, id: 95, nombre: 'Epson diciembre' } });
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await screen.findByRole('region', { name: 'Campañas de sell out' });
    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', { name: /Nueva campaña/ }));

    expect(await screen.findByRole('heading', { name: 'Nueva campaña de sell out' })).toBeInTheDocument();
    await user.type(screen.getByLabelText('Nombre'), 'Epson diciembre');
    await user.type(screen.getByLabelText('Monto por unidad'), '12');
    await user.type(screen.getByLabelText('Desde'), '2026-12-01');
    await user.type(screen.getByLabelText('Hasta'), '2026-12-31');
    await user.click(await screen.findByRole('checkbox', { name: 'TP-Link redes' }));
    await user.click(screen.getByRole('button', { name: 'Guardar campaña' }));

    expect(await screen.findByRole('heading', { name: 'Epson diciembre', level: 2 })).toBeInTheDocument();
    expect(sellOutAPI.detalle).toHaveBeenCalledWith(95);
    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenCalledTimes(2));
  });

  it('"Renovar" saves the copy as a new campaign and shows it like "Nueva campaña"; the original is not edited', async () => {
    const user = userEvent.setup();
    const NUEVA = { ...CAMPANA_MIGRADA, id: 96, fecha_desde: '2027-01-01', fecha_hasta: '2027-03-31' };
    sellOutAPI.renovacion.mockResolvedValue({ data: RENOVACION_MIGRADA });
    sellOutAPI.crear.mockResolvedValue({ data: NUEVA });
    sellOutAPI.detalle.mockImplementation(async (id) => ({ data: id === 96 ? NUEVA : CAMPANA_MIGRADA }));
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenCalledTimes(1));
    const fila = (await within(seccion).findByText('RB 8180')).closest('tr');
    await user.click(within(fila).getByRole('button', { name: 'Ver campaña' }));
    await screen.findByRole('heading', { name: 'RB 8180', level: 2 });
    // The panel's own button: each row has one too (slice E).
    await user.click(screen.getAllByRole('button', { name: 'Renovar' }).find((b) => !b.closest('table')));
    expect(await screen.findByText('Copia de «RB 8180». Revisá fechas y montos antes de guardar.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Guardar campaña' }));

    await waitFor(() => expect(sellOutAPI.detalle).toHaveBeenCalledWith(96));
    expect(await screen.findByRole('heading', { name: 'RB 8180', level: 2 })).toBeInTheDocument();
    expect(await screen.findByLabelText('Desde')).toHaveValue('2027-01-01');
    expect(screen.queryByText(/Copia de/)).not.toBeInTheDocument();
    expect(sellOutAPI.editar).not.toHaveBeenCalled();
    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenCalledTimes(2));
  });

  it('without sell_out.gestionar there is no "Nueva campaña" and the groups are not asked', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'sell_out.gestionar');
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    await within(seccion).findByText('RB 8180');
    expect(screen.queryByRole('button', { name: /Nueva campaña/ })).not.toBeInTheDocument();
    expect(sellOutAPI.grupos).not.toHaveBeenCalled();
  });

  it('without sell_out.ver the section is not shown and nothing is asked', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'sell_out.ver');
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    expect(await screen.findByText('Bonificación Q4 switches')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Campañas de sell out' })).not.toBeInTheDocument();
    expect(sellOutAPI.listar).not.toHaveBeenCalled();
  });
});

describe('SellIn page — bulk void (anular masivo)', () => {
  it('voids the selected purchases after confirming, then reloads the list and says what happened', async () => {
    const user = userEvent.setup();
    sellInAPI.anularMasivo.mockResolvedValue({ data: { anuladas: [1], ya_anuladas: [2] } });
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    const listados = sellInAPI.listar.mock.calls.length;

    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar la página de sell in' }));
    expect(screen.getByRole('checkbox', { name: 'Seleccionar compra #1' })).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    const pane = screen.getByRole('dialog', { name: 'Anular 2 compras' });
    expect(pane).toHaveTextContent('Se liberan sus unidades');
    await user.click(within(pane).getByRole('button', { name: 'Sí, anular 2' }));

    expect(sellInAPI.anularMasivo).toHaveBeenCalledWith([1, 2], '');
    expect(await screen.findByRole('status')).toHaveTextContent('Se anuló 1 compra. 1 ya estaba anulada.');
    expect(sellInAPI.listar.mock.calls.length).toBeGreaterThan(listados);
    expect(screen.getByRole('checkbox', { name: 'Seleccionar compra #1' })).not.toBeChecked();
  });

  it('goes back to page 1 after a bulk void: what it voided leaves the list, so the page it was on may no longer exist', async () => {
    const user = userEvent.setup();
    sellInAPI.listar.mockResolvedValue({ data: { ...LISTA, total: 500 } });
    sellInAPI.anularMasivo.mockResolvedValue({ data: { anuladas: [1, 2], ya_anuladas: [] } });
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.click(screen.getAllByRole('button', { name: 'Página 2' })[0]);
    await waitFor(() => expect(lastParams(sellInAPI.listar)).toEqual(expect.objectContaining({ page: 2 })));

    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar la página de sell in' }));
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(screen.getByRole('button', { name: 'Sí, anular 2' }));

    await waitFor(() => expect(lastParams(sellInAPI.listar)).toEqual(expect.objectContaining({ page: 1 })));
  });

  it('reloads with the page on screen when the void ends, not the one it started on', async () => {
    const user = userEvent.setup();
    let soltar;
    sellInAPI.listar.mockResolvedValue({ data: { ...LISTA, total: 500 } });
    sellInAPI.anularMasivo.mockImplementation(() => new Promise((resolve) => (soltar = () => resolve({ data: { anuladas: [1, 2], ya_anuladas: [] } }))));
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.click(screen.getAllByRole('button', { name: 'Página 2' })[0]);
    await waitFor(() => expect(lastParams(sellInAPI.listar)).toEqual(expect.objectContaining({ page: 2 })));
    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar la página de sell in' }));
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(screen.getByRole('button', { name: 'Sí, anular 2' }));

    await user.click(screen.getAllByRole('button', { name: 'Página 1' })[0]);
    await waitFor(() => expect(lastParams(sellInAPI.listar)).toEqual(expect.objectContaining({ page: 1 })));
    const listados = sellInAPI.listar.mock.calls.length;
    soltar();

    await screen.findByRole('status');
    await waitFor(() => expect(sellInAPI.listar.mock.calls.length).toBeGreaterThan(listados));
    expect(lastParams(sellInAPI.listar)).toEqual(expect.objectContaining({ page: 1 }));
  });

  it('the bonus list also goes back to page 1 after a bulk void', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.listar.mockResolvedValue({ data: { ...BONOS_LISTA, total: 500 } });
    sellInBonosAPI.anularMasivo.mockResolvedValue({ data: { anuladas: [BONO.id], ya_anuladas: [] } });
    // The list's own reads, not the active-bonus ones the purchase form takes (`estado: 'activa'`).
    const paginaDeLaLista = () => sellInBonosAPI.listar.mock.calls.map(([p]) => p).filter((p) => !p?.estado).at(-1)?.page;
    renderWithRouter(<SellIn />);
    const bonos = await screen.findByRole('region', { name: 'Bonos de marca' });
    await user.click(await within(bonos).findByRole('button', { name: 'Página 2' }));
    await waitFor(() => expect(paginaDeLaLista()).toBe(2));

    await user.click(within(bonos).getByRole('checkbox', { name: `Seleccionar bono #${BONO.id}` }));
    await user.click(within(bonos).getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(within(bonos).getByRole('button', { name: 'Sí, anular 1' }));

    await screen.findByRole('status');
    await waitFor(() => expect(paginaDeLaLista()).toBe(1));
  });

  it('a purchase a bonus generated cannot be selected: no checkbox, and "todo lo filtrado" leaves it out and says so', async () => {
    const user = userEvent.setup();
    sellInAPI.listar.mockResolvedValue({ data: { ...LISTA, items: [LISTA.items[0], COMPRA_BONO], total: 2, generadas: 1 } });
    sellInAPI.anularMasivo.mockResolvedValue({ data: { anuladas: [LISTA.items[0].id], ya_anuladas: [] } });
    renderWithRouter(<SellIn />);
    await screen.findByRole('checkbox', { name: `Seleccionar compra #${LISTA.items[0].id}` });
    expect(screen.queryByRole('checkbox', { name: `Seleccionar compra #${COMPRA_BONO.id}` })).not.toBeInTheDocument();
    expect(screen.getByText('1 anulable; 1 generada por bonos no se puede anular a mano.')).toBeInTheDocument();

    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar la página de sell in' }));
    expect(screen.getByText('1 seleccionado')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Limpiar selección' }));

    await user.click(screen.getByRole('button', { name: 'Seleccionar todo lo filtrado (1)' }));
    expect(await screen.findByText('1 seleccionado')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(screen.getByRole('button', { name: 'Sí, anular 1' }));
    expect(sellInAPI.anularMasivo).toHaveBeenCalledWith([LISTA.items[0].id], '');
  });

  it('"Seleccionar todo lo filtrado" asks every page with the filters on screen', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');

    await user.click(screen.getAllByRole('button', { name: 'Seleccionar todo lo filtrado (2)' })[0]);

    expect(lastParams(sellInAPI.listar)).toEqual(expect.objectContaining({ aplica: 'si', page: 1, page_size: 200 }));
    expect(await screen.findByText('2 seleccionados')).toBeInTheDocument();
  });

  it('voids the selected brand bonuses through their own bulk endpoint', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.anularMasivo.mockResolvedValue({ data: { anuladas: [BONO.id], ya_anuladas: [] } });
    renderWithRouter(<SellIn />);
    await user.click(await screen.findByRole('checkbox', { name: `Seleccionar bono #${BONO.id}` }));
    const bonos = screen.getByRole('region', { name: 'Bonos de marca' });
    await user.click(within(bonos).getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(within(bonos).getByRole('button', { name: 'Sí, anular 1' }));

    expect(sellInBonosAPI.anularMasivo).toHaveBeenCalledWith([BONO.id], '');
    expect(await screen.findByRole('status')).toHaveTextContent('Se anuló 1 bono.');
  });

  it('without sell_in.gestionar there is nothing to select', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo === 'sell_in.ver');
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    expect(screen.queryByRole('checkbox', { name: /Seleccionar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Seleccionar todo lo filtrado/ })).not.toBeInTheDocument();
  });

  it('says what happened even when only the bonus list is shown', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.anularMasivo.mockResolvedValue({ data: { anuladas: [BONO.id], ya_anuladas: [] } });
    renderWithRouter(<SellIn />);
    const chips = await screen.findByRole('group', { name: 'Tipo' });
    await user.click(await within(chips).findByRole('button', { name: 'Bono de marca · 2' }));
    await user.click(screen.getByRole('checkbox', { name: `Seleccionar bono #${BONO.id}` }));
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(screen.getByRole('button', { name: 'Sí, anular 1' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Se anuló 1 bono.');
  });

  it('drops "todo lo filtrado" when the filters changed while it was read', async () => {
    const user = userEvent.setup();
    let soltar;
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    sellInAPI.listar.mockImplementationOnce(() => new Promise((resolve) => (soltar = () => resolve({ data: LISTA }))));
    await user.click(screen.getAllByRole('button', { name: 'Seleccionar todo lo filtrado (2)' })[0]);
    await user.click(screen.getByRole('button', { name: /No aplican/ }));
    soltar();

    expect(await screen.findByRole('alert')).toHaveTextContent('Los filtros cambiaron mientras se seleccionaba. Volvé a intentarlo.');
    expect(screen.queryByText('2 seleccionados')).not.toBeInTheDocument();
  });

  it('closes the side panel of a purchase it voided, and the notice goes away on the next selection', async () => {
    const user = userEvent.setup();
    sellInAPI.detalle.mockResolvedValue({ data: LISTA.items[0] });
    sellInAPI.anularMasivo.mockResolvedValue({ data: { anuladas: [1], ya_anuladas: [] } });
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.click(screen.getAllByRole('button', { name: 'Detalle' })[0]);
    expect(screen.getByRole('complementary', { name: 'Detalle del sell in' })).toBeInTheDocument();

    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar compra #1' }));
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(screen.getByRole('button', { name: 'Sí, anular 1' }));

    expect(await screen.findByRole('status')).toHaveTextContent('Se anuló 1 compra.');
    expect(screen.queryByRole('complementary', { name: 'Detalle del sell in' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar compra #2' }));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

// ── Programs (campanas-sistema slice E) ─────────────────────────────

const conProgramas = () => sellOutProgramasAPI.listar.mockResolvedValue({ data: PROGRAMAS_LISTA });
const filaDeGrupo = (nombre) => screen.getByRole('button', { name: new RegExp(`^${nombre}`) }).closest('tr');

describe('SellIn page — sell-out programs (campanas-sistema slice E)', () => {
  it('without programs the flat list and its filter defaults are as before: no Programa filter and no view toggle', async () => {
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const filtros = await screen.findByRole('region', { name: 'Filtros de campañas' });
    expect(await screen.findByText('RB 8180')).toBeInTheDocument();
    await waitFor(() => expect(sellOutProgramasAPI.listar).toHaveBeenCalled());
    expect(lastParams(sellOutAPI.listar)).toEqual({ page: 1, page_size: 10 });
    expect(within(filtros).getByLabelText('Moneda')).toHaveValue('');
    expect(within(filtros).getByLabelText('Estado')).toHaveValue('');
    expect(within(filtros).queryByLabelText('Programa')).not.toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Ver' })).not.toBeInTheDocument();
    expect(sellOutAPI.porPrograma).not.toHaveBeenCalled();
  });

  it('"Programas" swaps the campaigns for the programs view, kept in the URL, and "Campañas" brings them back', async () => {
    conProgramas();
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('group', { name: 'Sección' });
    await user.click(within(seccion).getByRole('button', { name: 'Programas' }));

    expect(screen.getByRole('heading', { name: 'Programas' })).toBeInTheDocument();
    expect(screen.getByText(/Programa es el nivel superior/)).toBeInTheDocument();
    expect(screen.getByRole('row', { name: /MARCA PROG/ })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Filtros de campañas' })).not.toBeInTheDocument();

    await user.click(within(seccion).getByRole('button', { name: 'Campañas' }));
    expect(await screen.findByRole('region', { name: 'Filtros de campañas' })).toBeInTheDocument();
  });

  it('"Ver en Campañas" in a program opens the campaigns list filtered by that program', async () => {
    conProgramas();
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out&seccion=programas&vista=lista'] });
    await user.click(await screen.findByRole('button', { name: 'Ver campañas de MARCA PROG' }));
    await user.click(await screen.findByRole('button', { name: 'Ver en Campañas' }));

    const filtros = await screen.findByRole('region', { name: 'Filtros de campañas' });
    expect(within(filtros).getByLabelText('Programa')).toHaveValue('7');
    await waitFor(() => expect(lastParams(sellOutAPI.listar)).toEqual({ programa_id: 7, page: 1, page_size: 10 }));
  });

  it('the Programa filter sends programa_id, or sin_programa for "Sin programa", back on page 1', async () => {
    conProgramas();
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out&vista=lista'] });
    const filtros = await screen.findByRole('region', { name: 'Filtros de campañas' });
    const programa = await within(filtros).findByLabelText('Programa');
    expect(within(programa).getAllByRole('option').map((o) => o.textContent)).toEqual(['Todos', 'Sin programa', 'MARCA PROG', 'Modelos SP']);
    await user.selectOptions(programa, '7');
    await waitFor(() => expect(lastParams(sellOutAPI.listar)).toEqual({ programa_id: 7, page: 1, page_size: 10 }));
    await user.selectOptions(programa, 'sin');
    await waitFor(() => expect(lastParams(sellOutAPI.listar)).toEqual({ sin_programa: true, page: 1, page_size: 10 }));
  });

  it('"Seleccionar todo lo filtrado" resolves the campaigns with the program filter too', async () => {
    conProgramas();
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out&vista=lista'] });
    const filtros = await screen.findByRole('region', { name: 'Filtros de campañas' });
    await user.selectOptions(await within(filtros).findByLabelText('Programa'), '7');
    await waitFor(() => expect(lastParams(sellOutAPI.listar)).toEqual({ programa_id: 7, page: 1, page_size: 10 }));
    await user.click(await screen.findByRole('button', { name: 'Seleccionar todo lo filtrado (2)' }));
    await waitFor(() => expect(lastParams(sellOutAPI.listar)).toEqual({ programa_id: 7, page: 1, page_size: 200 }));
    expect(await screen.findByText('2 seleccionadas')).toBeInTheDocument();
  });

  it('with programs the list opens grouped "Por programa": a row per program with its counts, then "Sin programa"', async () => {
    conProgramas();
    renderWithRouter(
      <>
        <SellIn />
        <Ubicacion />
      </>,
      { initialEntries: ['/sell-in?tab=sell-out'] },
    );
    const ver = await screen.findByRole('group', { name: 'Ver' });
    expect(within(ver).getByRole('button', { name: 'Por programa' })).toHaveAttribute('aria-pressed', 'true');
    const marca = await waitFor(() => filaDeGrupo('MARCA PROG'));
    expect(marca).toHaveTextContent('3 campañas · 2 nombres · 01/08/2026 – 31/10/2026');
    expect(marca).toHaveTextContent('2 activas');
    expect(filaDeGrupo('Sin programa')).toHaveTextContent('1 campaña · 1 nombre · 01/01/2026 – 31/12/2026');
    expect(screen.queryByText('RB 8180')).not.toBeInTheDocument(); // collapsed
    expect(lastParams(sellOutAPI.porPrograma)).toEqual({ page: 1, page_size: 50 });

    await userEvent.setup().click(within(ver).getByRole('button', { name: 'Lista' }));
    expect(await screen.findByText('RB 8180')).toBeInTheDocument();
    expect(screen.getByTestId('ubicacion')).toHaveTextContent('vista=lista');
  });

  it('expanding a group asks its campaigns with the active filters plus the program, or sin_programa', async () => {
    conProgramas();
    sellOutAPI.listar.mockImplementation(async (p) => ({ data: p.programa_id === 7 ? CAMPANAS_DEL_PROGRAMA : CAMPANAS_LISTA }));
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const filtros = await screen.findByRole('region', { name: 'Filtros de campañas' });
    await user.selectOptions(within(filtros).getByLabelText('Estado'), 'activa');
    await waitFor(() => expect(lastParams(sellOutAPI.porPrograma)).toEqual({ estado: 'activa', page: 1, page_size: 50 }));

    await user.click(await waitFor(() => screen.getByRole('button', { name: /^MARCA PROG/ })));
    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenLastCalledWith({ estado: 'activa', programa_id: 7, page: 1, page_size: 200 }));
    const fila = (await screen.findByText('MARCA PROG 3.0')).closest('tr');
    expect(within(fila).getByRole('checkbox', { name: 'Seleccionar MARCA PROG 3.0' })).toBeInTheDocument();
    expect(within(fila).getByRole('button', { name: 'Ver campaña' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^MARCA PROG/ })).toHaveAttribute('aria-expanded', 'true');

    await user.click(screen.getByRole('button', { name: /^Sin programa/ }));
    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenLastCalledWith({ estado: 'activa', sin_programa: true, page: 1, page_size: 200 }));
    expect(await screen.findByText('RB 8180')).toBeInTheDocument();
  });

  it('the campaigns of an open group are nested under it with a ↳ marker; the flat list has none', async () => {
    conProgramas();
    sellOutAPI.listar.mockImplementation(async (p) => ({ data: p.programa_id === 7 ? CAMPANAS_DEL_PROGRAMA : CAMPANAS_LISTA }));
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });

    await user.click(await waitFor(() => screen.getByRole('button', { name: /^MARCA PROG/ })));
    const fila = (await screen.findByText('MARCA PROG 3.0')).closest('tr');
    expect(within(fila).getByText('↳')).toHaveAttribute('aria-hidden', 'true');

    await user.click(within(screen.getByRole('group', { name: 'Ver' })).getByRole('button', { name: 'Lista' }));
    const plana = (await screen.findByText('RB 8180')).closest('tr');
    expect(within(plana).queryByText('↳')).not.toBeInTheDocument();
  });

  it('a program without campaigns under the filters gets no group row', async () => {
    conProgramas(); // MARCA PROG and Modelos SP exist; only MARCA PROG has campaigns under the filters
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await waitFor(() => filaDeGrupo('MARCA PROG'));
    expect(screen.queryByRole('button', { name: /^Modelos SP/ })).not.toBeInTheDocument();
  });

  it('"Asignar ahora" on "Sin programa" assigns every unassigned campaign under the filters', async () => {
    conProgramas();
    sellOutAPI.listar.mockImplementation(async (p) => ({
      data: p.sin_programa ? { items: [CAMPANA_MIGRADA], total: 1, page: 1, page_size: 200 } : CAMPANAS_LISTA,
    }));
    sellOutProgramasAPI.asignar.mockResolvedValue({ data: { asignadas: 1, sin_cambio: 0 } });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const filtros = await screen.findByRole('region', { name: 'Filtros de campañas' });
    await user.selectOptions(within(filtros).getByLabelText('Estado'), 'activa');
    await waitFor(() => expect(lastParams(sellOutAPI.porPrograma)).toEqual({ estado: 'activa', page: 1, page_size: 50 }));

    await user.click(await waitFor(() => within(filaDeGrupo('Sin programa')).getByRole('button', { name: 'Asignar ahora' })));
    expect(sellOutAPI.listar).toHaveBeenLastCalledWith({ estado: 'activa', sin_programa: true, page: 1, page_size: 200 });
    const dialogo = await screen.findByRole('dialog', { name: 'Asignar a programa (1 campaña)' });
    await user.selectOptions(within(dialogo).getByLabelText('Programa'), '7');
    await user.click(within(dialogo).getByRole('button', { name: 'Asignar' }));

    expect(sellOutProgramasAPI.asignar).toHaveBeenCalledWith([55], 7);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(within(filaDeGrupo('MARCA PROG')).queryByRole('button', { name: 'Asignar ahora' })).not.toBeInTheDocument();
  });

  it('"Asignar ahora" that cannot resolve the unassigned campaigns says so and opens no dialog', async () => {
    conProgramas();
    sellOutAPI.listar.mockImplementation(async (p) => ({
      data: p.sin_programa ? { items: [], total: 0, page: 1, page_size: 200 } : CAMPANAS_LISTA,
    }));
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });

    await user.click(await waitFor(() => within(filaDeGrupo('Sin programa')).getByRole('button', { name: 'Asignar ahora' })));

    expect(
      await screen.findByText('La lista de campañas cambió mientras se seleccionaba. Actualizá la lista y volvé a intentar.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it.each([
    [{ response: { status: 403, data: { detail: 'No tienes permiso: sell_out.ver' } } }, 'No tienes permiso: sell_out.ver'],
    [new Error('Network Error'), 'No se pudo conectar con el servidor para seleccionar las campañas.'],
  ])('"Asignar ahora" whose read fails shows the API message or the connection error', async (fallo, mensaje) => {
    conProgramas();
    sellOutAPI.listar.mockImplementation(async (p) => {
      if (p.sin_programa) throw fallo;
      return { data: CAMPANAS_LISTA };
    });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });

    await user.click(await waitFor(() => within(filaDeGrupo('Sin programa')).getByRole('button', { name: 'Asignar ahora' })));

    expect(await screen.findByRole('alert')).toHaveTextContent(mensaje);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('without sell_out.gestionar "Sin programa" has no "Asignar ahora"', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'sell_out.gestionar');
    conProgramas();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });

    await waitFor(() => filaDeGrupo('Sin programa'));
    expect(screen.queryByRole('button', { name: 'Asignar ahora' })).not.toBeInTheDocument();
  });

  it('"Asignar a programa" assigns the selected campaigns to an active program and reloads the list and groups', async () => {
    conProgramas();
    sellOutProgramasAPI.asignar.mockResolvedValue({ data: { asignadas: 1, sin_cambio: 1 } });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out&vista=lista'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    await user.click(await within(seccion).findByRole('checkbox', { name: 'Seleccionar RB 8180' }));
    await user.click(within(seccion).getByRole('checkbox', { name: 'Seleccionar TP-Link 2% noviembre' }));
    await user.click(within(seccion).getByRole('button', { name: 'Asignar a programa' }));

    const dialogo = screen.getByRole('dialog', { name: 'Asignar a programa (2 campañas)' });
    expect(dialogo).toHaveTextContent('Asignar un programa no cambia la plata de las campañas: solo las agrupa.');
    const select = within(dialogo).getByLabelText('Programa');
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Elegí un programa', 'MARCA PROG']); // archived ones are not offered
    const listados = sellOutAPI.listar.mock.calls.length;
    const agrupados = sellOutAPI.porPrograma.mock.calls.length;
    await user.selectOptions(select, '7');
    await user.click(within(dialogo).getByRole('button', { name: 'Asignar' }));

    expect(sellOutProgramasAPI.asignar).toHaveBeenCalledWith([55, 60], 7);
    expect(sellOutProgramasAPI.crear).not.toHaveBeenCalled();
    expect(await within(seccion).findByRole('status')).toHaveTextContent('1 campaña asignada a «MARCA PROG». 1 ya lo tenía.');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(within(seccion).getByRole('checkbox', { name: 'Seleccionar RB 8180' })).not.toBeChecked();
    await waitFor(() => expect(sellOutAPI.listar.mock.calls.length).toBeGreaterThan(listados));
    expect(sellOutAPI.porPrograma.mock.calls.length).toBe(agrupados); // the flat view asks no groups
  });

  it('"Programa nuevo" creates the program, then assigns the campaigns to it', async () => {
    conProgramas();
    sellOutProgramasAPI.crear.mockResolvedValue({ data: { ...PROGRAMAS_LISTA.items[0], id: 12, nombre: 'MODELOS SP', campanas: 0, activas: 0, nombres: 0 } });
    sellOutProgramasAPI.asignar.mockResolvedValue({ data: { asignadas: 1, sin_cambio: 0 } });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out&vista=lista'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    await user.click(await within(seccion).findByRole('checkbox', { name: 'Seleccionar RB 8180' }));
    await user.click(within(seccion).getByRole('button', { name: 'Asignar a programa' }));
    const dialogo = screen.getByRole('dialog', { name: 'Asignar a programa (1 campaña)' });
    await user.click(within(dialogo).getByRole('radio', { name: 'Programa nuevo' }));
    await user.type(within(dialogo).getByLabelText('Nombre'), '  MODELOS SP ');
    await user.type(within(dialogo).getByLabelText('Descripción (opcional)'), 'Modelos de la marca');
    await user.click(within(dialogo).getByRole('button', { name: 'Asignar' }));

    await waitFor(() => expect(sellOutProgramasAPI.asignar).toHaveBeenCalledWith([55], 12));
    expect(sellOutProgramasAPI.crear).toHaveBeenCalledWith({ nombre: 'MODELOS SP', descripcion: 'Modelos de la marca' });
    expect(sellOutProgramasAPI.crear.mock.invocationCallOrder[0]).toBeLessThan(sellOutProgramasAPI.asignar.mock.invocationCallOrder[0]);
    expect(await within(seccion).findByRole('status')).toHaveTextContent('1 campaña asignada a «MODELOS SP».');
  });

  it('the API refusal (an archived program) shows inline in the dialog, which stays open', async () => {
    conProgramas();
    sellOutProgramasAPI.asignar.mockRejectedValue({
      response: { status: 422, data: { error: { message: 'El programa «MARCA PROG» está archivado.' } } },
    });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out&vista=lista'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    await user.click(await within(seccion).findByRole('checkbox', { name: 'Seleccionar RB 8180' }));
    await user.click(within(seccion).getByRole('button', { name: 'Asignar a programa' }));
    const dialogo = screen.getByRole('dialog', { name: 'Asignar a programa (1 campaña)' });
    await user.selectOptions(within(dialogo).getByLabelText('Programa'), '7');
    await user.click(within(dialogo).getByRole('button', { name: 'Asignar' }));

    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('El programa «MARCA PROG» está archivado.');
    expect(within(seccion).getByRole('checkbox', { name: 'Seleccionar RB 8180' })).toBeChecked();
  });

  it('a row\'s "Renovar" opens the new-campaign form prefilled with the renewal draft', async () => {
    sellOutAPI.renovacion.mockResolvedValue({ data: RENOVACION_MIGRADA });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    const fila = (await within(seccion).findByText('RB 8180')).closest('tr');
    await user.click(within(fila).getByRole('button', { name: 'Renovar' }));

    await waitFor(() => expect(sellOutAPI.renovacion).toHaveBeenCalledWith(55));
    expect(await screen.findByText('Copia de «RB 8180». Revisá fechas y montos antes de guardar.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Guardar campaña' })).toBeInTheDocument();
    expect(sellOutAPI.crear).not.toHaveBeenCalled();
  });

  it('a grouped row has "Renovar" too', async () => {
    conProgramas();
    sellOutAPI.listar.mockImplementation(async (p) => ({ data: p.programa_id === 7 ? CAMPANAS_DEL_PROGRAMA : CAMPANAS_LISTA }));
    sellOutAPI.renovacion.mockResolvedValue({ data: RENOVACION_MIGRADA });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await user.click(await waitFor(() => screen.getByRole('button', { name: /^MARCA PROG/ })));
    const fila = (await screen.findByText('MARCA PROG 3.0')).closest('tr');
    await user.click(within(fila).getByRole('button', { name: 'Renovar' }));
    await waitFor(() => expect(sellOutAPI.renovacion).toHaveBeenCalledWith(71));
  });

  it('without sell_out.gestionar the rows have no "Renovar"', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'sell_out.gestionar');
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const fila = (await screen.findByText('RB 8180')).closest('tr');
    expect(within(fila).getByRole('button', { name: 'Ver campaña' })).toBeInTheDocument();
    expect(within(fila).queryByRole('button', { name: 'Renovar' })).not.toBeInTheDocument();
  });

  it('a renewal saved from a grouped row shows up in its group, and the groups are read again', async () => {
    conProgramas();
    const NUEVA = { ...CAMPANAS_DEL_PROGRAMA.items[0], id: 96, nombre: 'MARCA PROG 3.0 Q1', fecha_desde: '2027-01-01', fecha_hasta: '2027-03-31' };
    let guardada = false;
    sellOutAPI.listar.mockImplementation(async (p) => {
      if (p.programa_id !== 7) return { data: CAMPANAS_LISTA };
      const items = guardada ? [NUEVA, ...CAMPANAS_DEL_PROGRAMA.items] : CAMPANAS_DEL_PROGRAMA.items;
      return { data: { ...CAMPANAS_DEL_PROGRAMA, items, total: items.length } };
    });
    sellOutAPI.renovacion.mockResolvedValue({ data: RENOVACION_MIGRADA });
    sellOutAPI.crear.mockImplementation(async () => {
      guardada = true;
      return { data: NUEVA };
    });
    sellOutAPI.detalle.mockImplementation(async (id) => ({ data: id === 96 ? NUEVA : CAMPANAS_DEL_PROGRAMA.items[0] }));
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await user.click(await waitFor(() => screen.getByRole('button', { name: /^MARCA PROG/ })));
    const fila = (await screen.findByText('MARCA PROG 3.0')).closest('tr');
    await user.click(within(fila).getByRole('button', { name: 'Renovar' }));
    await screen.findByText(/Copia de/);
    const agrupados = sellOutAPI.porPrograma.mock.calls.length;
    await user.click(screen.getByRole('button', { name: 'Guardar campaña' }));

    const seccion = screen.getByRole('region', { name: 'Campañas de sell out' });
    expect(await within(seccion).findByText('MARCA PROG 3.0 Q1')).toBeInTheDocument();
    expect(sellOutAPI.porPrograma.mock.calls.length).toBeGreaterThan(agrupados);
  });

  it('"Actualizar" reads the program groups again', async () => {
    conProgramas();
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await waitFor(() => filaDeGrupo('MARCA PROG'));
    const agrupados = sellOutAPI.porPrograma.mock.calls.length;
    await user.click(screen.getByRole('button', { name: /Actualizar/ }));
    await waitFor(() => expect(sellOutAPI.porPrograma.mock.calls.length).toBeGreaterThan(agrupados));
  });

  it('more than 500 campaigns cannot be assigned at once, and no program is created for them', async () => {
    conProgramas();
    const TOTAL = 501;
    sellOutAPI.listar.mockImplementation(async ({ page, page_size: size }) => {
      const desde = (page - 1) * size;
      const items = Array.from({ length: Math.max(0, Math.min(size, TOTAL - desde)) }, (_, i) => ({
        ...CAMPANA_MIGRADA,
        id: 1000 + desde + i,
        nombre: `MODELO ${desde + i}`,
      }));
      return { data: { items, total: TOTAL, page, page_size: size } };
    });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out&vista=lista'] });
    await user.click(await screen.findByRole('button', { name: `Seleccionar todo lo filtrado (${TOTAL})` }));
    await user.click(await screen.findByRole('button', { name: 'Asignar a programa' }));
    const dialogo = screen.getByRole('dialog', { name: `Asignar a programa (${TOTAL} campañas)` });
    expect(dialogo).toHaveTextContent('Se pueden asignar hasta 500 campañas por vez.');
    await user.selectOptions(within(dialogo).getByLabelText('Programa'), '7');
    expect(within(dialogo).getByRole('button', { name: 'Asignar' })).toBeDisabled();
    await user.click(within(dialogo).getByRole('radio', { name: 'Programa nuevo' }));
    await user.type(within(dialogo).getByLabelText('Nombre'), 'MARCA PROG 2');
    expect(within(dialogo).getByRole('button', { name: 'Asignar' })).toBeDisabled();
    expect(sellOutProgramasAPI.crear).not.toHaveBeenCalled();
  });

  it('a program created whose assignment then fails is offered at once, and a retry does not create it again', async () => {
    const NUEVO = { ...PROGRAMAS_LISTA.items[0], id: 12, nombre: 'MODELOS SP', campanas: 0, activas: 0, nombres: 0 };
    let creado = false;
    sellOutProgramasAPI.listar.mockImplementation(async () => ({
      data: { ...PROGRAMAS_LISTA, items: creado ? [...PROGRAMAS_LISTA.items, NUEVO] : PROGRAMAS_LISTA.items },
    }));
    sellOutProgramasAPI.crear.mockImplementation(async () => {
      creado = true;
      return { data: NUEVO };
    });
    sellOutProgramasAPI.asignar.mockRejectedValue({ response: { status: 422, data: { error: { message: 'La campaña 55 no existe.' } } } });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out&vista=lista'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    await user.click(await within(seccion).findByRole('checkbox', { name: 'Seleccionar RB 8180' }));
    await user.click(within(seccion).getByRole('button', { name: 'Asignar a programa' }));
    const dialogo = screen.getByRole('dialog', { name: 'Asignar a programa (1 campaña)' });
    await user.click(within(dialogo).getByRole('radio', { name: 'Programa nuevo' }));
    await user.type(within(dialogo).getByLabelText('Nombre'), 'MODELOS SP');
    await user.click(within(dialogo).getByRole('button', { name: 'Asignar' }));
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('La campaña 55 no existe.');

    const filtros = screen.getByRole('region', { name: 'Filtros de campañas' });
    await waitFor(() => expect(within(within(filtros).getByLabelText('Programa')).getByRole('option', { name: 'MODELOS SP' })).toBeInTheDocument());
    await user.click(within(dialogo).getByRole('button', { name: 'Cancelar' }));
    await user.click(within(seccion).getByRole('button', { name: 'Asignar a programa' }));
    const otra = screen.getByRole('dialog', { name: 'Asignar a programa (1 campaña)' });
    await user.selectOptions(within(otra).getByLabelText('Programa'), '12');
    await user.click(within(otra).getByRole('button', { name: 'Asignar' }));
    await waitFor(() => expect(sellOutProgramasAPI.asignar).toHaveBeenCalledTimes(2));
    expect(sellOutProgramasAPI.asignar).toHaveBeenLastCalledWith([55], 12);
    expect(sellOutProgramasAPI.crear).toHaveBeenCalledTimes(1);
  });

  it('when a reload leaves the page of groups past the end, it goes to the last page that has groups', async () => {
    conProgramas();
    const grupo = (i) => ({ ...GRUPOS_POR_PROGRAMA.items[0], programa_id: 100 + i, nombre: `MARCA PROG ${String(i).padStart(2, '0')}` });
    let total = 51;
    sellOutAPI.porPrograma.mockImplementation(async ({ page, page_size: size }) => {
      const desde = (page - 1) * size;
      const items = Array.from({ length: Math.max(0, Math.min(size, total - desde)) }, (_, i) => grupo(desde + i));
      return { data: { items, total, page, page_size: size, sin_programa: null } };
    });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await user.click(await screen.findByRole('button', { name: 'Página 2' }));
    expect(await screen.findByRole('button', { name: 'MARCA PROG 50' })).toBeInTheDocument();

    total = 50; // its only program's campaigns were moved elsewhere
    await user.click(screen.getByRole('button', { name: /Actualizar/ }));
    expect(await screen.findByRole('button', { name: 'MARCA PROG 49' })).toBeInTheDocument();
    expect(lastParams(sellOutAPI.porPrograma)).toEqual({ page: 1, page_size: 50 });
  });

  it('the assign dialog takes the focus, keeps Tab inside and gives it back to "Asignar a programa" on close', async () => {
    conProgramas();
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out&vista=lista'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    await user.click(await within(seccion).findByRole('checkbox', { name: 'Seleccionar RB 8180' }));
    const abrir = within(seccion).getByRole('button', { name: 'Asignar a programa' });
    await user.click(abrir);
    const dialogo = screen.getByRole('dialog', { name: 'Asignar a programa (1 campaña)' });
    await waitFor(() => expect(dialogo).toContainElement(document.activeElement));
    for (let i = 0; i < 8; i += 1) {
      await user.tab();
      expect(dialogo).toContainElement(document.activeElement);
    }
    await user.tab({ shift: true });
    expect(dialogo).toContainElement(document.activeElement);
    await user.click(within(dialogo).getByRole('button', { name: 'Cancelar' }));
    expect(abrir).toHaveFocus();
  });

  it('the Programa filter and the dialog offer every program, past the first page of 200', async () => {
    const programa = (i) => ({ ...PROGRAMAS_LISTA.items[0], id: 1000 + i, nombre: `MARCA PROG ${String(i).padStart(3, '0')}` });
    sellOutProgramasAPI.listar.mockImplementation(async ({ page, page_size: size }) => {
      const desde = (page - 1) * size;
      const items = Array.from({ length: Math.max(0, Math.min(size, 201 - desde)) }, (_, i) => programa(desde + i));
      return { data: { items, total: 201, page, page_size: size } };
    });
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out&vista=lista'] });
    const filtros = await screen.findByRole('region', { name: 'Filtros de campañas' });
    const select = await within(filtros).findByLabelText('Programa');
    await waitFor(() => expect(within(select).getByRole('option', { name: 'MARCA PROG 200' })).toBeInTheDocument());
    expect(sellOutProgramasAPI.listar).toHaveBeenLastCalledWith({ page: 2, page_size: 200 });
  });

  it('assigning the last page of "Sin programa" moves the list to the last page that still has campaigns', async () => {
    conProgramas();
    let total = 13;
    sellOutAPI.listar.mockImplementation(async ({ page, page_size: size }) => {
      const desde = (page - 1) * size;
      const items = Array.from({ length: Math.max(0, Math.min(size, total - desde)) }, (_, i) => ({
        ...CAMPANA_MIGRADA,
        id: 500 + desde + i,
        nombre: `MODELO ${8180 + desde + i}`,
      }));
      return { data: { items, total, page, page_size: size } };
    });
    sellOutProgramasAPI.asignar.mockImplementation(async (ids) => {
      total -= ids.length;
      return { data: { asignadas: ids.length, sin_cambio: 0 } };
    });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out&vista=lista'] });
    const filtros = await screen.findByRole('region', { name: 'Filtros de campañas' });
    await user.selectOptions(await within(filtros).findByLabelText('Programa'), 'sin');
    const seccion = screen.getByRole('region', { name: 'Campañas de sell out' });
    await user.click(await within(seccion).findByRole('button', { name: 'Página 2' }));
    await user.click(await within(seccion).findByRole('checkbox', { name: 'Seleccionar la página' }));
    expect(within(seccion).getByText('3 seleccionadas')).toBeInTheDocument();
    await user.click(within(seccion).getByRole('button', { name: 'Asignar a programa' }));
    const dialogo = screen.getByRole('dialog', { name: 'Asignar a programa (3 campañas)' });
    await user.selectOptions(within(dialogo).getByLabelText('Programa'), '7');
    await user.click(within(dialogo).getByRole('button', { name: 'Asignar' }));

    expect(await within(seccion).findByText('MODELO 8180')).toBeInTheDocument();
    expect(within(seccion).queryByText('No hay campañas de sell out.')).not.toBeInTheDocument();
    expect(lastParams(sellOutAPI.listar)).toEqual({ sin_programa: true, page: 1, page_size: 10 });
  });

  it('when the opener is gone after assigning, the focus goes to the campaigns heading, not the page body', async () => {
    conProgramas();
    sellOutProgramasAPI.asignar.mockResolvedValue({ data: { asignadas: 1, sin_cambio: 0 } });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out&vista=lista'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    await user.click(await within(seccion).findByRole('checkbox', { name: 'Seleccionar RB 8180' }));
    await user.click(within(seccion).getByRole('button', { name: 'Asignar a programa' }));
    const dialogo = screen.getByRole('dialog', { name: 'Asignar a programa (1 campaña)' });
    await user.selectOptions(within(dialogo).getByLabelText('Programa'), '7');
    await user.click(within(dialogo).getByRole('button', { name: 'Asignar' }));

    await within(seccion).findByRole('status');
    expect(within(seccion).queryByRole('button', { name: 'Asignar a programa' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Campañas de sell out' })).toHaveFocus();
  });

  it('without sell_out.gestionar there is no "Asignar a programa"', async () => {
    conProgramas();
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'sell_out.gestionar');
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out&vista=lista'] });
    await screen.findByText('RB 8180');
    expect(screen.queryByRole('button', { name: 'Asignar a programa' })).not.toBeInTheDocument();
  });
});

describe('SellIn page — program suggestions (campanas-sistema slice E)', () => {
  const BANNER = '2 sugerencias de programa: campañas sin programa con las mismas fechas';
  const tarjeta = (desde, hasta) => screen.getByRole('group', { name: `Sugerencia del ${desde} al ${hasta}` });

  it('the banner shows with sell_out.gestionar and suggestions, and not without either', async () => {
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS });
    const { unmount } = renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    expect(await screen.findByText(BANNER)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ver sugerencias' })).toBeInTheDocument();
    expect(lastParams(sellOutProgramasAPI.sugerencias)).toEqual({ page: 1, page_size: 200 });
    unmount();

    vi.clearAllMocks();
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'sell_out.gestionar');
    const lector = renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await screen.findByText('RB 8180');
    expect(screen.queryByText(BANNER)).not.toBeInTheDocument();
    expect(sellOutProgramasAPI.sugerencias).not.toHaveBeenCalled();
    lector.unmount();

    mockTienePermiso.mockReturnValue(true);
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS_VACIO });
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await waitFor(() => expect(sellOutProgramasAPI.sugerencias).toHaveBeenCalled());
    await screen.findByText('RB 8180');
    expect(screen.queryByText(/sugerencias? de programa/)).not.toBeInTheDocument();
  });

  it('"Crear programa y asignar" creates the program with the edited name, assigns its campaigns and refreshes', async () => {
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS });
    sellOutProgramasAPI.crear
      .mockRejectedValueOnce({ response: { status: 409, data: { error: { message: 'Ya existe un programa llamado «MARCA».' } } } })
      .mockResolvedValueOnce({ data: { id: 15, nombre: 'MARCA PROG', descripcion: null, estado: 'activo', campanas: 0, activas: 0, desde: null, hasta: null, nombres: 0 } });
    sellOutProgramasAPI.asignar.mockResolvedValue({ data: { asignadas: 3, sin_cambio: 0 } });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await user.click(await screen.findByRole('button', { name: 'Ver sugerencias' }));

    const drawer = screen.getByRole('dialog', { name: 'Sugerencias de programa' });
    expect(drawer).toHaveTextContent('Las sugerencias agrupan campañas sin programa con exactamente las mismas fechas. No se aplica nada hasta que lo confirmes.');
    expect(within(drawer).getAllByRole('textbox', { name: 'Nombre del programa' }).map((i) => i.value)).toEqual([
      'MARCA',
      'Del 01/11/2025 al 31/10/2026',
    ]);
    const primera = tarjeta('01/08/2026', '31/10/2026');
    expect(primera).toHaveTextContent('01/08/2026 – 31/10/2026 · 3 campañas · 2 nombres');
    expect(primera).toHaveTextContent('2 activas');
    await user.click(within(primera).getByRole('button', { name: 'Ver campañas' }));
    expect(within(primera).getByText('MARCA PROGRAM1 (×2)').closest('li')).toHaveTextContent('Activa');
    expect(within(primera).getByText('MARCA PROG 3.0').closest('li')).toHaveTextContent('Anulada');

    await user.click(within(primera).getByRole('button', { name: 'Crear programa y asignar' }));
    expect(await within(primera).findByRole('alert')).toHaveTextContent('Ya existe un programa llamado «MARCA».');
    expect(sellOutProgramasAPI.asignar).not.toHaveBeenCalled();

    const nombre = within(primera).getByRole('textbox', { name: 'Nombre del programa' });
    await user.clear(nombre);
    await user.type(nombre, 'MARCA PROG');
    const sugerencias = sellOutProgramasAPI.sugerencias.mock.calls.length;
    const programas = sellOutProgramasAPI.listar.mock.calls.length;
    await user.click(within(primera).getByRole('button', { name: 'Crear programa y asignar' }));

    await waitFor(() => expect(sellOutProgramasAPI.asignar).toHaveBeenCalledWith([81, 82, 83], 15));
    expect(sellOutProgramasAPI.crear).toHaveBeenLastCalledWith({ nombre: 'MARCA PROG' });
    expect(await within(drawer).findByRole('status')).toHaveTextContent('3 campañas asignadas a «MARCA PROG».');
    await waitFor(() => expect(sellOutProgramasAPI.sugerencias.mock.calls.length).toBeGreaterThan(sugerencias));
    expect(sellOutProgramasAPI.listar.mock.calls.length).toBeGreaterThan(programas);
  });

  it('when the assignment fails after the create, a retry only assigns, and the new program is read at once', async () => {
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS });
    sellOutProgramasAPI.crear.mockResolvedValue({ data: { id: 15, nombre: 'MARCA', descripcion: null, estado: 'activo', campanas: 0, activas: 0, desde: null, hasta: null, nombres: 0 } });
    sellOutProgramasAPI.asignar
      .mockRejectedValueOnce({ response: { status: 422, data: { error: { message: 'La campaña 83 no existe.' } } } })
      .mockResolvedValueOnce({ data: { asignadas: 3, sin_cambio: 0 } });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await user.click(await screen.findByRole('button', { name: 'Ver sugerencias' }));
    const primera = tarjeta('01/08/2026', '31/10/2026');
    const programas = sellOutProgramasAPI.listar.mock.calls.length;
    await user.click(within(primera).getByRole('button', { name: 'Crear programa y asignar' }));

    expect(await within(primera).findByRole('alert')).toHaveTextContent('La campaña 83 no existe.');
    await waitFor(() => expect(sellOutProgramasAPI.listar.mock.calls.length).toBeGreaterThan(programas));
    await user.click(within(primera).getByRole('button', { name: 'Crear programa y asignar' }));
    await waitFor(() => expect(sellOutProgramasAPI.asignar).toHaveBeenCalledTimes(2));
    expect(sellOutProgramasAPI.crear).toHaveBeenCalledTimes(1);
    expect(sellOutProgramasAPI.asignar).toHaveBeenLastCalledWith([81, 82, 83], 15);
  });

  it('the drawer takes the focus, keeps Tab inside and gives it back to "Ver sugerencias" on close', async () => {
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const abrir = await screen.findByRole('button', { name: 'Ver sugerencias' });
    await user.click(abrir);
    const drawer = screen.getByRole('dialog', { name: 'Sugerencias de programa' });
    await waitFor(() => expect(drawer).toContainElement(document.activeElement));
    for (let i = 0; i < 12; i += 1) {
      await user.tab();
      expect(drawer).toContainElement(document.activeElement);
    }
    await user.click(within(drawer).getByRole('button', { name: 'Cerrar sugerencias' }));
    expect(abrir).toHaveFocus();
  });

  it('a suggestion with more than 500 campaigns cannot be created and assigned at once', async () => {
    const grande = {
      ...SUGERENCIAS.items[0],
      campanas: Array.from({ length: 501 }, (_, i) => ({ ...SUGERENCIAS.items[0].campanas[0], id: 2000 + i })),
    };
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: { ...SUGERENCIAS, items: [grande], total: 1 } });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await user.click(await screen.findByRole('button', { name: 'Ver sugerencias' }));
    const card = tarjeta('01/08/2026', '31/10/2026');
    expect(card).toHaveTextContent('Se pueden asignar hasta 500 campañas por vez.');
    expect(within(card).getByRole('button', { name: 'Crear programa y asignar' })).toBeDisabled();
    expect(within(card).getByRole('button', { name: 'Descartar' })).toBeEnabled();
    expect(sellOutProgramasAPI.crear).not.toHaveBeenCalled();
  });

  it('when no suggestion is left, closing the drawer puts the focus on the campaigns heading', async () => {
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await user.click(await screen.findByRole('button', { name: 'Ver sugerencias' }));
    const drawer = screen.getByRole('dialog', { name: 'Sugerencias de programa' });
    await user.click(within(tarjeta('01/08/2026', '31/10/2026')).getByRole('button', { name: 'Descartar' }));
    await user.click(within(tarjeta('01/11/2025', '31/10/2026')).getByRole('button', { name: 'Descartar' }));
    expect(screen.queryByRole('button', { name: 'Ver sugerencias' })).not.toBeInTheDocument();
    await user.click(within(drawer).getByRole('button', { name: 'Cerrar sugerencias' }));
    expect(screen.getByRole('heading', { name: 'Campañas de sell out' })).toHaveFocus();
  });

  it('"Descartar" hides that card only, for this session, and writes nothing', async () => {
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await user.click(await screen.findByRole('button', { name: 'Ver sugerencias' }));
    await user.click(within(tarjeta('01/08/2026', '31/10/2026')).getByRole('button', { name: 'Descartar' }));

    expect(screen.queryByRole('group', { name: 'Sugerencia del 01/08/2026 al 31/10/2026' })).not.toBeInTheDocument();
    expect(tarjeta('01/11/2025', '31/10/2026')).toBeInTheDocument();
    expect(screen.getByText('1 sugerencia de programa: campañas sin programa con las mismas fechas')).toBeInTheDocument();
    expect(sellOutProgramasAPI.crear).not.toHaveBeenCalled();
    expect(sellOutProgramasAPI.asignar).not.toHaveBeenCalled();
  });
});
