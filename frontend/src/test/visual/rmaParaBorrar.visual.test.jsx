/**
 * RMA "Para borrar" grouped by operation -- real CSS, real Chromium: a row with two cases of one ML cart lists both
 * case numbers and both articles one per line, with the shipping number, inside the table and without overflowing
 * it, in light and dark.
 *
 *   pnpm exec vitest run --project=visual rmaParaBorrar
 *   VITE_RMA_BORRAR_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual rmaParaBorrar   (also saves screenshots)
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import api from '../../services/api';
import RmaParaBorrar from '../../pages/rma/RmaParaBorrar';

vi.mock('../../services/api', () => ({ default: { get: vi.fn(), put: vi.fn() } }));

const SHOTS_DIR = import.meta.env.VITE_RMA_BORRAR_SHOTS_DIR;

const caso = (id, numero, articulo, revisado) => ({
  id,
  numero_caso: numero,
  cliente_nombre: 'Juan Pérez',
  ml_id: '2000000000000002',
  estado: 'Abierto',
  fecha_caso: '2026-11-04',
  borrar_revisado_at: revisado ? '2026-11-05T15:00:00Z' : null,
  borrar_revisado_por_nombre: revisado ? 'Ana' : null,
  articulos: [articulo],
});

const OPERACIONES = [
  {
    clave: 'op:2000000000000001',
    ml_id: '2000000000000002',
    numero_envio: '40000000001',
    cliente_nombre: 'Juan Pérez',
    revisado: false,
    casos: [
      caso(12, 'RMA-2026-0012', 'Repetidor de señal TP-Link RE200 AC750', true),
      caso(11, 'RMA-2026-0011', 'Router TP-Link Archer AX1500 WiFi 6', false),
    ],
  },
  {
    clave: 'ml:ML-998877',
    ml_id: 'ML-998877',
    numero_envio: null,
    cliente_nombre: 'María Gómez',
    revisado: false,
    casos: [caso(9, 'RMA-2026-0009', 'Mouse inalámbrico Logitech M170', false)],
  },
];

describe('RmaParaBorrar grouped rows (visual)', () => {
  for (const theme of ['light', 'dark']) {
    it(`lists the cases and articles of one operation one per line, ${theme}`, async () => {
      await page.viewport(1280, 700);
      setTheme(theme);
      document.body.style.background = 'var(--cf-bg-app)';
      api.get.mockResolvedValue({ data: { items: OPERACIONES, counts: { pendientes: 2, revisados: 0, todos: 2 } } });
      await render(
        <div data-testid="pagina" style={{ padding: 16 }}>
          <RmaParaBorrar puedeGestionar />
        </div>,
      );
      await expect.element(page.getByText('RMA-2026-0011')).toBeVisible();

      const primero = page.getByText('RMA-2026-0012').element().getBoundingClientRect();
      const segundo = page.getByText('RMA-2026-0011').element().getBoundingClientRect();
      expect(segundo.top).toBeGreaterThan(primero.top); // one case per line
      const tabla = document.querySelector('table');
      expect(tabla.getBoundingClientRect().right).toBeLessThanOrEqual(1280);
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/rma-para-borrar-${theme}.png` });
    });
  }
});
