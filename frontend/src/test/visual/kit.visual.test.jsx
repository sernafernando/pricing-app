/**
 * Kit layout primitives — SplitPanelLayout + TableShell in real Chromium
 * (publicaciones-ml-vista P10b.T4).
 *
 * jsdom has no layout, so "the panel never covers the table" and "the header
 * never lands on the first row" cannot be unit tested. This suite renders a
 * harness that exists only inside this file (the components are not used by
 * any page yet) and asserts the geometry promises at the widths operators
 * actually use, plus the 1279/1000 cases that broke Ventas ML in #1419.
 *
 *   pnpm exec vitest run --project=visual kit
 */
import { describe, it, expect } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme, tokenPx } from './visualHelpers';
import SplitPanelLayout from '../../components/kit/SplitPanelLayout';
import TableShell from '../../components/kit/TableShell';

const COLUMN_COUNT = 12;
const COLUMNS = [
  { key: 'title', header: 'Publicación', width: 260, group: 'Datos', render: (r) => r.title },
  ...Array.from({ length: COLUMN_COUNT }, (_, i) => ({
    key: `c${i}`,
    header: `Col ${i}`,
    width: 150,
    sortable: true,
    group: i < 4 ? 'Datos' : 'Métricas',
    render: (r) => `${r.id}-${i}`,
  })),
];
const UNGROUPED = COLUMNS.map((column) => ({ ...column, group: undefined }));
const ROWS = Array.from({ length: 80 }, (_, i) => ({ id: i, title: `Publicación ${i}` }));

const Shell = ({ children }) => (
  <div
    data-shell
    style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}
  >
    {children}
  </div>
);

const Harness = ({ open, grouped = true, tree = false }) => (
  <Shell>
    <div style={{ padding: 'var(--spacing-lg)' }}>
      <SplitPanelLayout
        open={open}
        onClose={() => {}}
        width="lg"
        ariaLabel="Detalle"
        panel={<div style={{ padding: 16, height: 1200 }}>Panel de detalle</div>}
      >
        <TableShell
          columns={grouped ? COLUMNS : UNGROUPED}
          rows={ROWS}
          getRowKey={(r) => r.id}
          getRowDepth={tree ? (r) => r.id % 3 : undefined}
          ariaLabel="Publicaciones"
          offset="200px"
        />
      </SplitPanelLayout>
      {/* Makes the PAGE scrollable too, so the #1419 shape (page scroll +
          a horizontal scroll container) is actually exercised. */}
      <div style={{ height: 900 }} />
    </div>
  </Shell>
);

const mount = async ({ width, height = 700, theme = 'light', open = false, ...rest }) => {
  await page.viewport(width, height);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
  window.scrollTo(0, 0);
  return render(<Harness open={open} {...rest} />);
};

const scrollerOf = () => document.querySelector('[data-table-shell-scroller]');
const rect = (el) => el.getBoundingClientRect();
const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));

const WIDTHS = [1920, 1366, 1279, 1024, 1000];

describe('SplitPanelLayout (visual)', () => {
  for (const width of WIDTHS) {
    it(`${width}: opening the panel shrinks the table and never covers it`, async () => {
      const screen = await mount({ width });
      const closedWidth = rect(scrollerOf()).width;
      expect(closedWidth).toBeGreaterThan(0);

      await screen.rerender(<Harness open />);
      await frame();
      const panel = document.querySelector('aside');
      const scroller = scrollerOf();
      const table = rect(scroller);
      const side = rect(panel);

      // S61.1: the table's right edge is left of the panel's left edge.
      expect(table.right).toBeLessThanOrEqual(side.left + 0.5);
      // It really shrank: it did not keep the full width underneath.
      expect(table.width).toBeLessThan(closedWidth - 100);
      // The panel sits inside the viewport and the page does not grow sideways.
      expect(side.right).toBeLessThanOrEqual(width + 0.5);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
      // Nothing of the panel overlays any table pixel: probe the table's
      // right-most column inside the scroller.
      const probe = document.elementFromPoint(table.right - 3, table.top + table.height / 2);
      expect(scroller.contains(probe)).toBe(true);
      // Capped at 42vw (plus a hair for the border).
      expect(side.width).toBeLessThanOrEqual(width * 0.42 + 1);
      // Not a fixed sheet.
      expect(getComputedStyle(panel).position).toBe('sticky');
      screen.unmount();
    });
  }

  it('lg is wider than md when there is room (1920)', async () => {
    const screen = await mount({ width: 1920, open: true });
    await frame();
    expect(rect(document.querySelector('aside')).width).toBeCloseTo(tokenPx('--split-panel-width-lg'), 0);
    screen.unmount();
  });

  it('the panel sits below the TopBar and its sticky offset clears it', async () => {
    const screen = await mount({ width: 1366, open: true });
    await frame();
    const panel = document.querySelector('aside');
    expect(rect(panel).top).toBeGreaterThanOrEqual(tokenPx('--cf-topbar-height') - 0.5);
    expect(Number.parseFloat(getComputedStyle(panel).top)).toBeGreaterThanOrEqual(tokenPx('--cf-topbar-height'));
    // It never outgrows the viewport: taller content scrolls inside it.
    expect(rect(panel).height).toBeLessThanOrEqual(700 - tokenPx('--cf-topbar-height'));
    screen.unmount();
  });
});

describe('TableShell (visual)', () => {
  for (const width of WIDTHS) {
    it(`${width}: own bounded scroller on both axes; header above the first row`, async () => {
      const screen = await mount({ width, open: true });
      await frame();
      const scroller = scrollerOf();
      // Bounded: it scrolls inside itself in both directions.
      expect(scroller.scrollHeight).toBeGreaterThan(scroller.clientHeight);
      expect(scroller.scrollWidth).toBeGreaterThan(scroller.clientWidth);
      expect(rect(scroller).height).toBeLessThanOrEqual(768);
      expect(getComputedStyle(scroller).overflowX).toBe('auto');
      expect(getComputedStyle(scroller).overflowY).toBe('auto');

      // The first body row starts at or below the BOTTOM of the header
      // (both header rows), i.e. nothing is hidden under it.
      const headRows = [...scroller.querySelectorAll('thead tr')].map(rect);
      const headerBottom = Math.max(...headRows.map((r) => r.bottom));
      const firstRow = rect(scroller.querySelector('tbody tr'));
      expect(firstRow.top).toBeGreaterThanOrEqual(headerBottom - 0.5);
      screen.unmount();
    });

    it(`${width}: header stays pinned and the first column stays fixed while scrolling both axes`, async () => {
      const screen = await mount({ width, open: true });
      await frame();
      const scroller = scrollerOf();
      const box = rect(scroller);
      const headerCell = scroller.querySelector('thead tr:last-child th');
      const firstCell = scroller.querySelector('tbody tr td');
      const secondCell = scroller.querySelector('tbody tr td:nth-child(2)');
      const secondLeftBefore = rect(secondCell).left;

      scroller.scrollTop = 400;
      scroller.scrollLeft = 300;
      await frame();

      // Header: still flush with the scroller's top edge (border = 1px).
      // (measured on the <th>: a sticky cell moves, its <tr> does not)
      const groupRow = rect(scroller.querySelector('thead tr:first-child th'));
      expect(Math.abs(groupRow.top - box.top)).toBeLessThanOrEqual(2);
      // Leaf header sits directly under the group row, no gap and no overlap.
      expect(Math.abs(rect(headerCell).top - groupRow.bottom)).toBeLessThanOrEqual(1);
      // The pinned header cell did not move horizontally either.
      expect(Math.abs(rect(headerCell).left - box.left)).toBeLessThanOrEqual(2);

      // First column: same x as before scrolling, i.e. at the scroller's left edge...
      const pinned = scroller.querySelector('tbody td[data-pinned]');
      expect(pinned).toBe(firstCell);
      // (the first row scrolled away vertically, so probe a visible pinned cell)
      const visiblePinned = [...scroller.querySelectorAll('tbody td[data-pinned]')].find(
        (td) => rect(td).top >= rect(headerCell).bottom - 0.5 && rect(td).bottom <= box.bottom,
      );
      expect(visiblePinned).toBeTruthy();
      expect(Math.abs(rect(visiblePinned).left - box.left)).toBeLessThanOrEqual(2);
      // ...while the next column really scrolled away.
      expect(rect(secondCell).left).toBeLessThan(secondLeftBefore - 100);

      // The cell under the header's bottom edge is a body cell, never the
      // header painting over a row (elementFromPoint honours z-index).
      const below = document.elementFromPoint(box.left + box.width / 2, rect(headerCell).bottom + 3);
      expect(below.closest('tbody')).not.toBeNull();
      screen.unmount();
    });
  }

  it('#1419 repro (S62.2): scrolling the PAGE leaves a pinned header on its first row', async () => {
    for (const width of [1366, 1279, 1000]) {
      // Single header row: the exact shape Ventas ML has (one sticky <th>).
      const screen = await mount({ width, open: true, grouped: false });
      await frame();
      const scroller = scrollerOf();
      window.scrollTo(0, 150);
      scroller.scrollLeft = 200;
      await frame();
      const headerBottom = Math.max(...[...scroller.querySelectorAll('thead tr')].map((r) => rect(r).bottom));
      const firstRow = rect(scroller.querySelector('tbody tr'));
      // At scrollTop 0 the first row hugs the header bottom; page scroll
      // must not have pushed the header (or its offset) over it.
      expect(firstRow.top).toBeGreaterThanOrEqual(headerBottom - 0.5);
      expect(firstRow.top - headerBottom).toBeLessThanOrEqual(2);
      // And once the scroller itself scrolls, the header is flush with ITS
      // top edge -- not offset by the TopBar height (the #1419 failure).
      scroller.scrollTop = 300;
      await frame();
      const th = rect(scroller.querySelector('thead th'));
      expect(Math.abs(th.top - rect(scroller).top)).toBeLessThanOrEqual(2);
      screen.unmount();
    }
  });

  for (const theme of ['light', 'dark']) {
    it(`1366 ${theme}: pinned cells are opaque, so scrolled cells never show through`, async () => {
      const screen = await mount({ width: 1366, theme, open: true });
      await frame();
      const scroller = scrollerOf();
      for (const el of [
        scroller.querySelector('thead th[data-pinned]'),
        scroller.querySelector('tbody td[data-pinned]'),
      ]) {
        const { backgroundColor } = getComputedStyle(el);
        expect(backgroundColor).not.toBe('rgba(0, 0, 0, 0)');
        expect(backgroundColor).not.toMatch(/rgba\(.*,\s*0(\.\d+)?\)$/);
      }
      screen.unmount();
    });
  }

  it('1366: tree rows indent the pinned cell by --indent steps', async () => {
    const screen = await mount({ width: 1366, tree: true });
    await frame();
    const cells = [...scrollerOf().querySelectorAll('tbody td[data-pinned]')].slice(0, 3);
    const pads = cells.map((td) => Number.parseFloat(getComputedStyle(td).paddingLeft));
    const step = tokenPx('--table-shell-indent');
    expect(pads[1] - pads[0]).toBeCloseTo(step, 0);
    expect(pads[2] - pads[0]).toBeCloseTo(step * 2, 0);
    screen.unmount();
  });

  it('1366: without groups there is a single header row pinned at the top', async () => {
    const screen = await mount({ width: 1366, grouped: false });
    await frame();
    const scroller = scrollerOf();
    expect(scroller.querySelectorAll('thead tr')).toHaveLength(1);
    scroller.scrollTop = 300;
    await frame();
    expect(Math.abs(rect(scroller.querySelector('thead th')).top - rect(scroller).top)).toBeLessThanOrEqual(2);
    screen.unmount();
  });
});
