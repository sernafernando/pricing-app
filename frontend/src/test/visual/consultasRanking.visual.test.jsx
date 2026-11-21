/**
 * Ranking de Productos at costo SI (sell-in-costo-si T3 PR 10, unit B): a stocked product with an unknown cost reads
 * "Sin costo" in secondary text, and the capital KPI card and the resumen totals carry the "N productos sin costo"
 * note, at 1440 next to the expanded sidebar, in both themes; everything fits its card / table container. With
 * `VITE_CONSULTAS_RANKING_SHOTS_DIR` it also takes the review screenshots:
 *
 *   VITE_CONSULTAS_RANKING_SHOTS_DIR=<dir> run_tests.sh frontend src/test/visual/consultasRanking.visual.test.jsx
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme, tokenColor } from './visualHelpers';
import api from '../../services/api';
import ConsultasRanking from '../../pages/ConsultasRanking';
import Sidebar from '../../components/Sidebar';
import layout from '../../components/AppLayout.module.css';

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, tieneAlgunPermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const SHOTS_DIR = import.meta.env.VITE_CONSULTAS_RANKING_SHOTS_DIR;
const ROOT_ID = 'capturas-root';

const fila = (itemId, codigo, stock, ars, usd) => ({
  item_id: itemId,
  codigo,
  descripcion: `Cámara IP Demo Domo 4MP Exterior Visión Nocturna ${codigo}`,
  marca: 'MARCA DEMO',
  categoria: 'CAMARAS',
  moneda_costo: ars == null ? null : 'USD',
  pm: 'PM Demo',
  dias_sin_venta: 120,
  erp_ageing_dias: null,
  last_purchase_date: '2026-09-15',
  last_purchase_qty: 20,
  total_stock: stock,
  valor_costo_ars: ars,
  valor_costo_usd: usd,
  valor_venta: stock ? 450000 * stock : null,
});

const RANKING = {
  items: [fila(1, 'CONCOSTO', 10, 200000, 200), fila(2, 'SINCOSTO', 5, null, null)],
  total: 2,
  page: 1,
  page_size: 50,
};

const KPIS = {
  total_productos: 2,
  stock_total: 15,
  capital_costo_ars: 200000,
  capital_costo_usd: 200,
  capital_venta_ars: 6750000,
  capital_muerto_ars: 0,
  pct_capital_muerto: 0,
  productos_sin_costo: 1,
};

const grupo = (nombre, ars, usd, sinCosto) => ({
  grupo: nombre,
  pm: 'PM Demo',
  num_productos: 2,
  stock_total: 15,
  valor_costo_ars: ars,
  valor_costo_usd: usd,
  valor_venta: 6750000,
  productos_sin_costo: sinCosto,
});

const RESUMEN = {
  items: [grupo('MARCA DEMO', 200000, 200, 1), grupo('OTRA MARCA', null, null, 2)],
  totales: { ...grupo('TOTAL', 200000, 200, 3), pm: null, num_productos: 4 },
};

const respuesta = (url) => {
  if (url.includes('/consultas/ranking/kpis')) return KPIS;
  if (url.includes('/consultas/ranking/resumen')) return RESUMEN;
  if (url.includes('/consultas/ranking/facets')) return { marcas: [], categorias: [], pms: [], depositos: [] };
  if (url.includes('/consultas/ranking/stock-status')) return { last_updated: '2026-11-20T09:00:00', syncing: false };
  if (url.includes('/consultas/ranking')) return RANKING;
  return url.includes('disponibles') || url.includes('/usuarios/pms') ? [] : {};
};

beforeEach(() => {
  vi.spyOn(api, 'get').mockImplementation((url) => Promise.resolve({ data: respuesta(url) }));
});

afterAll(() => {
  vi.restoreAllMocks();
});

const shot = async (name) => {
  if (!SHOTS_DIR) return;
  await page.screenshot({ path: `${SHOTS_DIR}/${name}.png`, element: document.getElementById(ROOT_ID) });
};

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/consultas/ranking']}>
      <div id={ROOT_ID} className={layout.appLayout} style={{ height: '100vh', overflow: 'hidden' }}>
        <Sidebar />
        <div className={layout.mainWrapper} data-sidebar-expanded="true" data-sidebar-hidden="false">
          <main className={layout.mainContent} style={{ marginTop: 0 }}>
            <ConsultasRanking />
          </main>
        </div>
      </div>
    </MemoryRouter>,
  );

// The nearest ancestor that clips or scrolls the element sideways.
const contenedorDe = (el) => {
  for (let nodo = el.parentElement; nodo; nodo = nodo.parentElement) {
    if (['auto', 'scroll', 'hidden'].includes(getComputedStyle(nodo).overflowX)) return nodo;
  }
  return document.documentElement;
};

// An element fits when it sits inside its clipping container and its own text is not cut.
const cabe = (el) => {
  const borde = Math.min(contenedorDe(el).getBoundingClientRect().right, 1440);
  expect(el.getBoundingClientRect().right, el.textContent).toBeLessThanOrEqual(borde + 1);
  expect(el.scrollWidth, el.textContent).toBeLessThanOrEqual(el.clientWidth + 1);
};

describe.each(['light', 'dark'])('Ranking de Productos, Sin costo (%s)', (theme) => {
  beforeEach(async () => {
    await page.viewport(1440, 900);
    setTheme(theme);
  });

  it('Detalle: the product without cost reads "Sin costo" in secondary text and the capital card counts it', async () => {
    renderPage();
    const fila = page.getByRole('row').filter({ hasText: 'SINCOSTO' });
    await expect.element(fila).toBeVisible();

    const marca = fila.getByLabelText('Sin costo').element();
    expect(marca.textContent).toBe('Sin costo');
    expect(getComputedStyle(marca).color).toBe(tokenColor('--text-secondary'));
    // The Detalle table already scrolls sideways at 1440 (11 columns): the mark fits its own cell, uncut, on one line.
    const celda = marca.closest('td');
    expect(marca.getBoundingClientRect().right).toBeLessThanOrEqual(celda.getBoundingClientRect().right + 1);
    expect(marca.scrollWidth).toBeLessThanOrEqual(marca.clientWidth + 1);
    expect(marca.getClientRects()).toHaveLength(1);
    const conCosto = page.getByRole('row').filter({ hasText: 'CONCOSTO' });
    expect(conCosto.getByLabelText('Sin costo').elements()).toHaveLength(0);

    const kpis = page.getByRole('region', { name: 'KPIs de capital' });
    await expect.element(kpis.getByText('1 producto sin costo')).toBeVisible();
    const nota = kpis.getByText('1 producto sin costo').element();
    expect(getComputedStyle(nota).color).toBe(tokenColor('--text-secondary'));
    cabe(nota);
    const tarjeta = nota.parentElement;
    expect(nota.getBoundingClientRect().right).toBeLessThanOrEqual(tarjeta.getBoundingClientRect().right);

    marca.scrollIntoView({ inline: 'end', block: 'nearest' }); // the review shot shows the cost column
    await shot(`consultas-ranking-detalle-sin-costo-1440-${theme}`);
  });

  it('Resumen: the groups and the totals carry the note, a group with no costed product reads "Sin costo"', async () => {
    renderPage();
    await page.getByRole('tab', { name: 'Resumen' }).click();
    const total = page.getByRole('row').filter({ hasText: 'TOTAL' });
    await expect.element(total.getByText('3 productos sin costo')).toBeVisible();

    cabe(total.getByText('3 productos sin costo').element());
    const marca = page.getByRole('row').filter({ hasText: 'MARCA DEMO' });
    cabe(marca.getByText('1 producto sin costo').element());
    const otra = page.getByRole('row').filter({ hasText: 'OTRA MARCA' });
    const sinCosto = otra.getByLabelText('Sin costo').element();
    expect(getComputedStyle(sinCosto).color).toBe(tokenColor('--text-secondary'));
    cabe(sinCosto);

    const tabla = document.querySelector('table');
    const contenedor = contenedorDe(tabla);
    expect(contenedor.scrollWidth).toBeLessThanOrEqual(contenedor.clientWidth + 1);

    await shot(`consultas-ranking-resumen-sin-costo-1440-${theme}`);
  });
});
