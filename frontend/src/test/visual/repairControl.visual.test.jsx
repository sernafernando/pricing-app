import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import RepairControl from '../../pages/RepairControl';
import { publicacionRepairAPI } from '../../services/api';

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    publicacionRepairAPI: {
      runs: vi.fn(),
      run: vi.fn(),
      eventsByMla: vi.fn(),
    },
  };
});

const SHOTS_DIR = import.meta.env.VITE_REPAIR_CONTROL_SHOTS_DIR;

const RUNS = [
  {
    id: 1,
    job_type: 'envio',
    status: 'success',
    trigger: 'tick',
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
    scanned: 10,
    changed: 2,
    skipped: 7,
    errors: 0,
    error_message: null,
  },
  {
    id: 2,
    job_type: 'sku',
    status: 'failed',
    trigger: 'tick',
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
    scanned: 5,
    changed: 0,
    skipped: 4,
    errors: 1,
    error_message: 'boom',
  },
  {
    id: 3,
    job_type: 'envio',
    status: 'partial',
    trigger: 'tick',
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
    scanned: 8,
    changed: 1,
    skipped: 6,
    errors: 2,
    error_message: null,
  },
];

beforeEach(() => {
  publicacionRepairAPI.runs.mockResolvedValue({ data: { items: RUNS, total: RUNS.length } });
  publicacionRepairAPI.run.mockResolvedValue({
    data: {
      run: RUNS[0],
      events: [
        { id: 11, run_id: 1, mla_id: 'MLA1', item_id: 42, action: 'changed', before: { shipping_mode: 'me2', free_shipping: false }, after: { shipping_mode: 'me2', free_shipping: true }, detail: 'shipping_put', created_at: new Date().toISOString() },
        { id: 12, run_id: 1, mla_id: 'MLA2', item_id: 7, action: 'skipped', before: { sku: 'ABC' }, after: { sku: 'ABC' }, detail: null, created_at: new Date().toISOString() },
      ],
      total: 2,
      page: 1,
      page_size: 50,
      breakdown: [
        { action: 'changed', detail: 'shipping_put', count: 1 },
        { action: 'skipped', detail: null, count: 1 },
      ],
    },
  });
  publicacionRepairAPI.eventsByMla.mockResolvedValue({ data: { mla_id: 'MLA9', events: [], total: 0, page: 1, page_size: 100, ml_writes: [] } });
});

describe.each([
  { theme: 'light', highContrast: false },
  { theme: 'dark', highContrast: false },
  { theme: 'light', highContrast: true },
])('RepairControl visual $theme', ({ theme, highContrast }) => {
  afterEach(() => {
    document.documentElement.classList.remove('high-contrast');
  });

  it('renders', async () => {
    await page.viewport(1366, 1800);
    setTheme(theme);
    document.documentElement.classList.toggle('high-contrast', highContrast);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(<MemoryRouter><RepairControl /></MemoryRouter>);
    await expect.element(screen.getByText('Control de reparación')).toBeVisible();
    // expand a run to show full JSON diff
    const row = document.querySelector('[data-row-key="1"]');
    if (row) row.click();
    await new Promise((r) => setTimeout(r, 200));
    const btn = [...document.querySelectorAll('button')].find((b) => /Ver JSON/i.test(b.textContent));
    if (btn) btn.click();
    await new Promise((r) => setTimeout(r, 200));
    if (SHOTS_DIR) {
      await page.screenshot({ path: `${SHOTS_DIR}/repair-control-${theme}${highContrast ? '-hc' : ''}.png`, fullPage: true });
    }
    screen.unmount();
  });
});