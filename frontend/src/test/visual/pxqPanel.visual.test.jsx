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
import { tokenPx, tokenColor, px, setTheme, verticalGapBetween } from './visualHelpers';
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

/**
 * How many line boxes an element's text occupies.
 *
 * Split this way on purpose: `.label` sets `line-height: var(--leading-tight)`,
 * so Chromium resolves ONE line to a fixed 12 x 1.25 = 15px that does not move
 * with the typeface. The line COUNT does move with it. Keeping the two apart
 * lets the tests assert the part that is invariant and merely observe the part
 * that is not.
 */
const lineCount = (el) => {
  const line = px(getComputedStyle(el).lineHeight);
  if (!Number.isFinite(line) || line <= 0) throw new Error(`no resolved line-height on <${el.tagName}>`);
  return Math.round(el.getBoundingClientRect().height / line);
};

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

  /**
   * Equal width is a claim about the flex configuration, not about the text
   * inside it: the three fields share one `flex: 0 1 9rem`, so they have the
   * same basis AND the same shrink factor. Whether the row has slack (they all
   * sit at the 144px basis) or is over-constrained (they all shrink by the same
   * proportion of the same basis), the three end up identical. That is why this
   * survives a typeface change, and it is the only width claim that does.
   *
   * Deliberately NOT asserted here any more: "all three share one `top`, so the
   * row did not wrap". That read the geometry wrong twice over. `.pxqTierForm`
   * is `align-items: flex-end`, so items on a single line share a BOTTOM, not a
   * top — the moment one label needs two lines, its field is 15px taller and
   * starts 15px higher while never leaving the row. The old assertion therefore
   * failed on a wider fallback font for a layout that was behaving exactly as
   * designed. "Still one row" is really "still one flex line", which is what
   * the bottom-alignment test below measures.
   */
  it('every field is the same width', async () => {
    const container = await renderPanel();
    const form = createForm(container);
    const fields = [...form.children].filter((el) => el.querySelector('label'));

    const widths = new Set(fields.map((f) => Math.round(f.getBoundingClientRect().width)));
    expect(widths.size).toBe(1);
  });

  /**
   * THE claim `align-items: flex-end` exists to make, stated the way the design
   * states it: a label that needs two lines must not knock its own control —
   * or anyone else's — out of alignment.
   *
   * So the number of lines each label takes is an INPUT here, not something to
   * constrain. It is recorded and allowed to vary (it genuinely does: "Costo de
   * envío del bulto" takes one line under a narrow fallback and two under a
   * wide one), and the alignment is required to hold either way. Sharing one
   * bottom edge is also exactly what "these are all still on one flex line"
   * means, since a wrapped second line would sit at a different y.
   */
  it('every control stays bottom-aligned however many lines its label takes', async () => {
    const container = await renderPanel();
    const form = createForm(container);
    const fields = [...form.children].filter((el) => el.querySelector('label'));

    // Recorded, not constrained — this is the condition being absorbed.
    const lineCounts = fields.map((f) => lineCount(f.querySelector('label')));
    expect(Math.min(...lineCounts)).toBeGreaterThanOrEqual(1);

    const controls = [...form.querySelectorAll('input'), form.querySelector('button[type="submit"]')];
    const bottoms = new Set(controls.map((c) => Math.round(c.getBoundingClientRect().bottom)));

    expect(bottoms.size).toBe(1);
  });
});

describe('PxQ authoring form — the long label', () => {
  /**
   * DELETED, not skipped: "the longest label fits on ONE line inside its 9rem
   * field".
   *
   * `.pxqField`'s comment claims 9rem is "sized to hold the longest label
   * without forcing a wrap", and this test used to verify that by measuring the
   * label at exactly one 15px line box. It cannot be verified honestly.
   * "Does this string fit in 144px" is a question about a TYPEFACE, and the
   * suite loads none: index.css asks for `'Inter', system-ui, …` and gets
   * whatever the host has. Measured in this Chromium, "Costo de envío del
   * bulto" at 12px/500 is 129.42px on the stack this machine resolves and
   * 148.56px in a slightly wider face — one line, then two, for a form that is
   * behaving identically in both.
   *
   * It was previously guarded with `it.skipIf(!document.fonts.check('12px
   * Inter'))`, which does not work and cannot be made to work.
   * `FontFaceSet.check()` only consults `@font-face` rules registered in the
   * document; this page registers none (`document.fonts.size === 0`), so it
   * answers `true` for EVERY family — verified against a deliberately bogus
   * name, which also returns `true`. The guard never skipped anything anywhere.
   * It is not fixable either: there is no supported API that reports whether a
   * *system* font is installed. So the test ran on a runner with no Inter,
   * measured a wider fallback, and failed while claiming to be font-guarded.
   *
   * A skip guard that lies about coverage is worse than no test. What survives
   * below is every part of the original that was never about the typeface: the
   * label may take as many lines as it needs, but it must take a WHOLE number
   * of them, must never spill sideways out of its field, and must not have
   * bought its fit with truncation. Those hold in any environment.
   *
   * The consequence the deleted assertion was really guarding — a two-line
   * label changing the panel's height — is not lost: it is exactly what
   * `align-items: flex-end` absorbs, and the bottom-alignment test above now
   * asserts that absorption explicitly, under whatever line counts occur.
   */
  it('the longest label wraps within its field rather than overflowing or truncating', async () => {
    const container = await renderPanel();
    const form = createForm(container);
    const fields = [...form.children].filter((el) => el.querySelector('label'));

    const envioField = fields.find((f) => f.querySelector('label').textContent.includes('Costo de envío'));
    const label = envioField.querySelector('label');
    const cs = getComputedStyle(label);
    const labelRect = label.getBoundingClientRect();
    const fieldRect = envioField.getBoundingClientRect();

    // A whole number of line boxes. The COUNT is typeface-dependent and left
    // free; that each one is `--leading-tight` tall is not, and that is the
    // wiring worth protecting — a label box 22px tall would mean `line-height`
    // stopped reaching `.label` at all.
    const lines = lineCount(label);
    expect(lines).toBeGreaterThanOrEqual(1);
    expect(labelRect.height).toBeCloseTo(lines * px(cs.lineHeight), 1);

    // Wrapping means it never spills sideways, whatever the typeface: the text
    // breaks at the field edge instead of running past it.
    expect(label.scrollWidth).toBeLessThanOrEqual(Math.ceil(labelRect.width));
    expect(labelRect.width).toBeLessThanOrEqual(fieldRect.width + 0.5);

    // And the containment above must not have been bought with truncation —
    // clipping a Spanish label loses meaning, so wrapping stays ALLOWED.
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
   * The disabled-in-dark-mode case the maintainer flagged, on the REAL control.
   *
   * `forms-tesla.css` defines `:disabled { background: --cf-bg-app;
   * border-color: --cf-border-subtle; color: --cf-text-muted }`. Until the
   * global form rules in theme.css became a zero-specificity baseline, all
   * three of those declarations lost to `!important` on `input[type="number"]`,
   * which has no `:disabled` variant — so the state was not painted at all and
   * the only thing left was `cursor: not-allowed`, a pointer affordance that
   * keyboard and touch users never receive.
   *
   * Checked in BOTH themes because the two are painted from different sides of
   * the token scale: in light mode the disabled fill is lighter than the card
   * and recedes, in dark mode it is DARKER than the card. Only one of those can
   * be verified by eye at a time, and a token edit can easily fix one and break
   * the other.
   */
  it('a disabled PxQ control is visibly distinct from an enabled one, in both themes', async () => {
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

      // Three independent visual channels, not one — a single differing
      // property would be a weaker claim than "this reads as disabled".
      expect(d.backgroundColor).not.toBe(e.backgroundColor);
      expect(d.borderTopColor).not.toBe(e.borderTopColor);
      expect(d.color).not.toBe(e.color);

      // The exact declarations the primitive asks for, so a control cannot pass
      // by being differently wrong.
      expect(d.backgroundColor).toBe(tokenColor('--cf-bg-app'));
      expect(d.borderTopColor).toBe(tokenColor('--cf-border-subtle'));
      expect(d.color).toBe(tokenColor('--cf-text-muted'));

      // Never bought with `opacity`, which would dim the label too.
      expect(d.opacity).toBe(e.opacity);

      // The pointer affordance is still there, it is just no longer the ONLY
      // thing there.
      expect(d.cursor).toBe('not-allowed');
      expect(e.cursor).not.toBe('not-allowed');
    }

    probe.remove();
  });
});
