/**
 * Subir PDF de ventas por fuera — the upload modal in real Chromium with the app's CSS (ODD `vpf-metricas-canal-fe`
 * T3, mockup 3). jsdom proves the flow; this file proves the layout of the two new screens of the modal:
 *  - the salespeople list (preview, L22): one line per salesperson, the amount whole and right-aligned;
 *  - the result: nothing wider than the modal, money never wrapped, the footer on one line.
 *
 * Screenshots (a DEV aid, never a committed baseline) only when `VITE_CARGAS_SHOTS_DIR` is set.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import SubirPdfModal from '../../components/ventasFueraPdf/SubirPdfModal';
import api from '../../services/api';
import { CARGA, PREVIEW } from '../../components/ventasFueraPdf/fixtures';

vi.mock('react-router-dom', () => ({
  useNavigate: () => () => {},
  Link: ({ to, children, ...rest }) => (
    <a href={to} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
}));

const SHOTS_DIR = import.meta.env.VITE_CARGAS_SHOTS_DIR;
const shot = async (name) => {
  if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/${name}.png` });
};

const pdf = (name, kb) => new File([new Uint8Array(kb * 1024)], name, { type: 'application/pdf' });

const oneLine = (el) => el.getClientRects().length === 1 && el.scrollWidth <= el.clientWidth + 1;

async function abrir(theme) {
  await page.viewport(1920, 1080);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
  const screen = await render(
    <SubirPdfModal
      isOpen
      onClose={() => {}}
      onCargado={() => {}}
      archivosIniciales={[pdf('reporte detallada octubre.pdf', 107), pdf('reporte ventas octubre.pdf', 65)]}
    />,
  );
  await userEvent.click(screen.getByRole('button', { name: 'Leer PDF' }));
  await expect.element(screen.getByRole('checkbox', { name: /Lucía Ferreyra/ })).toBeVisible();
  return screen;
}

const modal = () => document.querySelector('.modal-tesla');

describe('SubirPdfModal (visual)', () => {
  beforeEach(() => {
    api.post.mockReset();
    api.post.mockResolvedValueOnce({ data: PREVIEW }).mockResolvedValueOnce({ data: CARGA });
  });

  for (const theme of ['light', 'dark']) {
    it(`1920 ${theme}: the salespeople list keeps each one on one line, amounts whole`, async () => {
      const screen = await abrir(theme);
      await shot(`subir-pdf-preview-${theme}`);
      const filas = [...modal().querySelectorAll('label')].filter((l) => l.querySelector('input[type="checkbox"]'));
      expect(filas).toHaveLength(3);
      for (const fila of filas) {
        expect(fila.getBoundingClientRect().height).toBeLessThan(48);
        const monto = [...fila.querySelectorAll('span')].at(-1);
        expect(oneLine(monto), monto.textContent).toBe(true);
      }
      expect(modal().scrollWidth).toBeLessThanOrEqual(modal().clientWidth + 1);
      screen.unmount();
    });

    it(`1920 ${theme}: the result fits the modal, money unwrapped, footer on one line`, async () => {
      const screen = await abrir(theme);
      await userEvent.click(screen.getByRole('button', { name: /^Importar/ }));
      await expect.element(screen.getByText('Resultado de la carga')).toBeVisible();
      await userEvent.click(screen.getByRole('button', { name: 'Ver comprobantes' }));
      await shot(`subir-pdf-resultado-${theme}`);

      const body = modal().querySelector('.modal-body-tesla');
      expect(body.scrollWidth).toBeLessThanOrEqual(body.clientWidth + 1);
      const montos = [...body.querySelectorAll('span, strong')].filter((el) => /^-?\$ /.test(el.textContent) && el.children.length === 0);
      expect(montos.length).toBeGreaterThan(8);
      expect(montos.filter((el) => el.getClientRects().length !== 1).map((el) => el.textContent)).toEqual([]);
      const footer = modal().querySelector('.modal-footer-tesla');
      // One row: "Subido por" and both buttons share the same vertical band, each on one line.
      const botones = [...footer.querySelectorAll('button')];
      const banda = botones[0].getBoundingClientRect();
      for (const boton of botones) {
        expect(oneLine(boton), boton.textContent).toBe(true);
        expect(Math.abs(boton.getBoundingClientRect().top - banda.top)).toBeLessThan(1);
      }
      const subido = footer.querySelector('span');
      expect(subido.getClientRects()).toHaveLength(1);
      const centro = (r) => r.top + r.height / 2;
      expect(Math.abs(centro(subido.getBoundingClientRect()) - centro(banda))).toBeLessThan(2);
      screen.unmount();
    });
  }
});
