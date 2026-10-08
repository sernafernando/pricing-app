/**
 * Resumen tab (publicaciones-ml-vista P13a.T2): every field of the publication,
 * the price with its source, the stock by place, and -- for `ver_ganancia`
 * only -- how the markup is made up. A value the backend does not have is "—",
 * never 0 and never blank.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import ResumenTab from './ResumenTab';
import { readDetail } from './detailModel';
import {
  DETAIL_RESPONSE,
  DETAIL_RESPONSE_MARGIN,
  ITEMS,
  makeDetail,
  makeItem,
} from '../../../test/visual/publicacionesMlFixtures';

const renderTab = (raw = DETAIL_RESPONSE, { canSeeMargin = false } = {}) => {
  const detail = readDetail(raw, { canSeeMargin });
  return render(<ResumenTab detail={detail} itemId={detail.itemId} canSeeMargin={canSeeMargin} />);
};
const section = (name) => screen.getByRole('region', { name });
/** The value cell next to the label `label` inside a section. */
const valueOf = (name, label) => {
  const term = within(section(name)).getByText(label, { selector: 'dt' });
  return term.nextElementSibling;
};
const DASH = '—';

describe('the publication', () => {
  it('says what it is: status, condition, type, catalog, logistics', () => {
    renderTab();
    expect(valueOf('Publicación', 'Estado')).toHaveTextContent('Activa');
    expect(valueOf('Publicación', 'Condición')).toHaveTextContent('Nueva');
    expect(valueOf('Publicación', 'Tipo')).toHaveTextContent('Premium');
    expect(valueOf('Publicación', 'Catálogo')).toHaveTextContent('No');
    expect(valueOf('Publicación', 'Logística')).toHaveTextContent('Full');
  });

  it('names the store, brand, family and user product', () => {
    renderTab(makeDetail({ row: makeItem({ ...ITEMS[0], user_product_id: 'MLAU100001' }) }));
    expect(valueOf('Publicación', 'Tienda')).toHaveTextContent('TP-Link');
    expect(valueOf('Publicación', 'Marca')).toHaveTextContent('TP-Link');
    expect(valueOf('Publicación', 'Familia')).toHaveTextContent('Archer AX55');
    expect(valueOf('Publicación', 'Producto de usuario')).toHaveTextContent('MLAU100001');
  });

  it('shows health as a percentage, the tags, and the three dates', () => {
    renderTab();
    expect(valueOf('Publicación', 'Salud')).toHaveTextContent('87,0%');
    const tags = valueOf('Publicación', 'Etiquetas');
    expect(within(tags).getByText('good_quality_picture')).toBeInTheDocument();
    expect(within(tags).getByText('immediate_payment')).toBeInTheDocument();
    for (const label of ['Creada', 'Modificada en ML', 'Sincronizada']) {
      expect(valueOf('Publicación', label).textContent).toMatch(/\d{2}\/\d{2}\/\d{4}/);
    }
  });

  it('lists the sub-status and flags a publication that vanished from ML', () => {
    renderTab(
      makeDetail({
        row: makeItem({ ...ITEMS[3] }),
        sub_status: ['out_of_stock'],
      }),
    );
    expect(valueOf('Publicación', 'Estado')).toHaveTextContent('Eliminada');
    expect(valueOf('Publicación', 'Subestado')).toHaveTextContent('out_of_stock');
    expect(valueOf('Publicación', 'Eliminada el').textContent).toMatch(/\d{2}\/\d{2}\/\d{4}/);
  });

  it('counts the variations, or says there are none', () => {
    renderTab(makeDetail({ row: makeItem({ ...ITEMS[0], variations_count: 3 }) }));
    expect(valueOf('Publicación', 'Variaciones')).toHaveTextContent('3');
  });

  it('every field the backend does not have reads "—", never 0 or blank (S4.1)', () => {
    renderTab(
      makeDetail({
        row: ITEMS[2],
        tags: [],
        health: null,
        condition: null,
        date_created: null,
        ml_last_updated: null,
        fetched_at: null,
        stock_locations: null,
        stock_as_of: null,
        replenishment: null,
      }),
    );
    for (const label of ['Estado', 'Condición', 'Tienda', 'Marca', 'Familia', 'Producto de usuario', 'Salud', 'Etiquetas', 'Creada', 'Modificada en ML', 'Sincronizada']) {
      expect(valueOf('Publicación', label)).toHaveTextContent(DASH);
    }
    expect(within(section('Publicación')).queryByText('0')).not.toBeInTheDocument();
  });
});

describe('the price', () => {
  it('shows the amount and where it comes from', () => {
    renderTab();
    expect(valueOf('Precio', 'Precio')).toHaveTextContent('98.500,50');
    expect(valueOf('Precio', 'Origen')).toHaveTextContent('Precio de oferta');
  });

  it('shows the regular price and the promotion type under it', () => {
    renderTab();
    expect(valueOf('Precio', 'Precio regular')).toHaveTextContent('112.000,00');
    expect(valueOf('Precio', 'Promoción')).toHaveTextContent('DEAL');
    expect(valueOf('Precio', 'Promoción')).toHaveTextContent('Hot Sale');
  });

  it('labels the price that comes from Productos as such', () => {
    renderTab(makeDetail({ row: ITEMS[1] }));
    expect(valueOf('Precio', 'Origen')).toHaveTextContent('Precio de Productos');
    expect(valueOf('Precio', 'Promoción')).toHaveTextContent(DASH);
  });

  it('without a price everything reads "—"', () => {
    renderTab(makeDetail({ row: ITEMS[2] }));
    for (const label of ['Precio', 'Origen', 'Precio regular', 'Promoción']) {
      expect(valueOf('Precio', label)).toHaveTextContent(DASH);
    }
  });
});

describe('the stock', () => {
  it('shows available, Full and Propio, and the places they come from', () => {
    renderTab();
    expect(valueOf('Stock', 'Disponible')).toHaveTextContent('34');
    expect(valueOf('Stock', 'Full')).toHaveTextContent('20');
    expect(valueOf('Stock', 'Propio')).toHaveTextContent('14');
    expect(valueOf('Stock', 'Depósito de Mercado Libre')).toHaveTextContent('20');
    expect(valueOf('Stock', 'Dirección del vendedor')).toHaveTextContent('14');
    expect(valueOf('Stock', 'Actualizado').textContent).toMatch(/\d{2}\/\d{2}\/\d{4}/);
  });

  it('a place type the screen does not know keeps its own name', () => {
    renderTab(makeDetail({ stock_locations: [{ type: 'warehouse_x', quantity: 3 }] }));
    expect(valueOf('Stock', 'warehouse_x')).toHaveTextContent('3');
  });

  it('a real 0 is shown as 0; an unknown figure is "—"', () => {
    renderTab(makeDetail({ row: makeItem({ ...ITEMS[0], stock: { available: 0, full: null, own: 0, as_of: null } }), stock_locations: null }));
    expect(valueOf('Stock', 'Disponible')).toHaveTextContent('0');
    expect(valueOf('Stock', 'Full')).toHaveTextContent(DASH);
    expect(valueOf('Stock', 'Propio')).toHaveTextContent('0');
    expect(within(section('Stock')).queryByText('Depósito de Mercado Libre')).not.toBeInTheDocument();
  });
});

describe('the link with the product', () => {
  it('shows the state and the product it points to', () => {
    renderTab();
    expect(valueOf('Vínculo', 'Estado')).toHaveTextContent('Automático');
    expect(valueOf('Vínculo', 'Código')).toHaveTextContent('ARCHER-AX55');
    expect(valueOf('Vínculo', 'Producto')).toHaveTextContent('Router Archer AX55');
  });

  it('an unlinked publication says so', () => {
    renderTab(makeDetail({ row: ITEMS[3] }));
    expect(valueOf('Vínculo', 'Estado')).toHaveTextContent('Sin producto');
    expect(valueOf('Vínculo', 'Código')).toHaveTextContent(DASH);
  });
});

describe('the markup breakdown (ver_ganancia only)', () => {
  it('shows how the markup is made up', () => {
    renderTab(DETAIL_RESPONSE_MARGIN, { canSeeMargin: true });
    expect(valueOf('Markup', 'Precio')).toHaveTextContent('98.500,50');
    expect(valueOf('Markup', 'Origen del precio')).toHaveTextContent('Precio de oferta');
    expect(valueOf('Markup', 'Lista de precios')).toHaveTextContent('12');
    expect(valueOf('Markup', 'Comisión')).toHaveTextContent('13,5%');
    expect(valueOf('Markup', 'Comisión total')).toHaveTextContent('13.297,57');
    expect(valueOf('Markup', 'Costo de envío')).toHaveTextContent('4.200,00');
    expect(valueOf('Markup', 'Origen del envío')).toHaveTextContent('ERP');
    expect(valueOf('Markup', 'Precio limpio')).toHaveTextContent('81.002,93');
    expect(valueOf('Markup', 'Costo')).toHaveTextContent('64.000,00');
    expect(valueOf('Markup', 'Markup')).toHaveTextContent('26,5%');
  });

  it('a negative markup is flagged', () => {
    renderTab(makeDetail({ markup_breakdown: { ...DETAIL_RESPONSE_MARGIN.markup_breakdown, markup: -3.2 } }), { canSeeMargin: true });
    expect(valueOf('Markup', 'Markup')).toHaveTextContent('-3,2%');
    expect(valueOf('Markup', 'Markup').querySelector('[data-negative]')).not.toBeNull();
  });

  it('with the permission but no breakdown (not linked, no cost) it says there is none', () => {
    renderTab(makeDetail(), { canSeeMargin: true });
    expect(within(section('Markup')).getByText(/No se pudo calcular el markup/)).toBeInTheDocument();
  });

  it('without the permission the section does not exist, even if the payload carried it', () => {
    renderTab(DETAIL_RESPONSE_MARGIN, { canSeeMargin: false });
    expect(screen.queryByRole('region', { name: 'Markup' })).not.toBeInTheDocument();
    expect(screen.queryByText('Precio limpio')).not.toBeInTheDocument();
  });
});
