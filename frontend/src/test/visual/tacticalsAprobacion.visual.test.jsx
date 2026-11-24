/**
 * Tacticals approval (handoffs/tacticals-aprobacion-plan.md S8, S11, S12) -- real CSS, real Chromium: the Tacticals
 * tab with the "N pendientes de aprobación" count beside the money KPIs, the "Pendientes de aprobación" filter with a
 * pending tactical and the standalone pending loads under it, an approved row naming its approver under the state, and
 * the Aprobar confirmations of a tactical and of a legacy profit offset (S10), inside the window at 1440, light and dark.
 *
 * The screen talks to the real `tacticalsAPI`; only the HTTP client is faked. Each fake endpoint answers in its
 * backend schema's shape (`TacticalListOut`, `CargasPendientesOut`) and honors its parameters the way the endpoint
 * does: `estado`, `tipo` and paging filter the tacticals, the money KPIs leave pending tacticals out,
 * `pendientes_aprobacion` counts the pending tacticals plus the standalone loads, and `tipo` filters the loads.
 *
 *   VITE_TACTICALS_APROBACION_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual tacticalsAprobacion
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import SellIn from '../../pages/SellIn';
import api from '../../services/api';
import { CARGAS_PENDIENTES, TACTICAL_BPS, TACTICAL_REBATE } from '../../components/tacticals/tacticalsFixtures';

const SHOTS_DIR = import.meta.env.VITE_TACTICALS_APROBACION_SHOTS_DIR;
const HOY = '2026-11-12';

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  productosAPI: { marcas: vi.fn().mockResolvedValue({ data: { marcas: ['HP', 'Lenovo', 'TP-Link'] } }), listar: vi.fn() },
}));

vi.mock('../../services/sellInAPI', () => ({
  sellInAPI: { listar: vi.fn(), resumen: vi.fn(), detalle: vi.fn() },
  sellInBonosAPI: { listar: vi.fn(), detalle: vi.fn() },
  costoSiSospechasAPI: { resumen: vi.fn(() => Promise.resolve({ data: { pendientes: 0 } })), listar: vi.fn() },
}));

vi.mock('../../services/sellOutAPI', () => ({
  sellOutAPI: { listar: vi.fn(), detalle: vi.fn(), grupos: vi.fn(), consumos: vi.fn() },
}));

const SIN_APROBAR = { aprobado_por: null, aprobado_at: null, aprobado_por_nombre: null, cobranza: null };
const PENDIENTE = {
  ...TACTICAL_BPS,
  ...SIN_APROBAR,
  estado: 'pendiente',
  // A pending tactical applied nothing yet: its lines have no usage (verifier A4; the backend counts no consumption
  // for a line that never applied).
  lineas: TACTICAL_BPS.lineas.map((l) => ({ ...l, estado: 'pendiente', unidades_usadas: 0, monto_usado: '0' })),
};
const APROBADO = { ...TACTICAL_REBATE, ...SIN_APROBAR, aprobado_por: 9, aprobado_por_nombre: 'Alejandro', aprobado_at: '2026-11-10T15:00:00Z' };
const TACTICALS = [PENDIENTE, APROBADO];

/** `_consulta`'s estado filter: vigentes and vencidos are approved ones only; pending ones only under their filter. */
const CUMPLE_ESTADO = {
  vigentes: (t) => t.estado === 'activo' && t.fecha_hasta >= HOY,
  vencidos: (t) => t.estado === 'activo' && t.fecha_hasta < HOY,
  anulados: (t) => t.estado === 'anulado',
  pendientes_aprobacion: (t) => t.estado === 'pendiente',
};

const cents = (n) => n.toFixed(2);

/** `kpis` (`TacticalKpisOut`): over the approved tacticals only, their non-pending lines' usage per currency. */
function kpisDe(tacticals) {
  const grupo = (cobrados) => {
    const delGrupo = tacticals.filter((t) => t.estado !== 'pendiente' && Boolean(t.cobranza) === cobrados);
    const porMoneda = {};
    for (const t of delGrupo) {
      for (const l of t.lineas.filter((x) => x.estado !== 'pendiente')) {
        const m = (porMoneda[l.moneda] ??= { monto: 0, tope: 0, conTope: 0, lineas: 0 });
        m.monto += Number(l.monto_usado);
        m.lineas += 1;
        if (l.tope_monto != null) {
          m.tope += Number(l.tope_monto);
          m.conTope += 1;
        }
      }
    }
    return {
      cantidad: delGrupo.length,
      sin_tope: delGrupo.filter((t) => t.lineas.every((l) => l.tope_monto == null)).length,
      montos: ['ARS', 'USD']
        .filter((moneda) => porMoneda[moneda])
        .map((moneda) => {
          const m = porMoneda[moneda];
          return {
            moneda,
            monto: cents(m.monto),
            tope: m.conTope ? cents(m.tope) : null,
            tope_parcial: m.conTope > 0 && m.conTope < m.lineas,
            estimado: false,
          };
        }),
    };
  };
  return { pendientes: grupo(false), cobrados: grupo(true) };
}

// A legacy profit offset (S10) is a sell out load, as `tacticals._consultas_sueltas` lists it.
const TIPO_DE_ORIGEN = { offset_ganancia: 'sell_out' };
const delTipo = (tipo) => (origen) => !tipo || (TIPO_DE_ORIGEN[origen] ?? origen.split('_').slice(0, 2).join('_')) === tipo;

/** `GET /tacticals/cargas-pendientes` (`CargasPendientesOut`): the standalone loads of the kind asked for. */
/** `CargasPendientesOut`: one page (`page`, `page_size`) of the loads of the kind, with `total`. */
const cargasPendientes = ({ tipo, page = 1, page_size: pageSize = 50 } = {}) => {
  const todas = CARGAS_PENDIENTES.filter((c) => delTipo(tipo)(c.origen));
  return { items: todas.slice((page - 1) * pageSize, page * pageSize), total: todas.length, page, page_size: pageSize };
};

/** `GET /tacticals` (`TacticalListOut`). */
function listar({ tipo, estado, page = 1, page_size: pageSize = 50 } = {}) {
  const otros = TACTICALS.filter((t) => !tipo || t.tipo === tipo);
  const filtrados = otros.filter((t) => !estado || CUMPLE_ESTADO[estado](t));
  return {
    total: filtrados.length,
    page,
    page_size: pageSize,
    items: filtrados.slice((page - 1) * pageSize, page * pageSize),
    kpis: kpisDe(filtrados),
    // The pending tacticals under the other filters, whatever the estado one, plus the standalone loads.
    pendientes_aprobacion: otros.filter(CUMPLE_ESTADO.pendientes_aprobacion).length + cargasPendientes({ tipo }).total,
  };
}

const ENDPOINTS = { '/tacticals': listar, '/tacticals/cargas-pendientes': cargasPendientes };

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

const pedidas = (url, estado) => api.get.mock.calls.some(([u, c]) => u === url && (!estado || c?.params?.estado === estado));

describe.each([
  { width: 1440, height: 1000, theme: 'light' },
  { width: 1440, height: 1000, theme: 'dark' },
])('Tacticals approval at $width px, $theme', ({ width, height, theme }) => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date(2026, 10, 12, 10));
    api.get.mockReset();
    api.get.mockImplementation(async (url, config) => {
      const endpoint = ENDPOINTS[url];
      if (!endpoint) throw new Error(`GET ${url} is not faked`);
      return { data: endpoint(config?.params) };
    });
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

  it('with the sidebar open, a long approver name wraps in its cell: the type pill and Cobranza keep their room', async () => {
    // Seen in the real capture: a sell out tactical approved by "Alejandro Aprobador" at 1440 with the sidebar open.
    const largo = { ...APROBADO, tipo: 'sell_out', aprobado_por_nombre: 'Alejandro Aprobador' };
    TACTICALS.splice(1, 1, largo);
    try {
      await page.viewport(width, height);
      setTheme(theme);
      document.body.style.background = 'var(--cf-bg-app)';
      const screen = await render(
        <MemoryRouter initialEntries={['/sell-in?tab=tacticals']}>
          <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-expanded)' }}>
            <SellIn />
          </div>
        </MemoryRouter>,
      );
      const fila = screen.getByRole('row', { name: /Rebate HP Q1FY27/ });
      await expect.element(fila.getByText('Aprobado por Alejandro Aprobador el 10/11/2026')).toBeVisible();
      // The type pill stays on one line (it was squeezed to one letter per line).
      const pill = fila.getByText('Sell out', { exact: true }).element().getBoundingClientRect();
      expect(pill.height).toBeLessThan(30);
      // Cargar cobro stays inside the table, not cut at its edge.
      const cobro = fila.getByRole('button', { name: /Cargar cobro/ }).element().getBoundingClientRect();
      const tabla = fila.element().closest('table').parentElement.getBoundingClientRect();
      expect(cobro.right).toBeLessThanOrEqual(tabla.right + 0.5);
    } finally {
      TACTICALS.splice(1, 1, APROBADO);
    }
  });

  it('counts what waits for approval beside the money KPIs, which leave it out', async () => {
    const screen = await abrir();
    const kpis = screen.getByRole('region', { name: 'Cobranza de los tacticals' });

    // Vigentes: the approved tactical only. The count: the pending tactical plus four standalone loads.
    const contador = kpis.getByRole('button', { name: '5 pendientes de aprobación' });
    await expect.element(contador).toBeVisible();
    await expect.element(kpis.getByText('1 tactical', { exact: true })).toBeVisible();
    const aprobado = screen.getByText('Aprobado por Alejandro el 10/11/2026');
    await expect.element(aprobado).toBeVisible();
    // The approver line stays inside its cell: no overflow over the Cobranza column.
    const texto = aprobado.element().getBoundingClientRect();
    const celda = aprobado.element().closest('td').getBoundingClientRect();
    expect(texto.right).toBeLessThanOrEqual(celda.right + 0.5);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tacticals-kpi-pendientes-${theme}-${width}.png` });
  });

  it('the count opens the pending filter: the pending tactical and, under it, the standalone loads', async () => {
    const screen = await abrir();
    await screen.getByRole('button', { name: '5 pendientes de aprobación' }).click();

    await expect.poll(() => pedidas('/tacticals', 'pendientes_aprobacion')).toBe(true);
    await expect.poll(() => pedidas('/tacticals/cargas-pendientes')).toBe(true);
    const fila = screen.getByRole('row', { name: /Tacticals BPS Noviembre Q1FY27/ });
    await expect.element(fila.getByText('Pendiente de aprobación')).toBeVisible();
    // A pending tactical applied nothing: no usage on its row (the backend counts none for a pending line).
    expect(fila.element().textContent).not.toMatch(/252|20\.544/);
    await expect.element(screen.getByText('Rebate HP Q1FY27')).not.toBeInTheDocument();
    const sueltas = screen.getByRole('region', { name: 'Cargas sueltas pendientes de aprobación' });
    await expect.element(sueltas).toBeVisible();
    for (const carga of CARGAS_PENDIENTES) {
      await expect.element(sueltas.getByRole('button', { name: `Aprobar ${carga.nombre}` })).toBeVisible();
    }
    // Nothing of the pending filter applies money yet: the KPIs read none.
    await expect.element(screen.getByRole('region', { name: 'Cobranza de los tacticals' }).getByText('0 tacticals').first()).toBeVisible();
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    sueltas.element().scrollIntoView({ block: 'end' });
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tacticals-pendientes-${theme}-${width}.png` });
  });

  it('a pending tactical shows Cargar cobro disabled but hoverable, with its tooltip, and the KPI says de cobro', async () => {
    // Tacticals approval S16: "a tactical pending approval must not offer 'Cargar cobro' (disabled with tooltip 'Se
    // aprueba antes de cobrar')" and "rename that KPI 'Pendientes de cobro'".
    const screen = await abrir();
    // The KPI box (the Cobranza filter segment reads the same since L12).
    const kpis = screen.getByRole('region', { name: 'Cobranza de los tacticals' });
    await expect.element(kpis.getByText('Pendientes de cobro', { exact: true })).toBeVisible();
    await screen.getByRole('button', { name: 'Pendientes de aprobación', exact: true }).click();
    const fila = screen.getByRole('row', { name: /Tacticals BPS Noviembre Q1FY27/ });
    const boton = fila.getByRole('button', { name: /Cargar cobro/ });
    await expect.element(boton).toBeVisible();
    await expect.element(boton).toHaveAttribute('aria-disabled', 'true');
    await expect.element(boton).toHaveAttribute('title', 'Se aprueba antes de cobrar');
    const estilo = getComputedStyle(boton.element());
    expect(Number(estilo.opacity)).toBeLessThan(1);
    expect(estilo.pointerEvents).not.toBe('none'); // the tooltip needs the hover
    expect(estilo.cursor).toBe('not-allowed');
    boton.element().click(); // the browser's actionability check would refuse an aria-disabled button
    await expect.element(screen.getByRole('form', { name: /Cobranza de/ })).not.toBeInTheDocument();
  });

  it('Aprobar opens its confirmation inside the window', async () => {
    const screen = await abrir();
    await screen.getByRole('button', { name: 'Pendientes de aprobación', exact: true }).click();
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

  it('a pending profit offset is approved from its own row, inside the window (S10)', async () => {
    const screen = await abrir();
    await screen.getByRole('button', { name: 'Pendientes de aprobación', exact: true }).click();
    const sueltas = screen.getByRole('region', { name: 'Cargas sueltas pendientes de aprobación' });
    const fila = sueltas.getByRole('row', { name: /Offset Epson/ });
    await expect.element(fila.getByText('Offset de ganancia')).toBeVisible();
    await expect.element(fila.getByText('Desde 01/11/2026')).toBeVisible();
    await fila.getByRole('button', { name: 'Aprobar Offset Epson' }).click();

    const dialogo = screen.getByRole('dialog', { name: '¿Aprobar Offset Epson?' });
    await expect.element(dialogo).toBeVisible();
    await expect.element(dialogo.getByRole('button', { name: 'Aprobar offset' })).toBeVisible();
    const caja = dialogo.element().getBoundingClientRect();
    expect(caja.top).toBeGreaterThanOrEqual(0);
    expect(caja.right).toBeLessThanOrEqual(width + 0.5);
    expect(caja.bottom).toBeLessThanOrEqual(height + 0.5);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tacticals-aprobar-offset-${theme}-${width}.png` });
  });
});
