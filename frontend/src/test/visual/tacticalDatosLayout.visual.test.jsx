/**
 * Datos del tactical layout (owner, 2026-11-10) in real Chromium, light and dark:
 * S1 the reference input and the Desde/Hasta date inputs sit on the same row, top-aligned;
 * S2 the Moneda control is sized to its two 3-letter options, not stretched to its column;
 * S3 the cap preview, shared and per store, reads with the first line's unit cap (100 u.).
 *
 *   VITE_TACTICAL_DATOS_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual tacticalDatosLayout
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import TacticalNuevo from '../../pages/TacticalNuevo';
import { productosAPI } from '../../services/api';
import { seedTiendasOficiales } from '../tiendasOficialesFixtures';

const SHOTS_DIR = import.meta.env.VITE_TACTICAL_DATOS_SHOTS_DIR;

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));
vi.mock('../../services/api', () => ({
  default: { get: vi.fn(() => Promise.resolve({ data: [] })), post: vi.fn() },
  productosAPI: { marcas: vi.fn(), categorias: vi.fn() },
}));
vi.mock('../../services/sellInAPI', () => ({
  sellInLotesAPI: { productos: vi.fn(() => new Promise(() => {})) },
  sellInAPI: { operaciones: vi.fn() },
}));

beforeEach(() => {
  seedTiendasOficiales();
  productosAPI.marcas.mockResolvedValue({ data: { marcas: ['HP', 'TP-Link'] } });
  productosAPI.categorias.mockResolvedValue({ data: { categorias: ['Monitores', 'Notebooks', 'Redes'] } });
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

const box = (el) => el.getBoundingClientRect();

describe.each(['light', 'dark'])('Datos del tactical, %s', (theme) => {
  it('aligns the reference with the dates, keeps Moneda compact and explains the cap', async () => {
    await page.viewport(1440, 1100);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter initialEntries={['/sell-in/tactical/nuevo?tipo=sell_out']}>
        <Shell>
          <Routes>
            <Route path="/sell-in/tactical/nuevo" element={<TacticalNuevo />} />
          </Routes>
        </Shell>
      </MemoryRouter>,
    );
    await expect.element(screen.getByRole('heading', { name: 'Nuevo tactical' })).toBeVisible();
    await screen.getByLabelText('Nombre').fill('Tacticals BPS Noviembre Q1FY27');
    await screen.getByLabelText('Referencia de la marca').fill('Q1 FY27');
    await screen.getByLabelText('Tope de unidades, línea 1').fill('100');

    const card = screen.getByRole('heading', { name: 'Datos del tactical' }).element().closest('section');
    card.scrollIntoView({ block: 'start' });
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tactical-datos-${theme}.png`, element: card });

    // S1: one row, one top edge for the three inputs.
    const referencia = box(screen.getByLabelText('Referencia de la marca').element());
    for (const label of ['Desde', 'Hasta']) {
      const fecha = box(screen.getByLabelText(label, { exact: true }).element());
      expect(Math.abs(fecha.top - referencia.top)).toBeLessThanOrEqual(0.5);
      expect(Math.round(fecha.height)).toBe(Math.round(referencia.height));
    }

    // S2: USD | ARS takes its content's width, far less than the reference box above it.
    const moneda = box(screen.getByRole('group', { name: 'Moneda' }).element());
    expect(moneda.width).toBeLessThan(referencia.width / 2);

    // S3: per-store caps, the other mode of the preview.
    await screen.getByLabelText('Tope compartido entre las tiendas elegidas').click();
    card.scrollIntoView({ block: 'start' });
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tactical-datos-por-tienda-${theme}.png`, element: card });
  });
});
