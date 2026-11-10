/**
 * Collection check of the tacticals (handoffs/tactical-cobranza-tarea.md S3-S5): the Tacticals tab with the Cobranza
 * filter, the Pendientes / Cobrados KPIs, the Cobranza column and one row's box open, once per medium. Stitch failed
 * (internal error twice), so these captures are what the owner approves. Real Chromium geometry: jsdom does no layout.
 *
 *   VITE_SELLINOUT_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual tacticalCobranza   (also saves screenshots)
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import SellIn from '../../pages/SellIn';
import { sellInAPI, sellInBonosAPI } from '../../services/sellInAPI';
import { BONOS_LISTA, LISTA, RESUMEN } from '../../components/sellIn/sellInFixtures';
import { sellOutAPI } from '../../services/sellOutAPI';
import { CAMPANAS_LISTA } from '../../components/sellOut/sellOutFixtures';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import {
  COBRANZA_FONDO,
  KPIS_COBRANZA,
  TACTICAL_BPS,
  TACTICAL_REBATE,
  lineaDeProducto,
  pagina,
} from '../../components/tacticals/tacticalsFixtures';

const SHOTS_DIR = import.meta.env.VITE_SELLINOUT_SHOTS_DIR;

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
  tacticalsAPI: { listar: vi.fn(), editar: vi.fn(), anular: vi.fn(), cobrar: vi.fn(), deshacerCobro: vi.fn() },
}));

const MONITORES = {
  ...TACTICAL_BPS,
  id: 2,
  nombre: 'Monitores HP noviembre',
  referencia: null,
  fecha_hasta: '2026-11-15',
  lineas: [{ ...lineaDeProducto(21, 201, 'MON-V24I', 'Monitor HP V24i G5', 12, 180, 172), tope_monto: '2160' }],
};

const COBRANZAS = {
  nota_credito: { ...COBRANZA_FONDO, medio: 'nota_credito', nc_numero: '0003-00012345', distribuidor: null,
                  observaciones: 'NC aplicada a la factura de noviembre' },  // prettier-ignore
  fondo_distribuidor: COBRANZA_FONDO,
  otro: { ...COBRANZA_FONDO, medio: 'otro', distribuidor: null, otro_detalle: 'Transferencia directa de la marca',
          observaciones: null },  // prettier-ignore
};

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

describe.each([
  { width: 1440, height: 1000, theme: 'light' },
  { width: 1440, height: 1000, theme: 'dark' },
])('Tacticals cobranza at $width px, $theme', ({ width, height, theme }) => {
  describe.each(Object.keys(COBRANZAS))('medio %s', (medio) => {
    beforeEach(() => {
      vi.useFakeTimers({ toFake: ['Date'] });
      vi.setSystemTime(new Date(2026, 10, 12, 10));
      const items = [TACTICAL_BPS, MONITORES, { ...TACTICAL_REBATE, cobranza: COBRANZAS[medio] }];
      tacticalsAPI.listar.mockResolvedValue({ data: { ...pagina(items), kpis: KPIS_COBRANZA } });
      sellOutAPI.listar.mockResolvedValue({ data: CAMPANAS_LISTA });
      sellOutAPI.grupos.mockResolvedValue({ data: [] });
      sellInAPI.listar.mockResolvedValue({ data: LISTA });
      sellInAPI.resumen.mockResolvedValue({ data: RESUMEN });
      sellInBonosAPI.listar.mockResolvedValue({ data: BONOS_LISTA });
    });

    it('shows the KPIs, the column and the open box with its medium field, inside the window', async () => {
      await page.viewport(width, height);
      setTheme(theme);
      document.body.style.background = 'var(--cf-bg-app)';
      const screen = await render(
        <MemoryRouter initialEntries={['/sell-in?tab=tacticals']}>
          <Shell>
            <SellIn />
          </Shell>
        </MemoryRouter>,
      );

      await expect.element(screen.getByRole('region', { name: 'Cobranza de los tacticals' })).toBeVisible();
      await screen.getByRole('button', { name: 'Editar cobro de Rebate HP Q1FY27' }).click();
      const campo = { nota_credito: 'Número de NC', fondo_distribuidor: 'Distribuidor', otro: 'Detalle' }[medio];
      await expect.element(screen.getByLabelText(campo)).toBeVisible();
      await expect.element(screen.getByRole('button', { name: 'Deshacer cobro' })).toBeVisible();
      // The page is taller than the window: the box is under the last row, so it is scrolled to, as a user would.
      document.querySelector('form[aria-label^="Cobranza de"]').scrollIntoView({ block: 'end' });
      const caja = document.querySelector('form[aria-label^="Cobranza de"]').getBoundingClientRect();
      expect(caja.top).toBeGreaterThanOrEqual(0);
      expect(caja.right).toBeLessThanOrEqual(width + 0.5);
      expect(caja.bottom).toBeLessThanOrEqual(height + 0.5);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tactical-cobranza-${medio}-${theme}-${width}.png` });
    });
  });
});
