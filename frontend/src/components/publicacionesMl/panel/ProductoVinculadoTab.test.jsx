/**
 * Producto vinculado tab (publicaciones-ml-vista P13b.T3, S59.x): the product
 * the publication is linked to, its list prices and the link of each unit. The
 * cost is shown only with `ml_metricas.ver_ganancia`. Editing the links is not
 * done here.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import ProductoVinculadoTab from './ProductoVinculadoTab';
import { readDetail } from './detailModel';
import { ITEM_LINK, PRODUCT, PRODUCT_COST, VARIATION_LINK, makeDetail } from '../../../test/visual/publicacionesMlFixtures';

const LINKED = { product: { ...PRODUCT, ...PRODUCT_COST }, links: [ITEM_LINK, VARIATION_LINK] };

const renderTab = (overrides = LINKED, { canSeeMargin = false } = {}) => {
  const detail = readDetail(makeDetail(overrides), { canSeeMargin });
  return render(<ProductoVinculadoTab detail={detail} itemId={detail.itemId} canSeeMargin={canSeeMargin} />);
};
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
