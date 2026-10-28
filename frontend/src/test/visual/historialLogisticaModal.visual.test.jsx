/**
 * Envíos Flex logistics history modal -- real CSS, real Chromium (flex-logistica-historial S5).
 *
 * jsdom does no layout, so the unit suite proves the copy and the undo flow, and
 * this file proves the layout promises of the Stitch design:
 *  - logística chips and origin badges never wrap;
 *  - "Deshacer último cambio" and "Confirmar" stay on one line;
 *  - nothing overflows the modal sideways, with the confirmation strip open.
 *
 *   pnpm exec vitest run --project=visual historialLogisticaModal
 *   VITE_HISTORIAL_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual historialLogisticaModal   (also saves screenshots)
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import HistorialLogisticaModal from '../../components/enviosFlex/HistorialLogisticaModal';

const RAYO = { id: 1, nombre: 'Rayo Express', color: '#2563eb' };
const MOTO = { id: 2, nombre: 'Moto Sur Logística Integral', color: '#16a34a' };
const FLASH = { id: 3, nombre: 'Flash Envíos', color: '#f59e0b' };

const cambio = (id, hora, origen, anterior, nueva, usuario, operador) => ({
  id,
  cambiado_en: new Date(2026, 9, 27, hora, 15).toISOString(),
  origen,
  anterior,
  nueva,
  usuario_nombre: usuario,
  operador_nombre: operador,
});

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(async () => ({
      data: {
        shipping_id: '44812345678',
        logistica_actual: RAYO,
        puede_deshacer: true,
        deshacer_a: MOTO,
        cambios: [
          cambio(5, 14, 'deshacer', MOTO, RAYO, 'Juan Pérez', 'Carla Fernández'),
          cambio(4, 13, 'pistoleado', FLASH, MOTO, 'Juan Pérez', 'Carla'),
          cambio(3, 12, 'masivo', RAYO, FLASH, 'Ana Gómez', null),
          cambio(2, 11, 'manual', null, RAYO, 'María Laura Rodríguez Etchegaray', 'Operador de turno noche'),
          cambio(1, 9, null, null, null, null, null),
        ],
      },
    })),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
}));

const SHOTS_DIR = import.meta.env.VITE_HISTORIAL_SHOTS_DIR;

const expectOneLine = (el, maxHeight) => {
  expect(el.getBoundingClientRect().height).toBeLessThanOrEqual(maxHeight);
  expect(el.scrollWidth).toBeLessThanOrEqual(el.clientWidth + 1);
};

describe('HistorialLogisticaModal (visual)', () => {
  for (const [width, height] of [
    [1280, 800],
    [1920, 1080],
  ]) {
    for (const theme of ['light', 'dark']) {
      it(`keeps chips, badges and buttons on one line at ${width}px, ${theme}`, async () => {
        await page.viewport(width, height);
        setTheme(theme);
        document.body.style.background = 'var(--cf-bg-app)';
        const screen = await render(
          <HistorialLogisticaModal shippingId="44812345678" puedeDeshacer operadorId={7} onClose={() => {}} />,
        );
        await expect.element(screen.getByText('Ana Gómez')).toBeVisible();

        await userEvent.click(screen.getByRole('button', { name: /Deshacer último cambio/ }));
        await expect.element(screen.getByRole('group', { name: 'Confirmar deshacer' })).toBeVisible();

        const modal = document.querySelector('.modal-tesla');
        const chips = [...modal.querySelectorAll('span[class*="chip"]')].filter(
          (el) => !/envioChip/.test(el.className),
        );
        // 1 current + 5 rows x 2 + 1 in the confirmation strip.
        expect(chips.length).toBe(12);
        for (const chip of chips) expectOneLine(chip, 32);
        for (const badge of modal.querySelectorAll('span[class*="origen"]')) expectOneLine(badge, 28);
        for (const name of ['Deshacer último cambio', 'Confirmar', 'Cancelar', 'Cerrar']) {
          const button = [...modal.querySelectorAll('button')].find((b) => b.textContent.trim() === name);
          expectOneLine(button, 40);
        }

        const modalRect = modal.getBoundingClientRect();
        expect(modal.scrollWidth).toBeLessThanOrEqual(modal.clientWidth + 1);
        for (const row of modal.querySelectorAll('li')) {
          expect(row.getBoundingClientRect().right).toBeLessThanOrEqual(modalRect.right);
        }
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);

        if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/historial-logistica-${theme}-${width}.png` });
      });
    }
  }
});
