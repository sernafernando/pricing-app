/**
 * Sub-PMs — the save bar and the user list stay on screen however long the
 * marca list gets, and the user list sits beside the detail without
 * overlapping it, in both themes. Real Chromium geometry: jsdom does no layout.
 *
 * Screenshots are written only when `VITE_SUBPMS_SHOTS_DIR` is set (a DEV
 * aid, never a committed baseline).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import MisSubPMs from '../../pages/MisSubPMs';
import { marcasPmAPI } from '../../services/api';

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal()),
  marcasPmAPI: {
    listarTodosLosPares: vi.fn(),
    misTitularidades: vi.fn(),
    listarUsuariosPM: vi.fn(),
    obtenerConteosSubPMs: vi.fn(),
    listarGrantsScope: vi.fn(),
    obtenerGrantsUsuario: vi.fn(),
    asignarSubPMsBulk: vi.fn(),
  },
}));

const SHOTS_DIR = import.meta.env.VITE_SUBPMS_SHOTS_DIR;

const MARCAS = ['ACER', 'APPLE', 'ASUS', 'DELL', 'EPSON', 'HP', 'KINGSTON', 'LENOVO', 'LOGITECH', 'SAMSUNG', 'TP-LINK', 'XIAOMI'];
const CATEGORIAS = ['Monitores', 'Notebooks', 'Impresoras', 'Routers', 'Mouse', 'Teclados'];
const TITULARES = [
  { id: 2, nombre: 'Ramiro Echeverría' },
  { id: 3, nombre: 'Carolina Lépore' },
];

const PARES = MARCAS.flatMap((marca, i) =>
  CATEGORIAS.map((categoria, j) => {
    const titular = TITULARES[(i + j) % TITULARES.length];
    return { id: i * 10 + j, marca, categoria, usuario_id: titular.id, usuario_nombre: titular.nombre };
  }),
);

const USUARIOS = ['Juan Pereyra', 'Sofía Benítez', 'Martín Quiroga', 'Agustina Rolón'].map((nombre, i) => ({
  id: 10 + i,
  nombre,
  email: null,
  rol: 'ventas',
}));

beforeEach(() => {
  marcasPmAPI.listarTodosLosPares.mockResolvedValue({ data: PARES });
  marcasPmAPI.listarUsuariosPM.mockResolvedValue({ data: USUARIOS });
  marcasPmAPI.obtenerConteosSubPMs.mockResolvedValue({ data: { conteos: [{ usuario_id: 10, total: 8 }] } });
  marcasPmAPI.listarGrantsScope.mockResolvedValue({
    data: {
      grants: [{ id: 1, marca: 'LENOVO', categoria: 'Monitores', usuario_id: 11, usuario_nombre: 'Sofía Benítez' }],
    },
  });
  marcasPmAPI.obtenerGrantsUsuario.mockResolvedValue({
    data: {
      pares: [
        ...CATEGORIAS.map((categoria) => ({ marca: 'HP', categoria })),
        { marca: 'SAMSUNG', categoria: 'Monitores' },
        { marca: 'EPSON', categoria: 'Impresoras' },
      ],
      total: 8,
    },
  });
});

describe.each([
  { width: 1366, height: 768, theme: 'light' },
  { width: 1920, height: 1080, theme: 'dark' },
])('Sub-PMs at $width px, $theme', ({ width, height, theme }) => {
  it('keeps the save bar visible with every marca open, beside a non-overlapping user list', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(<MisSubPMs />);

    await screen.getByRole('button', { name: /^Juan Pereyra \(/ }).click();
    await screen.getByLabelText('Seleccionar toda la marca LENOVO').click();
    await screen.getByRole('button', { name: 'Expandir todo' }).click();
    await expect.element(screen.getByText('+6 agregar')).toBeVisible();

    const lista = document.querySelector('aside[aria-label="Usuarios"]').getBoundingClientRect();
    const detalle = screen.getByRole('heading', { name: 'Juan Pereyra' }).element().closest('section').getBoundingClientRect();
    expect(lista.right).toBeLessThanOrEqual(detalle.left + 1);

    // The page is far taller than the viewport once every marca is open.
    expect(document.documentElement.scrollHeight).toBeGreaterThan(height * 2);
    window.scrollTo(0, document.documentElement.scrollHeight / 2);

    const barra = document.querySelector('footer').getBoundingClientRect();
    expect(barra.bottom).toBeLessThanOrEqual(height);
    expect(barra.top).toBeGreaterThanOrEqual(0);

    // The user list sticks to the top too, so another user is one click away.
    const listaScrolleada = document.querySelector('aside[aria-label="Usuarios"]').getBoundingClientRect();
    expect(listaScrolleada.top).toBeGreaterThanOrEqual(0);
    expect(listaScrolleada.top).toBeLessThan(height / 2);

    if (SHOTS_DIR) {
      await page.screenshot({ path: `${SHOTS_DIR}/subpms-${theme}-${width}-scrolled.png` });
      window.scrollTo(0, 0);
      await page.screenshot({ path: `${SHOTS_DIR}/subpms-${theme}-${width}.png` });
    }
  });
});
