/**
 * "ABM de productos" (abm-productos T8) with the approved mock's own data: the list and the ficha (General and Specs
 * técnicas) fit desktop and phone widths in both themes with no horizontal page scroll. Real Chromium geometry.
 *
 * The phone viewport is tall because the browser runner only paints the viewport: a full-page shot of a short one
 * leaves the ficha blank. Screenshots are written only when `VITE_ABM_PRODUCTOS_SHOTS_DIR` is set (a DEV aid to put
 * the real screen next to the mock, never a committed baseline).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import AbmProductos from '../../pages/AbmProductos';
import {
  productoCategoriasAPI,
  productoMaestroAPI,
  productoMarcasAPI,
  productoSpecsAPI,
  productoTnVinculosAPI,
} from '../../services/api';
import { CAMPOS_SPECS, CATEGORIAS, LISTA, MAESTRO, MARCAS, SPECS_4874, TOTALES, VINCULOS } from './abmProductosFixtures';

vi.mock('../../services/api', () => ({
  default: { get: vi.fn() },
  productoMaestroAPI: { listar: vi.fn(), leer: vi.fn(), guardar: vi.fn() },
  productoSpecsAPI: { leer: vi.fn(), guardar: vi.fn(), precargar: vi.fn(), valores: vi.fn(), campos: vi.fn() },
  productoTnVinculosAPI: { leer: vi.fn(), candidatos: vi.fn(), vincular: vi.fn() },
  productoMarcasAPI: { listar: vi.fn() },
  productoCategoriasAPI: { listar: vi.fn() },
}));

const SHOTS_DIR = import.meta.env.VITE_ABM_PRODUCTOS_SHOTS_DIR;

beforeEach(() => {
  productoMaestroAPI.listar.mockImplementation((params) => {
    const items = params.tipo ? LISTA.filter((r) => r.tipo === params.tipo) : LISTA;
    return Promise.resolve({ data: { total: TOTALES[params.tipo ?? 'todos'], items: params.limit === 1 ? [] : items } });
  });
  productoMaestroAPI.leer.mockImplementation((id) => Promise.resolve({ data: MAESTRO[id] ?? MAESTRO[455] }));
  productoTnVinculosAPI.leer.mockImplementation((id) => Promise.resolve({ data: VINCULOS[id] ?? VINCULOS[4874] }));
  productoSpecsAPI.leer.mockResolvedValue({ data: SPECS_4874 });
  productoSpecsAPI.campos.mockResolvedValue({ data: CAMPOS_SPECS });
  productoSpecsAPI.valores.mockResolvedValue({ data: [] });
  productoMarcasAPI.listar.mockResolvedValue({ data: MARCAS });
  productoCategoriasAPI.listar.mockResolvedValue({ data: CATEGORIAS });
});

const sinScrollHorizontal = () => expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);

describe.each([
  { width: 1440, height: 1700, theme: 'light' },
  { width: 1440, height: 1700, theme: 'dark' },
  { width: 390, height: 4400, theme: 'light' },
  { width: 390, height: 4400, theme: 'dark' },
])('ABM de productos at $width px, $theme', ({ width, height, theme }) => {
  it('shows the list and the General ficha, then the specs, without horizontal page scroll', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(<AbmProductos />);

    await userEvent.click(screen.getByText('Adaptador Bluetooth 5.0 TP-Link UB500 Nano USB', { exact: true }).first());
    await expect.element(screen.getByText('GBP: BLUETOOTH TPLINK NANO USB UB500 BT 5.0')).toBeVisible();
    await expect.element(screen.getByText('Automático por SKU')).toBeVisible();
    await expect
      .element(screen.getByLabelText('Descripción web'))
      .toHaveAttribute('placeholder', 'Sin descripción en Tienda Nube: llega con la sincronización de TN');
    sinScrollHorizontal();
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/real-general-${width}-${theme}.png`, fullPage: true });

    await userEvent.click(screen.getByRole('tab', { name: /Notebooks/ }));
    await userEvent.click(screen.getByText('NB ASUS E1504FA 15.6" R5-40 8GB D5 512GB  FDOS (9921)').first());
    await userEvent.click(screen.getByRole('tab', { name: 'Specs técnicas 9 / 17' }));
    await expect.element(screen.getByRole('button', { name: 'Precargar de nuevo' })).toBeVisible();
    await expect.element(screen.getByLabelText('Pantalla Tamaño')).toHaveValue('15.6');
    sinScrollHorizontal();
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/real-specs-${width}-${theme}.png`, fullPage: true });
  });
});
