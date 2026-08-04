/**
 * Layer 1 — real geometry of the real PxQ authoring form.
 *
 * This mounts the actual `PxqPanel`, not a fixture that looks like it. The
 * field-grouping fix (`.pxqField` + a larger gap between units) is a claim
 * about PROXIMITY, and proximity is a measured distance between painted boxes.
 * Reading it out of the CSS would only re-read the intent; here we measure what
 * a reader's eye actually receives.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { tokenPx, px, setTheme, verticalGapBetween } from './visualHelpers';
import PxqPanel from '../../components/promociones/PxqPanel';
import { pxqAPI } from '../../services/api';

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  pxqAPI: {
    getLive: vi.fn(),
    createTier: vi.fn(),
    updateTier: vi.fn(),
    deleteTier: vi.fn(),
    sync: vi.fn(),
  },
}));

const LIVE_PAYLOAD = {
  data: {
    item_id: 'MLA001',
    live_status: 'ok',
    live_tiers: [{ id: 'p1', quantity: 3, amount: 900 }],
    mirror_tiers: [
      { id: 1, cantidad_minima: 3, precio_unitario: 900, costo_envio_total: 1500, estado: 'sincronizado', ml_price_id: 'p1' },
    ],
  },
};

/** Mount the panel and wait for the authoring form to be laid out. */
async function renderPanel() {
  pxqAPI.getLive.mockResolvedValue(LIVE_PAYLOAD);
  // `render` is async in vitest-browser-react 2.x — it resolves after React has
  // committed AND the browser has laid the tree out, which is exactly the
  // guarantee these geometry assertions need.
  const { container } = await render(<PxqPanel itemId="MLA001" pxqCacheRef={{ current: new Map() }} />);
  await vi.waitFor(() => {
    if (!container.querySelector('form')) throw new Error('authoring form not rendered yet');
  });
  return container;
}

/** The create form is the last one (edit forms only exist while editing). */
const createForm = (container) => [...container.querySelectorAll('form')].at(-1);

beforeEach(() => {
  vi.clearAllMocks();
  setTheme('light');
});

describe('PxQ authoring form — field grouping by proximity', () => {
  /**
   * THE readability fix, measured.
   *
   * Before, the row was a flat `flex-wrap` of alternating label/input with ONE
   * uniform 8px gap, so "Cantidad mínima" sat exactly as far from its own field
   * as from the next one and the row read as an undifferentiated strip. The fix
   * is entirely a ratio: small gap inside a unit, larger gap between units.
   * If those two ever converge again the grouping silently stops working, and
   * nothing else in the codebase would notice.
   */
  it('the gap inside a field is smaller than the gap between fields', async () => {
    const container = await renderPanel();
    const form = createForm(container);
    const fields = [...form.children].filter((el) => el.querySelector('label'));

    expect(fields.length).toBe(3);

    const [label, input] = [fields[0].querySelector('label'), fields[0].querySelector('input')];
    const insideGap = verticalGapBetween(label, input);
    const betweenGap = fields[1].getBoundingClientRect().left - fields[0].getBoundingClientRect().right;

    expect(insideGap).toBe(tokenPx('--spacing-xs'));
    expect(betweenGap).toBe(tokenPx('--spacing-md'));

    // The invariant that actually does the work — stated as a ratio so it
    // survives a rescale of the whole spacing system.
    expect(betweenGap).toBeGreaterThan(insideGap);
    expect(betweenGap / insideGap).toBeGreaterThanOrEqual(2);
  });

  it('every field is the same width and sits on one row', async () => {
    const container = await renderPanel();
    const form = createForm(container);
    const fields = [...form.children].filter((el) => el.querySelector('label'));

    const rects = fields.map((f) => f.getBoundingClientRect());
    const widths = new Set(rects.map((r) => Math.round(r.width)));
    expect(widths.size).toBe(1);

    // All three start at the same y — the row did not wrap at 1280px.
    const tops = new Set(rects.map((r) => Math.round(r.top)));
    expect(tops.size).toBe(1);
  });

  /**
   * `.pxqTierForm` uses `align-items: flex-end` specifically so a two-line
   * label cannot knock its own control out of line with the others. Asserted
   * against the real rendered bottoms, including the submit button.
   */
  it('all controls and the submit button are bottom-aligned on one line', async () => {
    const container = await renderPanel();
    const form = createForm(container);

    const controls = [...form.querySelectorAll('input'), form.querySelector('button[type="submit"]')];
    const bottoms = new Set(controls.map((c) => Math.round(c.getBoundingClientRect().bottom)));

    expect(bottoms.size).toBe(1);
  });
});

describe('PxQ authoring form — the long label', () => {
  /**
   * The maintainer could not check whether "Costo de envío del bulto" wraps.
   * `.pxqField` is `flex: 0 1 9rem` (144px) and its comment claims it is
   * "sized to hold the longest label without forcing a wrap".
   *
   * Measured answer: it does NOT wrap. At `--font-xs` (12px) / `--font-medium`
   * the string lays out inside 144px and the label box is exactly one line
   * tall. The comment's claim is accurate.
   *
   * Pinned because it is marginal: the label uses ~80-90% of the field width,
   * so a font-size bump, a heavier weight, or a longer translation flips it to
   * two lines. That would not break the row (`align-items: flex-end` keeps the
   * controls aligned — asserted above), but it changes the panel's height, and
   * this is where that shows up.
   *
   * THE ONE FONT-DEPENDENT ASSERTION IN THIS SUITE, and the reason it is
   * guarded by `skipIf`.
   *
   * "Does this label wrap" is an inherently typeface-dependent question — there
   * is no way to ask it that is not. See the long note in `setup.visual.js`:
   * the test browser loads no webfont, so the label is drawn with whatever the
   * host has. Measured at 12px/500: 117px with Inter installed (this machine,
   * and what production serves from the CDN), 129px with the Liberation Sans
   * fallback. The field is 144px, so the margin drops from 27px to 15px — and a
   * runner whose `system-ui` resolves to DejaVu Sans (wider again) could land
   * within a pixel or two of wrapping.
   *
   * Rather than gate CI on an unverifiable margin, the test runs ONLY where the
   * production typeface is actually available and reports SKIPPED elsewhere.
   * A skipped test that says so is honest; a green one that silently measured
   * the wrong font is not, and a red one on a runner nobody can reproduce gets
   * the whole suite disabled.
   */
  it.skipIf(!document.fonts.check('12px Inter'))('the longest label fits on ONE line inside its 9rem field', async () => {
    const container = await renderPanel();
    const form = createForm(container);
    const fields = [...form.children].filter((el) => el.querySelector('label'));

    const envioField = fields.find((f) => f.querySelector('label').textContent.includes('Costo de envío'));
    const label = envioField.querySelector('label');
    const cs = getComputedStyle(label);
    const labelRect = label.getBoundingClientRect();
    const fieldRect = envioField.getBoundingClientRect();

    // One line: 12px * 1.25 leading = 15px, not 30px.
    const oneLine = px(cs.fontSize) * px(cs.lineHeight) / px(cs.fontSize);
    expect(labelRect.height).toBeCloseTo(oneLine, 1);
    expect(labelRect.height).toBeLessThan(px(cs.fontSize) * 1.5);

    // It fits rather than overflowing: no horizontal scroll inside the label.
    expect(label.scrollWidth).toBeLessThanOrEqual(Math.ceil(labelRect.width));
    expect(labelRect.width).toBeLessThanOrEqual(fieldRect.width + 0.5);

    // Wrapping remains ALLOWED — truncating a Spanish label loses meaning, so
    // the fit above must not have been bought with `nowrap`/ellipsis.
    expect(cs.whiteSpace).not.toBe('nowrap');
    expect(cs.textOverflow).not.toBe('ellipsis');
  });
});

describe('PxQ authoring form — dark mode', () => {
  it('the form repaints for dark mode without changing its geometry', async () => {
    const container = await renderPanel();
    const form = createForm(container);
    const input = form.querySelector('input');

    const geometryOf = (el) => {
      const r = el.getBoundingClientRect();
      return `${Math.round(r.width)}x${Math.round(r.height)}`;
    };

    setTheme('light');
    const lightGeometry = geometryOf(input);
    const lightColor = getComputedStyle(input).color;

    setTheme('dark');
    const darkGeometry = geometryOf(input);
    const darkColor = getComputedStyle(input).color;

    // Colours move…
    expect(darkColor).not.toBe(lightColor);
    expect(darkColor).toBeTruthy();
    // …geometry does not. A theme toggle must never reflow a form the user is
    // halfway through filling in.
    expect(darkGeometry).toBe(lightGeometry);
  });

  /**
   * KNOWN DEFECT — the disabled-in-dark-mode case the maintainer flagged.
   *
   * The answer is worse than "hard to see in dark mode": on a real PxQ control
   * the disabled state is not PAINTED AT ALL. `forms-tesla.css` defines
   * `:disabled { background: --cf-bg-app; border-color: --cf-border-subtle;
   * color: --cf-text-muted }`, but theme.css sets background, colour and border
   * with `!important` on `input[type="number"]` and has no `:disabled` variant,
   * so all three of the primitive's disabled declarations are discarded.
   *
   * What survives is `cursor: not-allowed` — a pointer affordance only. A
   * keyboard or touch user gets no signal whatsoever, in EITHER theme.
   *
   * Reported, not fixed: the fix is deleting theme.css's global form rules,
   * which ~56 unmigrated modules still rely on.
   */
  it('a disabled PxQ control is visually IDENTICAL to an enabled one (defect)', async () => {
    const container = await renderPanel();
    const form = createForm(container);
    const enabled = form.querySelector('input');
    const probe = enabled.cloneNode();
    probe.disabled = true;
    form.append(probe);

    for (const theme of ['light', 'dark']) {
      setTheme(theme);
      const d = getComputedStyle(probe);
      const e = getComputedStyle(enabled);

      expect(d.backgroundColor).toBe(e.backgroundColor);
      expect(d.color).toBe(e.color);
      expect(d.borderTopColor).toBe(e.borderTopColor);
      expect(d.opacity).toBe(e.opacity);

      // The only difference the primitive still manages to deliver.
      expect(d.cursor).toBe('not-allowed');
      expect(e.cursor).not.toBe('not-allowed');
    }

    probe.remove();
  });

  it.fails('SHOULD: a disabled PxQ control has a different background from an enabled one', async () => {
    const container = await renderPanel();
    setTheme('dark');
    const form = createForm(container);
    const enabled = form.querySelector('input');
    const probe = enabled.cloneNode();
    probe.disabled = true;
    form.append(probe);

    expect(getComputedStyle(probe).backgroundColor).not.toBe(getComputedStyle(enabled).backgroundColor);
  });
});
