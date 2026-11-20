/**
 * "Acciones IA" (#2351 UI review) -- the real page next to the real sidebar, real CSS, real Chromium, invented data:
 * at 1440 with the sidebar expanded the table fits with no horizontal scroll (Resultado and Deshacer on screen), and
 * the undo dialog's Confirmar meets WCAG AA contrast in both themes. With `VITE_ACCIONES_IA_SHOTS_DIR` it also takes
 * the review screenshots.
 *
 *   VITE_ACCIONES_IA_SHOTS_DIR=<dir> run_tests.sh frontend src/test/visual/accionesIa.visual.test.jsx
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { contrastRatio, rgba, setTheme } from './visualHelpers';
import api from '../../services/api';
import AccionesIa from '../../pages/AccionesIa';
import Sidebar from '../../components/Sidebar';
import layout from '../../components/AppLayout.module.css';

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, tieneAlgunPermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const SHOTS_DIR = import.meta.env.VITE_ACCIONES_IA_SHOTS_DIR;
const WIDTH = 1440;
const HEIGHT = 900;

const fila = (over) => ({
  id: 41,
  plan_id: 'p_7f3a',
  created_at: '2026-11-19T14:05:00Z',
  usuario_id: 3,
  usuario_nombre: 'Usuario Demo',
  cliente: 'Claude',
  tool: 'precio_lista_cambiar',
  accion: 'precio_lista',
  objetivo: '12345',
  objetivo_label: 'SKU 12345 - Notebook Demo 14"',
  antes: { precio: 1250000 },
  despues: { precio: 1187500 },
  motivo: 'Bajar 5% para alinear con la competencia (pedido del PM)',
  resultado: 'ok',
  detalle: null,
  deshacible: true,
  deshecha: false,
  undo_of_id: null,
  ...over,
});

const ITEMS = [
  fila(),
  fila({ id: 42, objetivo: '23456', objetivo_label: 'SKU 23456 - Mouse Inalámbrico Demo', antes: { precio: 18900 }, despues: { precio: 19800 } }),
  fila({
    id: 43,
    plan_id: 'p_91bc',
    created_at: '2026-11-19T13:40:00Z',
    cliente: 'Cursor',
    tool: 'promos_aplicar_mejoras',
    accion: 'promo_aplicar',
    objetivo: 'MLA1000000001',
    objetivo_label: 'MLA1000000001 - Teclado Mecánico Demo',
    antes: { promo: 'ninguna', markup: 12.4 },
    despues: { promo: 'DEAL', precio: 54990, markup: 17.6 },
    motivo: 'Aplicar las promos que mejoran 5 puntos o más',
  }),
  fila({
    id: 44,
    plan_id: 'p_91bc',
    created_at: '2026-11-19T13:40:00Z',
    cliente: 'Cursor',
    tool: 'promos_aplicar_mejoras',
    accion: 'promo_aplicar',
    objetivo: 'MLA1000000002',
    objetivo_label: 'MLA1000000002 - Auriculares Demo',
    antes: { promo: 'ninguna', markup: 9.1 },
    despues: { promo: 'SMART', precio: 32500, markup: 15.0 },
    motivo: 'Aplicar las promos que mejoran 5 puntos o más',
  }),
  fila({
    id: 45,
    plan_id: 'p_2d10',
    created_at: '2026-11-19T12:10:00Z',
    cliente: 'Gemini CLI',
    tool: 'precio_mayorista_cambiar',
    accion: 'precio_mayorista',
    objetivo: 'MLA1000000003',
    objetivo_label: 'MLA1000000003 - Monitor Demo 27"',
    antes: { 'tramo 5+': 289000, 'tramo 10+': 279000, 'tramo 20+': 269000 },
    despues: { 'tramo 5+': 299000, 'tramo 10+': 289000, 'tramo 20+': 279000 },
    motivo: 'Subir mayorista 3,5% por aumento de costo',
  }),
  fila({
    id: 46,
    plan_id: 'p_5e77',
    created_at: '2026-11-19T11:30:00Z',
    cliente: 'ChatGPT',
    tool: 'publicaciones_estado',
    accion: 'estado_pausar',
    objetivo: 'MLA1000000004',
    objetivo_label: 'MLA1000000004 - Silla Gamer Demo',
    antes: { estado: 'active' },
    despues: { estado: 'paused' },
    motivo: 'Sin stock hasta el lunes',
    deshecha: true,
  }),
  fila({
    id: 47,
    plan_id: 'p_5e77',
    created_at: '2026-11-19T11:45:00Z',
    cliente: 'Aplicación',
    tool: 'accion_deshacer',
    accion: 'estado_activar',
    objetivo: 'MLA1000000004',
    objetivo_label: 'MLA1000000004 - Silla Gamer Demo',
    antes: { estado: 'paused' },
    despues: { estado: 'active' },
    motivo: 'Entró stock antes de lo previsto',
    deshacible: false,
    undo_of_id: 46,
  }),
  fila({
    id: 48,
    plan_id: 'p_c044',
    created_at: '2026-11-19T10:15:00Z',
    tool: 'precio_cuotas_cambiar',
    accion: 'precio_cuota',
    objetivo: '34567:clasica:6',
    objetivo_label: 'SKU 34567 - Parlante Demo (6 cuotas)',
    antes: { precio: 74900 },
    despues: { precio: 74900 },
    motivo: 'Alinear 6 cuotas',
    resultado: 'rechazada',
    detalle: 'el precio cambió entre el plan y la confirmación',
    deshacible: false,
  }),
];

const PLAN = {
  plan_id: 'p_undo',
  confirm_token: 'demo-token',
  expires_at: '2026-11-19T14:30:00Z',
  filas: [
    {
      accion_id: 43,
      objetivo: 'MLA1000000001',
      objetivo_label: 'MLA1000000001 - Teclado Mecánico Demo',
      accion: 'promo_quitar',
      antes: { promo: 'DEAL', precio: 54990 },
      despues: { promo: 'ninguna' },
      estado: 'lista',
      detalle: null,
    },
    {
      accion_id: 44,
      objetivo: 'MLA1000000002',
      objetivo_label: 'MLA1000000002 - Auriculares Demo',
      accion: 'promo_quitar',
      antes: { promo: 'SMART', precio: 32500 },
      despues: { promo: 'ninguna' },
      estado: 'bloqueada',
      detalle: 'ML ya no ofrece esa promo',
    },
  ],
};

let escritura;

beforeEach(() => {
  escritura = { habilitado: true, fuente: 'db' };
  vi.spyOn(api, 'get').mockImplementation((url) => {
    if (url === '/admin/mcp/escritura') return Promise.resolve({ data: escritura });
    if (url === '/admin/mcp/acciones') return Promise.resolve({ data: { total: ITEMS.length, items: ITEMS } });
    return Promise.resolve({ data: [] });
  });
  vi.spyOn(api, 'post').mockImplementation((url) =>
    url === '/admin/mcp/acciones/deshacer/plan' ? Promise.resolve({ data: PLAN }) : Promise.resolve({ data: {} }),
  );
  vi.spyOn(api, 'put').mockImplementation((_url, body) =>
    Promise.resolve({ data: { habilitado: body.habilitado, fuente: 'db' } }),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

const ROOT_ID = 'capturas-root';

// Full-screen shots clip to the 1440x900 window (the runner's frame is taller than the viewport).
const shot = async (name, element) => {
  if (!SHOTS_DIR) return;
  await page.screenshot({ path: `${SHOTS_DIR}/${name}.png`, element: element || document.getElementById(ROOT_ID) });
};

// The app's own layout: sidebar + content offset by the sidebar width (AppLayout), without the top bar.
const renderPage = (withSidebar = false) =>
  render(
    <MemoryRouter initialEntries={['/acciones-ia']}>
      <div id={ROOT_ID} className={layout.appLayout} style={{ height: '100vh', overflow: 'hidden' }}>
        {withSidebar && <Sidebar />}
        <div className={layout.mainWrapper} data-sidebar-expanded="true" data-sidebar-hidden={String(!withSidebar)}>
          <main className={layout.mainContent} style={{ marginTop: 0 }}>
            <AccionesIa />
          </main>
        </div>
      </div>
    </MemoryRouter>,
  );

// What paints behind `el`: its own fill (each stop of a gradient) composited over the first opaque ancestor.
const fondosDetras = (el) => {
  let base = null;
  for (let nodo = el.parentElement; nodo && !base; nodo = nodo.parentElement) {
    const color = getComputedStyle(nodo).backgroundColor;
    if (rgba(color)[3] === 1) base = rgba(color);
  }
  base = base || [255, 255, 255, 1];
  const estilo = getComputedStyle(el);
  const capas = estilo.backgroundImage.includes('gradient')
    ? estilo.backgroundImage.match(/rgba?\([^)]+\)/g)
    : [estilo.backgroundColor];
  return capas.map((capa) => {
    const [r, g, b, a] = rgba(capa);
    const mezcla = [r, g, b].map((v, i) => Math.round(v * a + base[i] * (1 - a)));
    return `rgb(${mezcla.join(', ')})`;
  });
};

const rowOf = (text) => page.getByRole('row').filter({ hasText: text });

describe.each(['light', 'dark'])('Acciones IA (%s)', (theme) => {
  beforeEach(async () => {
    await page.viewport(WIDTH, HEIGHT);
    setTheme(theme);
  });

  it('list: fits at 1440 next to the expanded sidebar, Resultado and Deshacer on screen', async () => {
    renderPage(true);
    await expect.element(page.getByText('SKU 12345 - Notebook Demo 14"')).toBeVisible();
    const contenedor = document.querySelector('.table-container-tesla');
    expect(contenedor.scrollWidth).toBeLessThanOrEqual(contenedor.clientWidth);
    const borde = contenedor.getBoundingClientRect().right;
    for (const boton of page.getByRole('button', { name: /^Deshacer/ }).elements()) {
      expect(boton.getBoundingClientRect().right).toBeLessThanOrEqual(borde);
    }
    for (const celda of page.getByText(/^(OK|Rechazada)$/).elements()) {
      expect(celda.getBoundingClientRect().right).toBeLessThanOrEqual(borde);
    }
    await shot(`lista-${theme}`);
  });

  it('antes/después detail', async () => {
    renderPage();
    const row = rowOf('Monitor Demo 27');
    await expect.element(row).toBeVisible();
    await shot(`antes-despues-mayorista-${theme}`, row.element());
    const promo = rowOf('Teclado Mecánico Demo');
    await shot(`antes-despues-promo-${theme}`, promo.element());
  });

  it('undo modal: Confirmar meets AA contrast', async () => {
    renderPage(true);
    await expect.element(page.getByText('SKU 12345 - Notebook Demo 14"')).toBeVisible();
    await rowOf('Teclado Mecánico Demo').getByRole('button', { name: 'Deshacer plan' }).click();
    const dialog = page.getByRole('dialog');
    await expect.element(dialog).toBeVisible();
    await userEvent.fill(dialog.getByRole('textbox'), 'La promo bajó el precio más de lo acordado');
    await shot(`modal-deshacer-motivo-${theme}`);
    await dialog.getByRole('button', { name: 'Preparar' }).click();
    await expect.element(dialog.getByText('ML ya no ofrece esa promo')).toBeVisible();
    await expect.element(dialog.getByText(/El plan vence a las \d{2}:\d{2}\.$/)).toBeVisible();
    const confirmar = dialog.getByRole('button', { name: 'Confirmar' }).element();
    for (const fondo of fondosDetras(confirmar)) {
      expect(contrastRatio(getComputedStyle(confirmar).color, fondo)).toBeGreaterThanOrEqual(4.5);
    }
    await shot(`modal-deshacer-plan-${theme}`);
  });

  it('write switch on / off / locked', async () => {
    renderPage();
    const sw = page.getByRole('switch');
    await expect.element(sw).toHaveAttribute('aria-checked', 'true');
    const panel = page.getByRole('region').filter({ has: sw });
    await shot(`interruptor-encendida-${theme}`, panel.element());
    await sw.click();
    await expect.element(sw).toHaveAttribute('aria-checked', 'false');
    await shot(`interruptor-apagada-${theme}`, panel.element());
  });

  it('write switch locked by the server kill switch', async () => {
    escritura = { habilitado: false, fuente: 'kill_switch' };
    renderPage();
    await expect
      .element(page.getByText('La escritura de la IA está bloqueada desde el servidor. No se puede encender desde acá.'))
      .toBeVisible();
    const panel = page.getByRole('region').filter({ has: page.getByRole('switch') });
    await shot(`interruptor-kill-switch-${theme}`, panel.element());
  });

  it('sidebar entry', async () => {
    renderPage(true);
    await expect.element(page.getByText('SKU 12345 - Notebook Demo 14"')).toBeVisible();
    await page.getByRole('button', { name: /Productos/ }).first().click();
    await page.getByRole('button', { name: /Gestión/ }).first().click();
    await expect.element(page.getByRole('link', { name: 'Acciones IA' })).toBeVisible();
    await shot(`sidebar-${theme}`);
  });
});
