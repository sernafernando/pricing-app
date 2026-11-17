/**
 * Envíos Flex mass undo and overwrite guard modals -- real CSS, real Chromium (flex-deshacer-masivo S2-S4).
 *
 * The unit suite proves the copy and the flows; this file proves the layout:
 *  - logística chips, dates, counts and buttons never wrap;
 *  - nothing overflows the modal sideways (list, result with long shipping id lists, confirmation strip).
 *
 *   pnpm exec vitest run --project=visual deshacerMasivoEnviosFlex
 *   VITE_DESHACER_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual deshacerMasivoEnviosFlex   (also saves screenshots)
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import OperacionesMasivasModal from '../../components/enviosFlex/OperacionesMasivasModal';
import DeshacerSeleccionModal from '../../components/enviosFlex/DeshacerSeleccionModal';
import SobrescribirLogisticaModal from '../../components/enviosFlex/SobrescribirLogisticaModal';

const RAYO = { id: 1, nombre: 'Rayo Express', color: '#2563eb' };
const MOTO = { id: 2, nombre: 'Moto Sur Logística Integral', color: '#16a34a' };
const PLACEHOLDER = { id: 5, nombre: 'A DESIGNAR', color: null };

const op = (id, hora, usuario, logistica, etiquetas) => ({
  id,
  usuario_nombre: usuario,
  cambiado_en: new Date(2026, 10, 17, hora, 12).toISOString(),
  logistica,
  etiquetas,
});

const ids = (desde, n) => Array.from({ length: n }, (_, i) => String(44800000000 + desde + i));

const RESULTADO = {
  revertidas: 112,
  no_revertidas: 14,
  no_revertidas_por_motivo: [
    { motivo: 'La etiqueta cambió de logística después de esta operación.', cantidad: 12, shipping_ids: ids(100, 12) },
    { motivo: 'La logística anterior está inactiva.', cantidad: 2, shipping_ids: ids(200, 2) },
  ],
};

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(async () => ({
      data: [
        op(41, 14, 'Ana Gómez', PLACEHOLDER, 126),
        op(38, 12, 'María Laura Rodríguez Etchegaray', MOTO, 48),
        op(30, 9, null, RAYO, 1),
      ],
    })),
    post: vi.fn(async () => ({ data: RESULTADO })),
    put: vi.fn(async () => ({ data: { actualizadas: 5, salteadas: 3 } })),
    delete: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
}));

const SHOTS_DIR = import.meta.env.VITE_DESHACER_SHOTS_DIR;

const expectOneLine = (el, maxHeight) => {
  expect(el.getBoundingClientRect().height).toBeLessThanOrEqual(maxHeight);
  expect(el.scrollWidth).toBeLessThanOrEqual(el.clientWidth + 1);
};

const expectNoSidewaysOverflow = (width) => {
  const modal = document.querySelector('.modal-tesla');
  expect(modal.scrollWidth).toBeLessThanOrEqual(modal.clientWidth + 1);
  const right = modal.getBoundingClientRect().right;
  for (const el of modal.querySelectorAll('li, button')) {
    expect(el.getBoundingClientRect().right).toBeLessThanOrEqual(right);
  }
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
  return modal;
};

const shot = async (name) => {
  if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/${name}.png` });
};

const preparar = async (theme) => {
  await page.viewport(1280, 800);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
};

describe('Envíos Flex mass undo modals (visual)', () => {
  for (const theme of ['light', 'dark']) {
    it(`bulk assignments list, confirmation and result, ${theme}`, async () => {
      await preparar(theme);
      const screen = await render(<OperacionesMasivasModal operadorId={7} onClose={() => {}} />);
      await expect.element(screen.getByText('Ana Gómez')).toBeVisible();

      let modal = expectNoSidewaysOverflow(1280);
      for (const chip of modal.querySelectorAll('span[class*="chip"]')) expectOneLine(chip, 32);
      for (const fecha of modal.querySelectorAll('span[class*="fecha"]')) expectOneLine(fecha, 28);
      await shot(`masivas-lista-${theme}`);

      await userEvent.click(screen.getByRole('button', { name: /Deshacer la asignación del 17\/11 14:12/ }));
      await expect.element(screen.getByRole('group', { name: 'Confirmar deshacer operación' })).toBeVisible();
      expectNoSidewaysOverflow(1280);
      await shot(`masivas-confirmar-${theme}`);

      await userEvent.click(screen.getByRole('button', { name: /Confirmar/ }));
      await expect.element(screen.getByRole('status')).toBeVisible();
      modal = expectNoSidewaysOverflow(1280);
      for (const button of modal.querySelectorAll('button')) expectOneLine(button, 40);
      await shot(`masivas-resultado-${theme}`);
    });

    it(`selection undo, confirmation and result, ${theme}`, async () => {
      await preparar(theme);
      const screen = await render(
        <DeshacerSeleccionModal shippingIds={ids(0, 126)} operadorId={7} onClose={() => {}} />,
      );
      await expect.element(screen.getByText(/126 etiquetas seleccionadas/)).toBeVisible();
      let modal = expectNoSidewaysOverflow(1280);
      for (const button of modal.querySelectorAll('button')) expectOneLine(button, 40);
      await shot(`seleccion-confirmar-${theme}`);

      await userEvent.click(screen.getByRole('button', { name: /Deshacer 126 etiquetas/ }));
      await expect.element(screen.getByRole('status')).toBeVisible();
      modal = expectNoSidewaysOverflow(1280);
      await shot(`seleccion-resultado-${theme}`);
    });

    it(`overwrite guard and its only-without result, ${theme}`, async () => {
      await preparar(theme);
      const screen = await render(
        <SobrescribirLogisticaModal
          shippingIds={ids(0, 8)}
          logistica={MOTO}
          sobrescribiria={3}
          onClose={() => {}}
        />,
      );
      await expect.element(screen.getByText(/3 de las 8 etiquetas/)).toBeVisible();
      const modal = expectNoSidewaysOverflow(1280);
      for (const button of modal.querySelectorAll('button')) expectOneLine(button, 40);
      await shot(`sobrescribir-aviso-${theme}`);

      await userEvent.click(screen.getByRole('button', { name: /Solo las sin logística/ }));
      await expect.element(screen.getByRole('status')).toBeVisible();
      expectNoSidewaysOverflow(1280);
      await shot(`sobrescribir-resultado-${theme}`);
    });
  }
});
