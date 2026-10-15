/**
 * Producto vinculado tab (publicaciones-ml-vista P13b.T3, S59.x): the product
 * the publication is linked to, its list prices and the link of each unit. The
 * cost is shown only with `ml_metricas.ver_ganancia`. With
 * `ml_publicaciones.vincular` each unit can be linked to a product by hand,
 * marked as having no product, or handed back to the automatic rule.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductoVinculadoTab from './ProductoVinculadoTab';
import { readDetail } from './detailModel';
import { publicacionesMlAPI } from '../../../services/api';
import { ITEM_LINK, PRODUCT, PRODUCT_COST, VARIATION_LINK, makeDetail } from '../../../test/visual/publicacionesMlFixtures';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  publicacionesMlAPI: {
    productLinks: vi.fn(),
    setProductLink: vi.fn(),
    setProductLinkNone: vi.fn(),
    revertProductLinkAuto: vi.fn(),
    searchProducts: vi.fn(),
  },
  registerAuthFailureHandler: vi.fn(),
}));

let granted = new Set();
vi.mock('../../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: (permiso) => granted.has(permiso), cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const LINKED = { product: { ...PRODUCT, ...PRODUCT_COST }, links: [ITEM_LINK, VARIATION_LINK] };

const renderTab = (overrides = LINKED, { canSeeMargin = false, onWritten = vi.fn() } = {}) => {
  const detail = readDetail(makeDetail(overrides), { canSeeMargin });
  return render(<ProductoVinculadoTab detail={detail} itemId={detail.itemId} canSeeMargin={canSeeMargin} onWritten={onWritten} />);
};

beforeEach(() => {
  granted = new Set();
  for (const fn of Object.values(publicacionesMlAPI)) fn.mockReset();
  publicacionesMlAPI.productLinks.mockResolvedValue({ data: { item_id: 'MLA1100000001', units: [] } });
});
const section = (name) => screen.getByRole('region', { name });
const valueOf = (name, label) => within(section(name)).getByText(label, { selector: 'dt' }).nextElementSibling;

describe('the linked product', () => {
  it('shows who the product is (S59.2: identity shows without the margin permission)', () => {
    renderTab();
    expect(valueOf('Producto', 'Código')).toHaveTextContent('ARCHER-AX55');
    expect(valueOf('Producto', 'Descripción')).toHaveTextContent('Router Archer AX55');
    expect(valueOf('Producto', 'Marca')).toHaveTextContent('TP-LINK');
    expect(valueOf('Producto', 'Categoría')).toHaveTextContent('ROUTERS');
    expect(valueOf('Producto', 'Subcategoría')).toHaveTextContent('Wi-Fi 6');
  });

  it('shows the product\'s ERP stock (depósito 1) apart from the ML stock, and "—" when unknown', () => {
    renderTab({ ...LINKED, product: { ...LINKED.product, stock: 12 } });
    expect(valueOf('Producto', 'Stock ERP (depósito 1)')).toHaveTextContent('12');
  });

  it('keeps a real ERP zero as 0 and an unknown ERP stock as "—"', () => {
    const { unmount } = renderTab({ ...LINKED, product: { ...LINKED.product, stock: 0 } });
    expect(valueOf('Producto', 'Stock ERP (depósito 1)')).toHaveTextContent('0');
    unmount();
    renderTab();
    expect(valueOf('Producto', 'Stock ERP (depósito 1)')).toHaveTextContent('—');
  });

  it('shows the list prices by name, and "—" for a list with no price', () => {
    renderTab();
    expect(valueOf('Precios de lista', 'Clásica')).toHaveTextContent('98.500,50');
    expect(valueOf('Precios de lista', '3 Cuotas')).toHaveTextContent('101.200,00');
    expect(valueOf('Precios de lista', '6 Cuotas')).toHaveTextContent('104.800,25');
    expect(valueOf('Precios de lista', '9 Cuotas')).toHaveTextContent('—');
    expect(valueOf('Precios de lista', '12 Cuotas')).toHaveTextContent('110.900,00');
  });

  it('names a list it does not know by its number', () => {
    renderTab({ ...LINKED, product: { ...LINKED.product, precios_lista: { 99: 10 } } });
    expect(valueOf('Precios de lista', 'Lista 99')).toHaveTextContent('10,00');
  });
});

describe('the cost (S59.2)', () => {
  it('is shown with ml_metricas.ver_ganancia', () => {
    renderTab(LINKED, { canSeeMargin: true });
    expect(valueOf('Costo', 'Costo')).toHaveTextContent('64.000,00 ARS');
    expect(valueOf('Costo', 'IVA')).toHaveTextContent('21%');
  });

  it('is not in the page at all without it, even when the payload carried it', () => {
    const { container } = renderTab(LINKED, { canSeeMargin: false });
    expect(screen.queryByRole('region', { name: 'Costo' })).not.toBeInTheDocument();
    expect(container.textContent).not.toMatch(/64\.000/);
    expect(container.textContent).not.toMatch(/IVA/);
  });
});

describe('the links of each unit', () => {
  it('lists the item level and each variation with its state and product', () => {
    renderTab();
    const units = within(section('Vínculos')).getAllByRole('listitem');
    expect(units).toHaveLength(2);
    expect(units[0]).toHaveTextContent('Publicación');
    expect(units[0]).toHaveTextContent('Automático');
    expect(units[0]).toHaveTextContent('ARCHER-AX55');
    expect(units[0]).toHaveTextContent('AX55-SKU');
    expect(units[1]).toHaveTextContent('Variación 9002');
    expect(units[1]).toHaveTextContent('Manual');
    expect(units[1]).toHaveTextContent('ARCHER-AX55-B');
    expect(units[1]).toHaveTextContent('Corregido a mano');
  });

  it('shows a unit without a product as such, with the suggestion if there is one', () => {
    renderTab({
      product: null,
      links: [{ ...ITEM_LINK, state: 'conflicto', match_status: 'conflict', producto_item_id: null, codigo: null, descripcion: null, marca: null, suggested_producto_item_id: 4107 }],
    });
    const unit = within(section('Vínculos')).getByRole('listitem');
    expect(unit).toHaveTextContent('Conflicto');
    expect(unit).toHaveTextContent('Sin producto vinculado');
    expect(unit).toHaveTextContent('Producto sugerido: 4107');
  });
});

describe('a publication without a linked product (S59.1)', () => {
  it('says so, and shows no empty product, prices or cost', () => {
    renderTab({ product: null, links: [] }, { canSeeMargin: true });
    expect(screen.getByText('Sin producto vinculado')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Producto' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Precios de lista' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Costo' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Vínculos' })).not.toBeInTheDocument();
  });
});

// ── Editing the links (ml_publicaciones.vincular) ─────────────────

const ITEM = 'MLA9';
const ref = (item_id, codigo, descripcion) => ({ item_id, codigo, descripcion });
const NO_SUGGESTION = { status: 'unmatched', producto_item_id: null, producto: null, candidates: [], candidate_count: 0, differs: false };
const apiLink = (overrides = {}) => ({
  source: 'sku_auto',
  match_status: 'linked',
  producto_item_id: 4101,
  producto: ref(4101, 'ARCHER-AX55', 'Router Archer AX55'),
  dangling: false,
  matched_sku: 'AX55-SKU',
  sku_field: 'seller_sku',
  linked_by: null,
  linked_at: '2026-09-01T10:00:00Z',
  note: null,
  evaluated_at: '2026-09-01T10:00:00Z',
  ...overrides,
});
const unit = (variation_id, link, suggestion = NO_SUGGESTION) => ({ variation_id, live: true, sku: 'AX55-SKU', sku_field: 'seller_sku', link, suggestion });
const CONFLICT_UNIT = unit(
  0,
  apiLink({ match_status: 'conflict', producto_item_id: null, producto: null }),
  { status: 'conflict', producto_item_id: null, producto: null, candidates: [ref(4107, 'AX55-A', 'Router A'), ref(4108, 'AX55-B', 'Router B')], candidate_count: 2, differs: false },
);
const CONFLICT_LINK = { ...ITEM_LINK, state: 'conflicto', source: 'sku_auto', match_status: 'conflict', producto_item_id: null, codigo: null, descripcion: null, marca: null };
const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data: { detail: `detail ${status}` } } });

const renderEditable = ({ links = [ITEM_LINK], units = [unit(0, apiLink())], onWritten = vi.fn() } = {}) => {
  granted = new Set(['ml_publicaciones.vincular']);
  publicacionesMlAPI.productLinks.mockResolvedValue({ data: { item_id: ITEM, units } });
  const detail = readDetail(makeDetail({ product: null, links }));
  render(<ProductoVinculadoTab detail={detail} itemId={ITEM} canSeeMargin={false} onWritten={onWritten} />);
  return { onWritten };
};
const cardOf = async (title) => {
  const units = await within(await screen.findByRole('region', { name: 'Vínculos' })).findAllByRole('listitem');
  return units.find((el) => within(el).queryByText(title, { exact: true }));
};
const written = { data: { changed: true, unit: unit(0, apiLink()) } };

describe('editing the links: who may', () => {
  it('offers no action and loads nothing without ml_publicaciones.vincular', () => {
    renderTab();
    expect(screen.queryByRole('button', { name: 'Vincular producto' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Marcar sin producto' })).not.toBeInTheDocument();
    expect(publicacionesMlAPI.productLinks).not.toHaveBeenCalled();
  });

  it('offers the actions on each unit with the permission', async () => {
    renderEditable({ links: [ITEM_LINK, VARIATION_LINK], units: [unit(0, apiLink()), unit(9002, apiLink({ source: 'manual' }))] });
    expect(publicacionesMlAPI.productLinks).toHaveBeenCalledWith(ITEM);
    const item = await cardOf('Publicación');
    const variation = await cardOf('Variación 9002');
    expect(within(item).getByRole('button', { name: 'Vincular producto' })).toBeInTheDocument();
    expect(within(variation).getByRole('button', { name: 'Vincular producto' })).toBeInTheDocument();
    expect(within(item).getByRole('button', { name: 'Marcar sin producto' })).toBeInTheDocument();
  });
});

describe('linking a unit to a product', () => {
  it('offers the conflict candidates first and links the one picked, with the note', async () => {
    const user = userEvent.setup();
    publicacionesMlAPI.setProductLink.mockResolvedValue(written);
    const { onWritten } = renderEditable({ links: [CONFLICT_LINK], units: [CONFLICT_UNIT] });
    const card = await cardOf('Publicación');
    await user.click(within(card).getByRole('button', { name: 'Vincular producto' }));

    const candidates = within(card).getByRole('list', { name: 'Candidatos' });
    expect(within(candidates).getAllByRole('button')).toHaveLength(2);
    await user.click(within(candidates).getByRole('button', { name: /AX55-B/ }));
    await user.type(within(card).getByLabelText('Nota (opcional)'), 'Es el blanco');
    await user.click(within(card).getByRole('button', { name: 'Guardar' }));

    await waitFor(() => expect(publicacionesMlAPI.setProductLink).toHaveBeenCalledWith(ITEM, 0, { producto_item_id: 4108, note: 'Es el blanco' }));
    await waitFor(() => expect(onWritten).toHaveBeenCalledTimes(1));
    expect(publicacionesMlAPI.productLinks).toHaveBeenCalledTimes(2);
  });

  it('searches the ERP products and links the one picked, sending no note when empty', async () => {
    const user = userEvent.setup();
    publicacionesMlAPI.searchProducts.mockResolvedValue({ data: [{ item_id: 5001, codigo: 'DECO-X20', descripcion: 'Deco X20', marca: 'TP-LINK', costo_unitario: 10 }] });
    publicacionesMlAPI.setProductLink.mockResolvedValue(written);
    renderEditable({ links: [VARIATION_LINK], units: [unit(9002, apiLink({ source: 'manual' }))] });
    const card = await cardOf('Variación 9002');
    await user.click(within(card).getByRole('button', { name: 'Vincular producto' }));

    expect(within(card).getByRole('button', { name: 'Guardar' })).toBeDisabled();
    const search = within(card).getByLabelText('Buscar producto');
    await user.type(search, 'x');
    expect(within(card).getByRole('button', { name: 'Buscar' })).toBeDisabled();
    await user.type(search, '20{Enter}');
    expect(publicacionesMlAPI.searchProducts).toHaveBeenCalledWith('x20');

    const results = await within(card).findByRole('list', { name: 'Resultados' });
    await user.click(within(results).getByRole('button', { name: /DECO-X20/ }));
    await user.click(within(card).getByRole('button', { name: 'Guardar' }));

    await waitFor(() => expect(publicacionesMlAPI.setProductLink).toHaveBeenCalledWith(ITEM, 9002, { producto_item_id: 5001, note: null }));
  });

  it('says so when the search finds nothing', async () => {
    const user = userEvent.setup();
    publicacionesMlAPI.searchProducts.mockResolvedValue({ data: [] });
    renderEditable();
    const card = await cardOf('Publicación');
    await user.click(within(card).getByRole('button', { name: 'Vincular producto' }));
    await user.type(within(card).getByLabelText('Buscar producto'), 'zzz{Enter}');
    expect(await within(card).findByText('No se encontraron productos.')).toBeInTheDocument();
  });

  it('cancelling closes the editor without writing', async () => {
    const user = userEvent.setup();
    renderEditable();
    const card = await cardOf('Publicación');
    await user.click(within(card).getByRole('button', { name: 'Vincular producto' }));
    await user.click(within(card).getByRole('button', { name: 'Cancelar' }));
    expect(within(card).queryByLabelText('Buscar producto')).not.toBeInTheDocument();
    expect(publicacionesMlAPI.setProductLink).not.toHaveBeenCalled();
  });
});

describe('marking a unit as having no product', () => {
  it('asks for confirmation, then writes it with the note and refreshes', async () => {
    const user = userEvent.setup();
    publicacionesMlAPI.setProductLinkNone.mockResolvedValue(written);
    const { onWritten } = renderEditable();
    const card = await cardOf('Publicación');
    await user.click(within(card).getByRole('button', { name: 'Marcar sin producto' }));
    expect(publicacionesMlAPI.setProductLinkNone).not.toHaveBeenCalled();
    await user.type(within(card).getByLabelText('Nota (opcional)'), 'Combo');
    await user.click(within(card).getByRole('button', { name: 'Confirmar' }));

    await waitFor(() => expect(publicacionesMlAPI.setProductLinkNone).toHaveBeenCalledWith(ITEM, 0, { note: 'Combo' }));
    await waitFor(() => expect(onWritten).toHaveBeenCalledTimes(1));
  });
});

describe('handing a unit back to the automatic rule', () => {
  it('is offered only for a manual link or a manual "no product"', async () => {
    renderEditable({
      links: [ITEM_LINK, VARIATION_LINK, { ...VARIATION_LINK, variation_id: 9003 }],
      units: [unit(0, apiLink()), unit(9002, apiLink({ source: 'manual' })), unit(9003, apiLink({ source: 'manual_none', match_status: 'unmatched', producto_item_id: null, producto: null }))],
    });
    expect(within(await cardOf('Publicación')).queryByRole('button', { name: 'Volver a automático' })).not.toBeInTheDocument();
    expect(within(await cardOf('Variación 9002')).getByRole('button', { name: 'Volver a automático' })).toBeInTheDocument();
    expect(within(await cardOf('Variación 9003')).getByRole('button', { name: 'Volver a automático' })).toBeInTheDocument();
  });

  it('reverts the unit and refreshes', async () => {
    const user = userEvent.setup();
    publicacionesMlAPI.revertProductLinkAuto.mockResolvedValue(written);
    const { onWritten } = renderEditable({ links: [VARIATION_LINK], units: [unit(9002, apiLink({ source: 'manual' }))] });
    await user.click(within(await cardOf('Variación 9002')).getByRole('button', { name: 'Volver a automático' }));
    await waitFor(() => expect(publicacionesMlAPI.revertProductLinkAuto).toHaveBeenCalledWith(ITEM, 9002));
    await waitFor(() => expect(onWritten).toHaveBeenCalledTimes(1));
  });
});

describe('a unit the automatic rule never evaluated', () => {
  it('is listed from the link units even when the detail has no link row, and can be linked', async () => {
    renderEditable({ links: [], units: [unit(0, null)] });
    const card = await cardOf('Publicación');
    expect(card).toHaveTextContent('Sin evaluar');
    expect(card).toHaveTextContent('Sin producto vinculado');
    expect(within(card).getByRole('button', { name: 'Vincular producto' })).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Volver a automático' })).not.toBeInTheDocument();
  });
});

describe('a refused write', () => {
  it.each([
    [409, 'La vinculación de productos está desactivada.'],
    [403, 'No tenés permiso para vincular productos.'],
    [422, 'detail 422'],
    [500, 'No se pudo guardar el vínculo.'],
  ])('%i says why and refreshes nothing', async (status, message) => {
    const user = userEvent.setup();
    publicacionesMlAPI.setProductLinkNone.mockRejectedValue(httpError(status));
    const { onWritten } = renderEditable();
    const card = await cardOf('Publicación');
    await user.click(within(card).getByRole('button', { name: 'Marcar sin producto' }));
    await user.click(within(card).getByRole('button', { name: 'Confirmar' }));
    expect(await within(card).findByRole('alert')).toHaveTextContent(message);
    expect(onWritten).not.toHaveBeenCalled();
  });

  it('a failed load of the link units says so and keeps the links shown', async () => {
    granted = new Set(['ml_publicaciones.vincular']);
    publicacionesMlAPI.productLinks.mockRejectedValue(httpError(500));
    const detail = readDetail(makeDetail({ product: null, links: [ITEM_LINK] }));
    render(<ProductoVinculadoTab detail={detail} itemId={ITEM} onWritten={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar los vínculos para editarlos.');
    expect(within(section('Vínculos')).getByRole('listitem')).toHaveTextContent('ARCHER-AX55');
  });
});
