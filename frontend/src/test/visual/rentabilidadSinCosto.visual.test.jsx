/**
 * Rentabilidad of Ventas por fuera and Tienda Nube — sales without a known cost (costo SI interface §7: the endpoint
 * returns a null costo, ganancia and markup when no sale of a card has a cost and counts the lines without one in
 * `ventas_sin_costo`). Those figures read "Sin costo" in secondary text, never $0, and the cards and totals with sales
 * without cost carry a readable note, at 1440 next to the expanded sidebar, in both themes. With
 * `VITE_RENTABILIDAD_SHOTS_DIR` it also takes the review screenshots:
 *
 *   VITE_RENTABILIDAD_SHOTS_DIR=<dir> run_tests.sh frontend src/test/visual/rentabilidadSinCosto.visual.test.jsx
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { createElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { setTheme, tokenColor, contrastRatio, rgba } from './visualHelpers';
import api from '../../services/api';
import TabRentabilidadFuera from '../../components/TabRentabilidadFuera';
import TabRentabilidadTiendaNube from '../../components/TabRentabilidadTiendaNube';
import Sidebar from '../../components/Sidebar';
import layout from '../../components/AppLayout.module.css';

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, tieneAlgunPermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const SHOTS_DIR = import.meta.env.VITE_RENTABILIDAD_SHOTS_DIR;
const ROOT_ID = 'capturas-root';

const card = (nombre, figures) => ({
  nombre,
  tipo: 'marca',
  identificador: nombre,
  offset_total: 0,
  desglose_offsets: null,
  ...figures,
});

const FUERA = {
  cards: [
    card('MARCA DEMO', { total_ventas: 2, monto_venta: 1500000, costo_total: 600000, ganancia: 400000, markup_promedio: 66.67, ventas_sin_costo: 1, ganancia_con_offset: 400000, markup_con_offset: 66.67 }),
    card('SIN COSTO DEMO', { total_ventas: 1, monto_venta: 300000, costo_total: null, ganancia: null, markup_promedio: null, ventas_sin_costo: 1, ganancia_con_offset: null, markup_con_offset: null }),
    card('COSTEADA DEMO', { total_ventas: 3, monto_venta: 1100000, costo_total: 650000, ganancia: 450000, markup_promedio: 69.23, ventas_sin_costo: 0, ganancia_con_offset: 450000, markup_con_offset: 69.23 }),
  ],
  totales: card('TOTAL', { total_ventas: 6, monto_venta: 2900000, costo_total: 1250000, ganancia: 850000, markup_promedio: 68, ventas_sin_costo: 2, ganancia_con_offset: 850000, markup_con_offset: 68 }),
  filtros_aplicados: { nivel_agrupacion: 'marca' },
};

const conComision = (c) => ({ ...c, comision_tn: c.monto_venta * 0.01, monto_limpio: c.monto_venta * 0.99 });
const TN = {
  cards: FUERA.cards.map(conComision),
  totales: conComision(FUERA.totales),
  filtros_aplicados: { nivel_agrupacion: 'marca', comision_tn_porcentaje: 1 },
};

const TABS = [
  { nombre: 'fuera', Tab: TabRentabilidadFuera, respuesta: FUERA },
  { nombre: 'tienda-nube', Tab: TabRentabilidadTiendaNube, respuesta: TN },
];

afterAll(() => vi.restoreAllMocks());

const shot = async (name) => {
  if (!SHOTS_DIR) return;
  await page.screenshot({ path: `${SHOTS_DIR}/${name}.png`, element: document.getElementById(ROOT_ID) });
};

const renderTab = (tab) =>
  render(
    <MemoryRouter>
      <div id={ROOT_ID} className={layout.appLayout} style={{ height: '100vh', overflow: 'hidden' }}>
        <Sidebar />
        <div className={layout.mainWrapper} data-sidebar-expanded="true" data-sidebar-hidden="false">
          <main className={layout.mainContent} style={{ marginTop: 0 }}>
            {createElement(tab, { fechaDesde: '2026-01-01', fechaHasta: '2026-01-31' })}
          </main>
        </div>
      </div>
    </MemoryRouter>,
  );

// The first ancestor (or the element itself) that paints an opaque background: what the text is read against.
const fondoOpaco = (el) => {
  for (let nodo = el; nodo; nodo = nodo.parentElement) {
    const fondo = getComputedStyle(nodo).backgroundColor;
    if (rgba(fondo)[3] === 1) return fondo;
  }
  return 'rgb(255, 255, 255)';
};

// The card holding the heading `nombre`.
const cardDe = (nombre) => page.getByRole('heading', { name: nombre }).element().parentElement.parentElement;

describe.each(['light', 'dark'])('Rentabilidad, sales without cost (%s)', (theme) => {
  describe.each(TABS)('$nombre', ({ nombre, Tab, respuesta }) => {
    beforeEach(async () => {
      vi.spyOn(api, 'get').mockImplementation((url) =>
        Promise.resolve({
          data: url.startsWith('/rentabilidad')
            ? url.endsWith('/filtros')
              ? { marcas: ['MARCA DEMO'], categorias: [], subcategorias: [] }
              : respuesta
            : [],
        }),
      );
      await page.viewport(1440, 900);
      setTheme(theme);
    });

    it('"Sin costo" in secondary text instead of $0, readable notes, no sideways scroll', async () => {
      renderTab(Tab);
      await expect.element(page.getByRole('heading', { name: 'SIN COSTO DEMO' })).toBeVisible();

      const sinCosto = cardDe('SIN COSTO DEMO');
      const marcas = [...sinCosto.querySelectorAll('[aria-label="Sin costo"]')];
      expect(marcas).toHaveLength(3);
      for (const marca of marcas) {
        expect(marca.textContent).toBe('Sin costo');
        expect(getComputedStyle(marca).color).toBe(tokenColor('--text-secondary'));
        expect(contrastRatio(getComputedStyle(marca).color, fondoOpaco(marca))).toBeGreaterThanOrEqual(4.5);
      }
      expect(sinCosto.textContent.replace(/\u00a0/g, ' ')).not.toMatch(/\$ ?0(?![\d.])/);

      const notas = page.getByText('1 venta sin costo: no suman al costo ni a la ganancia').elements();
      expect(notas).toHaveLength(2);
      for (const nota of notas) {
        expect(getComputedStyle(nota).color).toBe(tokenColor('--text-secondary'));
        expect(contrastRatio(getComputedStyle(nota).color, fondoOpaco(nota))).toBeGreaterThanOrEqual(4.5);
      }
      // The total card is light text on a dark gradient in both themes: its note reads like the card's labels.
      const notaTotal = page.getByText('2 ventas sin costo: no suman al costo ni a la ganancia').element();
      const etiquetaTotal = page.getByText('Ventas', { exact: true }).element();
      expect(getComputedStyle(notaTotal).color).toBe(getComputedStyle(etiquetaTotal).color);
      expect(getComputedStyle(notaTotal).opacity).toBe(getComputedStyle(etiquetaTotal).opacity);
      expect(cardDe('COSTEADA DEMO').querySelector('[aria-label="Sin costo"]')).toBeNull();

      const main = document.querySelector('main');
      expect(main.scrollWidth).toBeLessThanOrEqual(main.clientWidth + 1);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1440);

      await shot(`rentabilidad-${nombre}-sin-costo-1440-${theme}`);
    });
  });
});
