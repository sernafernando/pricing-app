/**
 * Publicaciones ML: column order, the layout saved per user and view, and column presets (pubml-columnas-presets
 * S1, S2, S3, S6, S8). The server is `services/mlPublicationsPresets` (mocked); dnd-kit's gestures do not run in
 * jsdom, so a drag ends through the picker's own `onDragEnd` (captured per DndContext `id`), as a real one would.
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { act, screen, waitFor, within, render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import PublicacionesML from './PublicacionesML';
import { equiposAPI, publicacionesMlAPI } from '../services/api';
import { mlPublicationsPresetsAPI } from '../services/mlPublicationsPresets';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';
import {
  BRAND_NODES,
  FACETS,
  ITEMS_RESPONSE,
  KPIS_RESPONSE,
  VARIATIONS_RESPONSE,
  groupsResponse,
  productsResponse,
} from '../test/visual/publicacionesMlFixtures';

vi.mock('../services/mlPublicationsPresets', () => ({
  mlPublicationsPresetsAPI: {
    getLayout: vi.fn(),
    saveLayout: vi.fn(),
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
}));

const dragEnd = vi.hoisted(() => ({}));
vi.mock('@dnd-kit/core', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    DndContext: ({ id, onDragEnd, children }) => {
      dragEnd[id] = onDragEnd;
      return children;
    },
  };
});

vi.mock('../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    patch: vi.fn(() => Promise.resolve({ data: {} })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  productosPropiosAPI: { get: vi.fn(() => new Promise(() => {})), save: vi.fn() },
  // The publication panel opens on Promos (owner, 2026-11-02): its promotions never answer here, these tests are
  // about the panel's opening and closing.
  promocionesAPI: {
    getPromocionesItem: vi.fn(() => new Promise(() => {})),
    refreshItemPromociones: vi.fn(() => new Promise(() => {})),
    getCompetenciaCatalogo: vi.fn(() => new Promise(() => {})),
  },
  publicacionesMlAPI: { items: vi.fn(), products: vi.fn(), variations: vi.fn(), groups: vi.fn(), detail: vi.fn(), enqueue: vi.fn(), kpis: vi.fn(), productIds: vi.fn(), stats: vi.fn(), statusItemIds: vi.fn(), statusItemIdsChecked: vi.fn(), statusBulk: vi.fn(), paintColors: vi.fn() },
  productosAPI: {
    // The product panel's publication tree (Productos' `ProductoMLAsPanel`): the product's publication.
    getProductoTree: vi.fn(() =>
      Promise.resolve({
        data: {
          item_id: 4101,
          tree: { level: 0, kind: 'producto', label: 'Router Archer AX55', children: [{ level: 1, kind: 'publicacion', mla: 'MLA1100000001', label: 'Router Archer AX55', children: [] }] },
        },
      }),
    ),
    marcas: vi.fn(() => Promise.resolve({ data: { marcas: ['TP,LINK', 'EPSON'] } })),
    categorias: vi.fn(() => Promise.resolve({ data: { categorias: ['REDES'] } })),
    subcategorias: vi.fn(() => Promise.resolve({ data: { categorias: [] } })),
    pms: vi.fn(() => Promise.resolve({ data: [{ id: 7, nombre: 'Ana' }] })),
    // The product panel's last purchases: no purchase, these tests are about the panel's opening and closing.
    detalle: vi.fn(() => Promise.resolve({ data: { producto: {}, pricing: {}, ultimas_compras: [] } })),
    listar: vi.fn(() => Promise.resolve({ data: { productos: [], total: 0 } })),
  },
  equiposAPI: {
    listar: vi.fn(() =>
      Promise.resolve({ data: [{ id: 1, nombre: 'U', es_global: true }, { id: 12, nombre: 'Ventas', es_global: false }] }),
    ),
    misPreferencias: vi.fn(),
  },
  preciosAPI: {
    calcularMarkup: vi.fn(() => Promise.resolve({ data: { markup: 10 } })),
    setRapido: vi.fn(() => Promise.resolve({ data: {} })),
    setCuota: vi.fn(() => Promise.resolve({ data: {} })),
    setRebate: vi.fn(() => Promise.resolve({ data: {} })),
    setWebTransferencia: vi.fn(() => Promise.resolve({ data: {} })),
    setOutOfCards: vi.fn(() => Promise.resolve({ data: {} })),
    tipoCambioActual: vi.fn(() => Promise.resolve({ data: { venta: 1000 } })),
    // The panel's Precios tab (`ProductPrices`) reads the product on its own.
    obtenerProducto: vi.fn(() => Promise.resolve({ data: { item_id: 4101, codigo: 'ARCHER-AX55', descripcion: 'Router Archer AX55' } })),
  },
  // No current offset unless a test says so: Productos' "markup con offsets" stays out of the cells.
  offsetsGananciaAPI: { vigentes: vi.fn(() => Promise.resolve({ data: [] })), grupoFiltros: vi.fn(() => Promise.resolve({ data: [] })) },
  registerAuthFailureHandler: vi.fn(),
}));

// jsdom lays nothing out: a test that needs the end of a long list in view says so (`virtualView.all`), and the
// virtualizer then shows every row; otherwise it is the real one.
const virtualView = vi.hoisted(() => ({ all: false }));
vi.mock('@tanstack/react-virtual', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    useVirtualizer: (options) => {
      const real = actual.useVirtualizer(options);
      if (!virtualView.all) return real;
      const items = Array.from({ length: options.count }, (_, index) => ({
        index,
        key: options.getItemKey(index),
        start: index * 56,
        end: (index + 1) * 56,
      }));
      return Object.assign(Object.create(real), {
        getVirtualItems: () => items,
        getTotalSize: () => options.count * 56,
        measureElement: () => {},
      });
    },
  };
});

// Team management has its own tests; here only that the page opens it and reloads its teams after.
vi.mock('../components/EquiposModal', () => ({
  default: ({ isOpen, onClose }) =>
    isOpen ? (
      <div role="dialog" aria-label="Gestión de equipos">
        <button type="button" onClick={onClose}>
          Cerrar equipos
        </button>
      </div>
    ) : null,
}));

// The color events (`producto_color:changed`, and a publication's own `publicacion_color:changed`) are pushed by
// each test through the captured listeners.
const sse = { listener: null, own: null };
vi.mock('../hooks/useSSEChannel', () => ({
  useSSEChannel: (channel, callback) => {
    if (channel === 'producto_color:changed') sse.listener = callback;
    if (channel === 'publicacion_color:changed') sse.own = callback;
  },
}));

vi.mock('../utils/mlSidePanel', async (importOriginal) => ({
  ...(await importOriginal()),
  openInMlPanel: vi.fn(),
}));

vi.mock('../utils/publicacionesMlExport', async (importOriginal) => ({
  ...(await importOriginal()),
  exportPublicacionesCsv: vi.fn(),
  exportPublicacionesSheets: vi.fn(),
}));
vi.mock('../utils/googleSheetsExport', async (importOriginal) => ({
  ...(await importOriginal()),
  loadGoogleIdentity: vi.fn(() => Promise.resolve(true)),
}));

// Everything is allowed except the margin, which each test grants on purpose.
let canSeeMargin = false;
let canSeeKpis = true;
// Productos' prices (S11): `productos.ver` or a price-edit code (`canViewProductPrices`).
let canSeePrices = true;
// Writing them (S11c): the Productos and Tienda edit codes (`pricePermissions`).
let canEditPrices = true;
let denied = new Set();
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (permiso) => {
      if (denied.has(permiso)) return false;
      if (permiso === 'ml_metricas.ver_ganancia') return canSeeMargin;
      if (permiso === 'ml_metricas.ver') return canSeeKpis;
      if (/^(productos\.(editar|toggle)|tienda\.editar)/.test(permiso)) return canSeePrices && canEditPrices;
      if (permiso.startsWith('productos.') || permiso.startsWith('tienda.')) return canSeePrices;
      return true;
    },
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const itemsCalls = () => publicacionesMlAPI.items.mock.calls.map(([params]) => params);
const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });

let location;
function LocationProbe() {
  location = useLocation();
  return null;
}
const urlParams = () => Object.fromEntries(new URLSearchParams(location.search));

const page = async (entry = '/ml-publicaciones') => {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <PublicacionesML />
      <LocationProbe />
    </MemoryRouter>,
  );
  await screen.findAllByRole('columnheader');
};

// The table's columns, left to right, by their keys: the first body row's cells (`data-column`). The header rows
// are no good for this: a group's columns sit in a second header row.
const order = () => {
  const row = screen.getByRole('table').querySelector('tbody tr td[data-column]')?.closest('tr');
  return row ? [...row.querySelectorAll('td[data-column]')].map((cell) => cell.getAttribute('data-column')) : [];
};
const before = (a, b) => {
  const keys = order();
  return keys.includes(a) && keys.includes(b) && keys.indexOf(a) < keys.indexOf(b);
};

const openPicker = () => userEvent.click(screen.getByRole('button', { name: /Columnas/ }));
const presetButton = () => screen.getByRole('button', { name: /^Preset:/ });
const openPresets = () => userEvent.click(presetButton());
const lastSave = () => mlPublicationsPresetsAPI.saveLayout.mock.calls.at(-1);

const SHARED = {
  id: 5,
  vista: 'publicacion',
  nombre: 'Pausadas por precio',
  compartido: true,
  editable: true,
  updated_at: '2026-11-18T10:00:00Z',
  payload: {
    columns: { visibility: { tienda: true }, order: ['titulo', 'tienda', 'tipo'] },
    params: { estado: 'paused', orden: 'precio', dir: 'asc', modo: 'cuotas', equipo: '12' },
  },
};
const OTHERS_SHARED = { ...SHARED, id: 6, nombre: 'Del equipo', editable: false, payload: { columns: { visibility: {}, order: [] }, params: { tipo: 'premium' } } };
const PERSONAL = { ...SHARED, id: 9, nombre: 'Mío', compartido: false, payload: { columns: { visibility: {}, order: [] }, params: { estado: 'active' } } };

beforeEach(() => {
  denied = new Set();
  location = null;
  Object.keys(dragEnd).forEach((key) => delete dragEnd[key]);
  seedTiendasOficiales([{ store_id: 471846, nombre: 'TP-Link', clave: null, orden: 0, activa: true }]);
  publicacionesMlAPI.items.mockReset();
  publicacionesMlAPI.items.mockResolvedValue({ data: { ...ITEMS_RESPONSE, facets: FACETS } });
  publicacionesMlAPI.kpis.mockResolvedValue({ data: KPIS_RESPONSE });
  publicacionesMlAPI.stats.mockResolvedValue({ data: { stats: {}, can_see_margin: false } });
  publicacionesMlAPI.variations.mockResolvedValue({ data: VARIATIONS_RESPONSE });
  publicacionesMlAPI.groups.mockResolvedValue({ data: groupsResponse('marca', BRAND_NODES) });
  publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse() });
  publicacionesMlAPI.productIds.mockResolvedValue({ data: { item_ids: [4101, 4102], count: 2, sin_producto: 1 } });
  equiposAPI.listar.mockResolvedValue({
    data: [
      { id: 1, nombre: 'U', es_global: true },
      { id: 12, nombre: 'Ventas', es_global: false },
      { id: 13, nombre: 'Compras', es_global: false },
    ],
  });
  Object.values(mlPublicationsPresetsAPI).forEach((fn) => fn.mockReset());
  mlPublicationsPresetsAPI.getLayout.mockResolvedValue({ columns: null, preset_activo_id: null });
  mlPublicationsPresetsAPI.saveLayout.mockImplementation((vista, body) => Promise.resolve(body));
  mlPublicationsPresetsAPI.list.mockResolvedValue([SHARED, OTHERS_SHARED, PERSONAL]);
  mlPublicationsPresetsAPI.create.mockImplementation((body) =>
    Promise.resolve({ id: 30, editable: true, updated_at: '2026-11-18T11:00:00Z', ...body }),
  );
  mlPublicationsPresetsAPI.update.mockImplementation((id, body) =>
    Promise.resolve({ ...[SHARED, OTHERS_SHARED, PERSONAL].find((preset) => preset.id === id), ...body }),
  );
  mlPublicationsPresetsAPI.remove.mockResolvedValue(undefined);
});

afterAll(resetTiendasOficiales);

describe('S2: the layout of each view is kept per user on the server', () => {
  it('asks the layout of the view on entry and shows it: visibility and order', async () => {
    mlPublicationsPresetsAPI.getLayout.mockResolvedValue({
      columns: { visibility: { tienda: true, ya_no_existe: false }, order: ['titulo', 'tienda', 'ya_no_existe', 'tipo'] },
      preset_activo_id: null,
    });
    await page();
    expect(mlPublicationsPresetsAPI.getLayout).toHaveBeenCalledWith('publicacion');
    await waitFor(() => expect(before('tienda', 'tipo')).toBe(true));
    // A column the save does not know keeps its default place: Precio still follows Estado.
    expect(before('estado', 'precio')).toBe(true);
  });

  it('a picker toggle is saved for the view (visibility and order, no preset)', async () => {
    await page();
    await openPicker();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Tienda' }));
    expect(screen.getByRole('columnheader', { name: 'Tienda' })).toBeInTheDocument();
    await waitFor(() => expect(mlPublicationsPresetsAPI.saveLayout).toHaveBeenCalled(), { timeout: 2000 });
    const [vista, body] = lastSave();
    expect(vista).toBe('publicacion');
    expect(body.preset_activo_id).toBeNull();
    expect(body.columns.visibility).toMatchObject({ tienda: true, vinculo: false, titulo: true });
    expect(body.columns.order[0]).toBe('titulo');
  });

  it('Restablecer saves nulls and brings the defaults back', async () => {
    mlPublicationsPresetsAPI.getLayout.mockResolvedValue({ columns: { visibility: { tienda: true }, order: ['titulo', 'tienda'] }, preset_activo_id: null });
    await page();
    await waitFor(() => expect(screen.getByRole('columnheader', { name: 'Tienda' })).toBeInTheDocument());
    await openPicker();
    await userEvent.click(screen.getByRole('button', { name: 'Restablecer' }));
    expect(mlPublicationsPresetsAPI.saveLayout).toHaveBeenCalledWith('publicacion', { columns: null, preset_activo_id: null });
    expect(screen.queryByRole('columnheader', { name: 'Tienda' })).not.toBeInTheDocument();
  });
});

describe('S1: dragging in the picker reorders the table, in every view', () => {
  it.each([
    ['publicacion', '/ml-publicaciones'],
    ['precios', '/ml-publicaciones?vista=precios'],
    ['producto', '/ml-publicaciones?vista=producto'],
    ['agrupado', '/ml-publicaciones?vista=agrupado'],
  ])('%s: a group dropped before Tipo moves as a block, and the order is saved for that view', async (vista, entry) => {
    await page(entry);
    await waitFor(() => expect(mlPublicationsPresetsAPI.getLayout).toHaveBeenCalledWith(vista));
    expect(before('tipo', 'stock_erp')).toBe(true);
    await openPicker();
    act(() => dragEnd['column-blocks']({ active: { id: 'group:Stock' }, over: { id: 'col:tipo' } }));
    await waitFor(() => expect(before('stock_erp', 'tipo')).toBe(true));
    expect(before('stock_erp', 'stock_full')).toBe(true);
    expect(before('stock_full', 'stock_total')).toBe(true);
    // The first column stays first.
    expect(order()[0]).toBe('titulo');
    await waitFor(() => expect(lastSave()?.[0]).toBe(vista), { timeout: 2000 });
    expect(lastSave()[1].columns.order.slice(0, 5)).toEqual(['titulo', 'stock_erp', 'stock_full', 'stock_total', 'tipo']);
  });

  it('a column moves only inside its group', async () => {
    await page();
    await openPicker();
    act(() => dragEnd['column-group-Stock']({ active: { id: 'stock_total' }, over: { id: 'stock_erp' } }));
    await waitFor(() => expect(before('stock_total', 'stock_erp')).toBe(true));
    act(() => dragEnd['column-group-Stock']({ active: { id: 'stock_total' }, over: { id: 'tipo' } }));
    expect(before('stock_total', 'stock_erp')).toBe(true);
    expect(before('tipo', 'stock_total')).toBe(true);
  });
});

describe('S3: presets', () => {
  it('lists Predeterminado, the shared ones and the personal ones of the view; Predeterminado is active at first', async () => {
    await page();
    await waitFor(() => expect(mlPublicationsPresetsAPI.list).toHaveBeenCalledWith('publicacion'));
    expect(presetButton()).toHaveAccessibleName('Preset: Predeterminado');
    await openPresets();
    const menu = screen.getByRole('dialog', { name: 'Presets' });
    expect(within(menu).getAllByRole('button', { name: /^Aplicar/ }).map((button) => button.textContent)).toEqual([
      // Shared first, then by name (the server's order).
      expect.stringContaining('Predeterminado'),
      expect.stringContaining('Del equipo'),
      expect.stringContaining('Pausadas por precio'),
      expect.stringContaining('Mío'),
    ]);
    // Only what the user may edit can be renamed or deleted; Predeterminado never.
    expect(within(menu).queryByRole('button', { name: 'Eliminar Predeterminado' })).not.toBeInTheDocument();
    expect(within(menu).queryByRole('button', { name: 'Eliminar Del equipo' })).not.toBeInTheDocument();
    expect(within(menu).getByRole('button', { name: 'Eliminar Mío' })).toBeInTheDocument();
    expect(within(menu).getByRole('button', { name: 'Renombrar Pausadas por precio' })).toBeInTheDocument();
  });

  it('applying one sets its columns, order, filters, sort, modo and layer at once (S8), and remembers it', async () => {
    await page();
    await openPresets();
    await userEvent.click(screen.getByRole('button', { name: 'Aplicar Pausadas por precio' }));
    await waitFor(() => expect(urlParams()).toEqual({ estado: 'paused', orden: 'precio', dir: 'asc', modo: 'cuotas', equipo: '12' }));
    await waitFor(() => expect(itemsCalls().at(-1)).toMatchObject({ estado: 'paused', orden: 'precio', dir: 'asc' }));
    expect(before('tienda', 'tipo')).toBe(true);
    expect(presetButton()).toHaveAccessibleName('Preset: Pausadas por precio');
    await waitFor(() => expect(lastSave()?.[1].preset_activo_id).toBe(5), { timeout: 2000 });
    expect(lastSave()[1].columns.order.slice(0, 3)).toEqual(['titulo', 'tienda', 'tipo']);
  });

  it('a change after applying marks it modificado; Guardar cambios overwrites it with the columns and params on screen', async () => {
    await page();
    await openPresets();
    await userEvent.click(screen.getByRole('button', { name: 'Aplicar Pausadas por precio' }));
    await waitFor(() => expect(presetButton()).toHaveAccessibleName('Preset: Pausadas por precio'));
    await openPicker();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Tienda' }));
    expect(presetButton()).toHaveAccessibleName('Preset: Pausadas por precio (modificado)');
    await openPresets();
    await userEvent.click(screen.getByRole('button', { name: 'Guardar cambios' }));
    await waitFor(() => expect(mlPublicationsPresetsAPI.update).toHaveBeenCalledTimes(1));
    const [id, body] = mlPublicationsPresetsAPI.update.mock.calls[0];
    expect(id).toBe(5);
    expect(body.payload.params).toEqual({ estado: 'paused', orden: 'precio', dir: 'asc', modo: 'cuotas', equipo: '12' });
    expect(body.payload.columns.visibility.tienda).toBe(false);
    expect(body.payload.columns.order[0]).toBe('titulo');
    await waitFor(() => expect(presetButton()).toHaveAccessibleName('Preset: Pausadas por precio'));
  });

  it('a filter change after applying also marks it modificado', async () => {
    await page();
    await openPresets();
    await userEvent.click(screen.getByRole('button', { name: 'Aplicar Mío' }));
    await waitFor(() => expect(presetButton()).toHaveAccessibleName('Preset: Mío'));
    await userEvent.click(within(screen.getByRole('group', { name: /Filtrar por estado/ })).getByRole('button', { name: /Pausadas/ }));
    await waitFor(() => expect(presetButton()).toHaveAccessibleName('Preset: Mío (modificado)'));
  });

  it('Guardar como nuevo: a name, personal or shared (with the permission), saved with what is on screen', async () => {
    await page('/ml-publicaciones?estado=active&modo=pvp');
    await openPresets();
    await userEvent.click(screen.getByRole('button', { name: 'Guardar como nuevo' }));
    await userEvent.type(screen.getByLabelText('Nombre'), '  Activas PVP ');
    await userEvent.click(screen.getByRole('radio', { name: 'Compartido' }));
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(mlPublicationsPresetsAPI.create).toHaveBeenCalledTimes(1));
    const body = mlPublicationsPresetsAPI.create.mock.calls[0][0];
    expect(body).toMatchObject({ vista: 'publicacion', nombre: 'Activas PVP', compartido: true, payload: { params: { estado: 'active', modo: 'pvp' } } });
    expect(body.payload.columns.order[0]).toBe('titulo');
    await waitFor(() => expect(presetButton()).toHaveAccessibleName('Preset: Activas PVP'));
    await waitFor(() => expect(lastSave()?.[1].preset_activo_id).toBe(30), { timeout: 2000 });
  });

  it('without ml_publicaciones.presets_compartidos there is no shared choice: it is personal', async () => {
    denied = new Set(['ml_publicaciones.presets_compartidos']);
    await page();
    await openPresets();
    await userEvent.click(screen.getByRole('button', { name: 'Guardar como nuevo' }));
    expect(screen.queryByRole('radio', { name: 'Compartido' })).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Nombre'), 'Solo mío');
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(mlPublicationsPresetsAPI.create).toHaveBeenCalledWith(expect.objectContaining({ nombre: 'Solo mío', compartido: false })));
  });

  it('a name already used (409) says so and keeps the dialog open', async () => {
    mlPublicationsPresetsAPI.create.mockRejectedValue(httpError(409));
    await page();
    await openPresets();
    await userEvent.click(screen.getByRole('button', { name: 'Guardar como nuevo' }));
    await userEvent.type(screen.getByLabelText('Nombre'), 'Mío');
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Ya existe un preset con ese nombre.');
    expect(screen.getByLabelText('Nombre')).toBeInTheDocument();
  });

  it('renames and deletes an editable preset', async () => {
    await page();
    await openPresets();
    await userEvent.click(screen.getByRole('button', { name: 'Renombrar Mío' }));
    const name = screen.getByLabelText('Nombre');
    await userEvent.clear(name);
    await userEvent.type(name, 'Mis activas');
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(mlPublicationsPresetsAPI.update).toHaveBeenCalledWith(9, { nombre: 'Mis activas' }));
    await openPresets();
    await userEvent.click(screen.getByRole('button', { name: 'Eliminar Pausadas por precio' }));
    await userEvent.click(screen.getByRole('button', { name: 'Eliminar' }));
    await waitFor(() => expect(mlPublicationsPresetsAPI.remove).toHaveBeenCalledWith(5));
    await openPresets();
    expect(screen.queryByRole('button', { name: 'Aplicar Pausadas por precio' })).not.toBeInTheDocument();
  });
});

describe('S6: the link against the remembered preset', () => {
  it('entering with no filters in the URL applies the remembered preset fully, before the rows are asked', async () => {
    mlPublicationsPresetsAPI.getLayout.mockResolvedValue({ columns: SHARED.payload.columns, preset_activo_id: 5 });
    await page();
    await waitFor(() => expect(urlParams()).toMatchObject({ estado: 'paused', orden: 'precio', modo: 'cuotas', equipo: '12' }));
    expect(itemsCalls()[0]).toMatchObject({ estado: 'paused', orden: 'precio', dir: 'asc' });
    expect(presetButton()).toHaveAccessibleName('Preset: Pausadas por precio');
  });

  it('a link with filters wins: its filters stay, the preset gives only its columns, marked modificado', async () => {
    mlPublicationsPresetsAPI.getLayout.mockResolvedValue({ columns: null, preset_activo_id: 5 });
    await page('/ml-publicaciones?estado=active');
    await waitFor(() => expect(presetButton()).toHaveAccessibleName('Preset: Pausadas por precio (modificado)'));
    expect(urlParams()).toMatchObject({ estado: 'active' });
    expect(urlParams()).not.toHaveProperty('orden');
    expect(itemsCalls().every((params) => params.estado === 'active')).toBe(true);
    expect(before('tienda', 'tipo')).toBe(true);
  });
});
