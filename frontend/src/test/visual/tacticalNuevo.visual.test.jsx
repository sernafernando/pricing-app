/**
 * Nuevo tactical (approved OpenDesign screens handoffs/diseno-tactical/nuevo-tactical-*aprobado.html) in real
 * Chromium: the lines' cells sit under their column heads, the product picker opens inside the viewport, and the
 * sticky summary bar does not cover the last line once the page is scrolled to the end.
 * The picker opens below its line, as the design draws it; scrolled to, it is whole and above the sticky bar.
 *
 * Screenshots are written only when `VITE_TACTICAL_SHOTS_DIR` is set (PR evidence next to the design PNGs).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import TacticalNuevo from '../../pages/TacticalNuevo';
import api, { productosAPI } from '../../services/api';
import { CATALOGO } from '../../components/tactical/tacticalFixtures';

const SHOTS_DIR = import.meta.env.VITE_TACTICAL_SHOTS_DIR;

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  productosAPI: { marcas: vi.fn(), categorias: vi.fn() },
}));

vi.mock('../../services/sellInAPI', () => ({
  // The Productos tab's list; never opened here.
  sellInLotesAPI: { productos: vi.fn(() => new Promise(() => {})) }, sellInAPI: { operaciones: vi.fn() } }));

beforeEach(() => {
  productosAPI.marcas.mockResolvedValue({ data: { marcas: ['HP', 'TP-Link'] } });
  productosAPI.categorias.mockResolvedValue({ data: { categorias: ['Monitores', 'Notebooks', 'Redes'] } });
  api.get.mockImplementation((url, config) => {
    const words = config.params.q.toLowerCase().split(/\s+/);
    return Promise.resolve({
      data: CATALOGO.filter((p) => words.every((w) => `${p.codigo} ${p.descripcion}`.toLowerCase().includes(w))),
    });
  });
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

const left = (el) => el.getBoundingClientRect().left;

describe.each([
  { width: 1440, height: 900, theme: 'light' },
  { width: 1440, height: 900, theme: 'dark' },
  { width: 1366, height: 768, theme: 'light' },
])('Nuevo tactical at $width px, $theme', ({ width, height, theme }) => {
  it.each(['sell_out', 'sell_in'])('%s: cells under their heads, picker in view, summary bar off the lines', async (tipo) => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter initialEntries={[`/sell-in/tactical/nuevo?tipo=${tipo}`]}>
        <Shell>
          <Routes>
            <Route path="/sell-in/tactical/nuevo" element={<TacticalNuevo />} />
          </Routes>
        </Shell>
      </MemoryRouter>,
    );
    await expect.element(screen.getByRole('heading', { name: 'Nuevo tactical' })).toBeVisible();
    await screen.getByLabelText('Nombre').fill(tipo === 'sell_in' ? 'Rebate TP-Link noviembre' : 'Tacticals BPS Noviembre Q1FY27');

    // The design's form: every single-line control is one height and stays inside its card; titles are semibold.
    const card = screen.getByRole('heading', { name: 'Datos del tactical' }).element().closest('section').getBoundingClientRect();
    const altos = ['Nombre', 'Marca', 'Referencia de la marca', 'Desde', 'Hasta'].map((label) => {
      const box = screen.getByLabelText(label, { exact: true }).element().getBoundingClientRect();
      expect(box.right).toBeLessThanOrEqual(card.right + 0.5);
      return Math.round(box.height);
    });
    expect(new Set(altos).size).toBe(1);
    for (const name of ['Nuevo tactical', 'Datos del tactical', 'Líneas']) {
      expect(Number(getComputedStyle(screen.getByRole('heading', { name }).element()).fontWeight)).toBeGreaterThanOrEqual(600);
    }

    // A line with three products and its amounts, so every column has content.
    await screen.getByRole('button', { name: '+ Producto' }).click();
    await screen.getByLabelText('Buscar productos').fill('monitor hp');
    await expect.element(screen.getByRole('checkbox', { name: /Monitor HP V24i G5/ })).toBeVisible();
    // Scrolled to, the picker is whole: inside the viewport and on top of everything (the sticky bar included).
    const dialog = document.querySelector('[role="dialog"]');
    dialog.scrollIntoView({ block: 'nearest' });
    const picker = dialog.getBoundingClientRect();
    expect(picker.left).toBeGreaterThanOrEqual(0);
    expect(picker.right).toBeLessThanOrEqual(width + 0.5);
    expect(picker.top).toBeGreaterThanOrEqual(0);
    expect(picker.bottom).toBeLessThanOrEqual(height + 0.5);
    for (const y of [picker.top + 4, picker.bottom - 4]) {
      expect(dialog.contains(document.elementFromPoint(picker.left + picker.width / 2, y))).toBe(true);
    }
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tactical-${tipo}-picker-${theme}-${width}.png` });
    for (const nombre of ['Monitor HP V24i G5', 'Monitor HP V27i G5', 'Monitor HP P24 G5']) {
      await screen.getByRole('checkbox', { name: new RegExp(nombre) }).click();
    }
    await screen.getByRole('button', { name: 'Agregar a la línea' }).click();
    await screen.getByLabelText('Monto de la línea 1').fill('12');
    await screen.getByLabelText('Tope de unidades, línea 1').fill('300');
    await screen.getByRole('button', { name: '+ Agregar línea' }).click();
    await userEvent.keyboard('{Escape}');

    const linea1 = document.querySelector('[role="group"][aria-label="Línea 1"]');
    const head = [...linea1.parentElement.firstElementChild.children];
    const row = [...linea1.children];
    expect(row).toHaveLength(head.length);
    row.forEach((cell, i) => expect(Math.abs(left(cell) - left(head[i]))).toBeLessThanOrEqual(0.5));
    // Every scope fits in its column (sell in has four: Productos, Marca, Categoría, Factura).
    const alcance = screen.getByRole('group', { name: 'Alcance de la línea 1' }).element().getBoundingClientRect();
    expect(alcance.right).toBeLessThanOrEqual(row[2].getBoundingClientRect().left);

    window.scrollTo(0, document.documentElement.scrollHeight);
    const last = document.querySelector('[role="group"][aria-label="Línea 2"]').getBoundingClientRect();
    // Sticky summary only — TacticalDatos also has aria-live for the tope preview.
    const bar = document.querySelector('[data-testid="tactical-stickybar"]');
    expect(last.bottom).toBeLessThanOrEqual(bar.getBoundingClientRect().top + 0.5);
    if (SHOTS_DIR) {
      await page.screenshot({ path: `${SHOTS_DIR}/tactical-${tipo}-lineas-${theme}-${width}.png` });
      window.scrollTo(0, 0);
      await page.screenshot({ path: `${SHOTS_DIR}/tactical-${tipo}-${theme}-${width}.png` });
    }
  });
});
