/**
 * The Grupos tab of Sell in / Sell out with "Borrar seleccionados" (tactical S9): a checkbox per group, the button
 * next to "Nuevo grupo", the inline confirmation and the result above the table, in both themes. Real Chromium
 * geometry: jsdom does no layout.
 *
 *   VITE_GRUPOS_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual gruposBorrarSeleccionados   (also saves screenshots)
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import GruposTab from '../../components/grupos/GruposTab';
import { offsetGruposAPI } from '../../services/offsetGruposAPI';

const SHOTS_DIR = import.meta.env.VITE_GRUPOS_SHOTS_DIR;

vi.mock('../../services/offsetGruposAPI', () => ({
  offsetGruposAPI: { listar: vi.fn(), alcance: vi.fn(), opciones: vi.fn(), eliminarVarios: vi.fn() },
}));

const filtro = (id, grupo_id, campos) => ({ id, grupo_id, marca: null, categoria: null, subcategoria_id: null, item_id: null, producto_descripcion: null, ...campos });
const GRUPOS = [
  { id: 1, nombre: 'TP-Link redes', descripcion: 'Routers y switches', filtros: [filtro(11, 1, { marca: 'TP-LINK', categoria: 'Routers' })] },
  { id: 2, nombre: 'Epson tintas', descripcion: null, filtros: [filtro(21, 2, { marca: 'EPSON', categoria: 'Tintas' })] },
  { id: 3, nombre: 'Sin filtros', descripcion: null, filtros: [] },
];
const ALCANCE = [
  { grupo_id: 1, productos: 42, campanas: [{ id: 5, nombre: 'Noviembre TP-Link', estado: 'activa' }] },
  { grupo_id: 2, productos: 18, campanas: [] },
  { grupo_id: 3, productos: 0, campanas: [] },
];
const RECHAZO = 'El grupo está asignado a la campaña de sell out activa «Noviembre TP-Link». Quite el grupo de la campaña antes de eliminarlo.';

beforeEach(() => {
  vi.clearAllMocks();
  offsetGruposAPI.listar.mockResolvedValue({ data: GRUPOS });
  offsetGruposAPI.alcance.mockResolvedValue({ data: ALCANCE });
  offsetGruposAPI.opciones.mockResolvedValue({ data: { marcas: [], categorias: [], subcategorias: [] } });
  offsetGruposAPI.eliminarVarios.mockResolvedValue({ data: { eliminados: [2, 3], rechazados: [{ id: 1, nombre: 'TP-Link redes', motivo: RECHAZO }] } });
});

const box = (el) => el.getBoundingClientRect();

describe.each([
  { width: 1366, height: 768, theme: 'light' },
  { width: 1366, height: 768, theme: 'dark' },
])('Grupos at $width px, $theme', ({ width, height, theme }) => {
  it('checks groups, confirms inline above the table and shows what stayed and why, inside the viewport', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter>
        <div style={{ padding: 'var(--space-4)' }}>
          <GruposTab />
        </div>
      </MemoryRouter>,
    );
    await expect.element(screen.getByText('Routers y switches')).toBeVisible();
    for (const nombre of ['TP-Link redes', 'Epson tintas', 'Sin filtros']) await screen.getByRole('checkbox', { name: `Seleccionar ${nombre}` }).click();
    const boton = screen.getByRole('button', { name: 'Borrar seleccionados (3)' });
    await expect.element(boton).toBeVisible();
    const nuevo = box(screen.getByRole('button', { name: /Nuevo grupo/ }).element());
    expect(Math.abs(box(boton.element()).top - nuevo.top)).toBeLessThan(2); // same toolbar row
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/grupos-seleccionados-${theme}-${width}.png` });

    await boton.click();
    const confirmar = screen.getByRole('group', { name: 'Confirmar borrado' });
    await expect.element(confirmar).toBeVisible();
    expect(box(confirmar.element()).bottom).toBeLessThanOrEqual(box(document.querySelector('table')).top + 0.5);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/grupos-confirmar-${theme}-${width}.png` });

    await confirmar.getByRole('button', { name: 'Borrar 3 grupos' }).click();
    const resultado = screen.getByRole('status');
    await expect.element(resultado).toHaveTextContent('Se borraron 2 grupos.');
    expect(box(resultado.element()).bottom).toBeLessThanOrEqual(box(document.querySelector('table')).top + 0.5);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/grupos-resultado-${theme}-${width}.png` });
  });
});
