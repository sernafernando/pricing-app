/**
 * Tacticals approval (handoffs/tacticals-aprobacion-plan.md S8) -- real CSS, real Chromium: the Tacticals tab on
 * "Pendientes de aprobación", a pending row with its warning pill, an approved row naming its approver under the
 * state, and the Aprobar confirmation, inside the window at 1440, light and dark.
 *
 *   VITE_TACTICALS_APROBACION_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual tacticalsAprobacion
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import SellIn from '../../pages/SellIn';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import { KPIS_COBRANZA, TACTICAL_BPS, TACTICAL_REBATE, pagina } from '../../components/tacticals/tacticalsFixtures';

const SHOTS_DIR = import.meta.env.VITE_TACTICALS_APROBACION_SHOTS_DIR;

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  productosAPI: { marcas: vi.fn().mockResolvedValue({ data: { marcas: ['HP', 'Lenovo', 'TP-Link'] } }), listar: vi.fn() },
}));

vi.mock('../../services/sellInAPI', () => ({
  sellInLotesAPI: { productos: vi.fn(() => new Promise(() => {})) },
  sellInAPI: { listar: vi.fn(), resumen: vi.fn(), detalle: vi.fn() },
  sellInBonosAPI: { listar: vi.fn(), detalle: vi.fn() },
}));

vi.mock('../../services/sellOutAPI', () => ({
  sellOutAPI: { listar: vi.fn(), detalle: vi.fn(), grupos: vi.fn(), consumos: vi.fn() },
}));

vi.mock('../../services/tacticalsAPI', () => ({
  tacticalsAPI: { listar: vi.fn(), editar: vi.fn(), anular: vi.fn(), aprobar: vi.fn(), cobrar: vi.fn(), deshacerCobro: vi.fn() },
}));

const PENDIENTE = { ...TACTICAL_BPS, estado: 'pendiente', lineas: TACTICAL_BPS.lineas.map((l) => ({ ...l, estado: 'pendiente' })) };
const APROBADO = { ...TACTICAL_REBATE, aprobado_por: 9, aprobado_por_nombre: 'Alejandro', aprobado_at: '2026-11-10T15:00:00Z' };

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

describe.each([
  { width: 1440, height: 1000, theme: 'light' },
  { width: 1440, height: 1000, theme: 'dark' },
])('Tacticals approval at $width px, $theme', ({ width, height, theme }) => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date(2026, 10, 12, 10));
    tacticalsAPI.listar.mockResolvedValue({ data: { ...pagina([PENDIENTE, APROBADO]), kpis: KPIS_COBRANZA } });
  });

  const abrir = async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    return render(
      <MemoryRouter initialEntries={['/sell-in?tab=tacticals']}>
        <Shell>
          <SellIn />
        </Shell>
      </MemoryRouter>,
    );
  };

  it('filters the pending ones: the pending pill and the approver fit their cell', async () => {
    const screen = await abrir();
    await screen.getByRole('button', { name: 'Pendientes de aprobación' }).click();
    await expect.poll(() => tacticalsAPI.listar.mock.calls.some(([p]) => p.estado === 'pendientes_aprobacion')).toBe(true);

    const fila = screen.getByRole('row', { name: /Tacticals BPS Noviembre Q1FY27/ });
    await expect.element(fila.getByText('Pendiente de aprobación')).toBeVisible();
    const aprobado = screen.getByText('Aprobado por Alejandro el 10/11/2026');
    await expect.element(aprobado).toBeVisible();
    // The approver line stays inside its cell: no overflow over the Cobranza column.
    const texto = aprobado.element().getBoundingClientRect();
    const celda = aprobado.element().closest('td').getBoundingClientRect();
    expect(texto.right).toBeLessThanOrEqual(celda.right + 0.5);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tacticals-pendientes-${theme}-${width}.png` });
  });

  it('Aprobar opens its confirmation inside the window', async () => {
    const screen = await abrir();
    await screen.getByRole('button', { name: 'Acciones de Tacticals BPS Noviembre Q1FY27' }).click();
    await screen.getByRole('menuitem', { name: 'Aprobar' }).click();

    const dialogo = screen.getByRole('dialog', { name: '¿Aprobar Tacticals BPS Noviembre Q1FY27?' });
    await expect.element(dialogo).toBeVisible();
    await expect.element(dialogo.getByRole('button', { name: 'Aprobar tactical' })).toBeVisible();
    const caja = dialogo.element().getBoundingClientRect();
    expect(caja.top).toBeGreaterThanOrEqual(0);
    expect(caja.right).toBeLessThanOrEqual(width + 0.5);
    expect(caja.bottom).toBeLessThanOrEqual(height + 0.5);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tacticals-aprobar-${theme}-${width}.png` });
  });
});
