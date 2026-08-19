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
    getMarkup: vi.fn(),
    createTier: vi.fn(),
    updateTier: vi.fn(),
    deleteTier: vi.fn(),
    sync: vi.fn(),
    adoptLive: vi.fn(),
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
  // Resolved to an empty batch, not left unmocked: these are geometry
  // assertions about the authoring form/live column, unrelated to slice A2's
  // markup cell, so it must settle out of its "Calculando…" state instead of
  // hanging pending for the whole suite.
  pxqAPI.getMarkup.mockResolvedValue({ data: { item_id: 'MLA001', tiers: [] } });
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

/**
 * The adopt-live import control's outcome tones.
 *
 * Judged worth a browser test for one reason, and it is not "the new control
 * should look nice". The control's entire contract is that its outcomes are
 * DISTINGUISHABLE — a 409 you must act on, a 503 you should just retry, and a
 * success that still owes you a shipping cost. In the DOM that distinction is
 * carried by nothing but which of three CSS-module classes is applied, and the
 * jsdom suite can only prove the class NAMES differ.
 *
 * They are declared as `color: var(--success, var(--text-primary))` and
 * friends. That fallback chain is a silent collapse waiting to happen: drop
 * `--success` / `--warning` / `--danger` from `theme.css` and all three tones
 * resolve to the same `--text-primary`, the "warn tone, not error tone" unit
 * assertion keeps passing on the class name, and the operator gets three
 * identically-painted messages on the money path.
 *
 * Typeface-independent by construction — it measures resolved colours, exactly
 * like the disabled-state test above, and asserts nothing about text metrics.
 */
describe('PxQ adopt-live control — outcome tones are actually distinguishable', () => {
  const IMPORTABLE = {
    data: {
      item_id: 'MLA001',
      live_status: 'ok',
      live_tiers: [{ id: 'p1', quantity: 3, amount: 900 }],
      // Empty mirror + live tiers is the one state that offers the import.
      mirror_tiers: [],
    },
  };

  /** Mount the panel in the importable state, click Import, return the message node. */
  async function messageAfterImport(adoptResult, expectedClass) {
    pxqAPI.getLive.mockResolvedValue(IMPORTABLE);
    adoptResult();
    const { container } = await render(<PxqPanel itemId="MLA001" pxqCacheRef={{ current: new Map() }} />);

    const button = await vi.waitFor(() => {
      const found = [...container.querySelectorAll('button')].find((b) => b.textContent === 'Importar de MercadoLibre');
      if (!found) throw new Error('import button not rendered yet');
      return found;
    });
    button.click();

    // Querying BY the expected class is deliberate: it proves the branch chose
    // that class, and hands back the node whose paint we then measure.
    return vi.waitFor(() => {
      const node = container.querySelector(`[class*="${expectedClass}"]`);
      if (!node) throw new Error(`no ${expectedClass} message rendered yet`);
      return node;
    });
  }

  it('paints success, warn and error in three different colours, in both themes', async () => {
    const ok = await messageAfterImport(
      () => pxqAPI.adoptLive.mockResolvedValue({ data: { item_id: 'MLA001', count: 2, imported: [] } }),
      'feedbackSuccess',
    );
    const warn = await messageAfterImport(
      () =>
        pxqAPI.adoptLive.mockRejectedValue({
          response: { status: 503, data: { detail: { status: 'adopt_read_unavailable', reason: 'read failed' } } },
        }),
      'feedbackWarn',
    );
    const error = await messageAfterImport(
      () =>
        pxqAPI.adoptLive.mockRejectedValue({
          response: {
            status: 409,
            data: { detail: { status: 'adopt_conflict', conflicts: [{ tier_id: 3, cantidad_minima: 12 }] } },
          },
        }),
      'feedbackError',
    );

    // Both themes: the three tones come off `theme.css`'s light and dark
    // blocks independently, so one can be repaired while the other collapses.
    for (const theme of ['light', 'dark']) {
      setTheme(theme);
      const tones = [ok, warn, error].map((el) => getComputedStyle(el).color);

      expect(new Set(tones).size).toBe(3);

      // The exact collapse mode the fallback chain allows: every tone silently
      // becoming the ordinary body colour. Three-distinct alone would not
      // catch a partial collapse, so each is checked against it by name.
      const plain = tokenColor('--text-primary');
      for (const tone of tones) {
        expect(tone).not.toBe(plain);
      }
    }
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

/**
 * The read table, measured.
 *
 * The unit project runs with `css: false`, where the CSS-module object echoes
 * back any key it is handed — a class that exists and a class that was never
 * written are indistinguishable there, and that is exactly how the markup cell
 * once shipped unstyled. Every claim this redesign makes about hierarchy is a
 * claim about painted pixels, so it is settled here or not at all.
 */
describe('PxQ read table — the operator can tell what he is looking at', () => {
  const table = (container) => container.querySelector('[data-testid="pxq-tramos"]');
  const head = (container) => table(container).querySelector('[class*="pxqTableHead"]');
  const firstRow = (container) => table(container).querySelector('[class*="pxqRow"]');

  it('names every column, quietly and above the figures', async () => {
    const container = await renderPanel();
    const headings = [...head(container).children].map((el) => el.textContent);
    expect(headings).toEqual(['Cant.', 'Precio en ML', 'Costo del envío', 'Markup', 'Limpio por u.']);

    const style = getComputedStyle(head(container));
    expect(style.color).toBe(tokenColor('--text-tertiary'));
    expect(style.textTransform).toBe('uppercase');
    expect(Number(style.fontWeight)).toBeGreaterThanOrEqual(600);
    // Smaller than the figures underneath: a heading that competes with its
    // column is one more thing to read, not a map.
    expect(px(style.fontSize)).toBeLessThan(px(getComputedStyle(firstRow(container)).fontSize));
  });

  it('paints each tier as a card, not a bare line of text', async () => {
    const container = await renderPanel();
    const style = getComputedStyle(firstRow(container));

    expect(style.backgroundColor).toBe(tokenColor('--bg-secondary'));
    expect(px(style.borderTopWidth)).toBe(1);
    expect(px(style.borderTopLeftRadius)).toBe(tokenPx('--radius-md'));
    // A card is only a card if it is separated from the next one.
    expect(px(getComputedStyle(firstRow(container).parentElement).rowGap)).toBeGreaterThan(0);
  });

  it('lines the columns up, digit over digit', async () => {
    const container = await renderPanel();
    const row = firstRow(container);
    // Every cell that carries a figure asks for tabular digits; proportional
    // ones make a column of money read as unrelated strings.
    const numeric = [...row.querySelectorAll('[class*="pxqNum"]')];
    expect(numeric.length).toBeGreaterThan(0);
    for (const cell of numeric) {
      expect(getComputedStyle(cell).fontVariantNumeric).toContain('tabular-nums');
    }
    // Head and body share one grid template, so a heading sits over its column.
    // Compared track by track with a pixel of slack: the row carries a 1px
    // border the heading does not, so its two flexible tracks resolve a hair
    // narrower without the columns being misaligned.
    const tracks = (el) => getComputedStyle(el).gridTemplateColumns.split(' ').map(px);
    const headTracks = tracks(head(container));
    const rowTracks = tracks(row);
    expect(headTracks).toHaveLength(rowTracks.length);
    headTracks.forEach((track, i) => expect(Math.abs(track - rowTracks[i])).toBeLessThanOrEqual(2));
  });

  it('says where the shipping cost came from, in a chip that cannot be read as a figure', async () => {
    const container = await renderPanel();
    const chip = [...firstRow(container).querySelectorAll('[class*="pxqChip"]')].find((el) => el.textContent === 'a mano');
    expect(chip).toBeTruthy();

    const style = getComputedStyle(chip);
    expect(px(style.borderTopLeftRadius)).toBeGreaterThanOrEqual(9999 / 2);
    expect(style.color).toBe(tokenColor('--text-secondary'));
    // Quieter and smaller than the amount it qualifies.
    const amount = firstRow(container).querySelector('[class*="pxqNum"]');
    expect(px(style.fontSize)).toBeLessThan(px(getComputedStyle(amount).fontSize));
  });

  it('renders the presented estado label, not the raw enum, and keeps it subordinate', async () => {
    const container = await renderPanel();
    const estado = firstRow(container).querySelector('[class*="pxqEstado"]');

    expect(estado.textContent).toBe('Actualizado en MercadoLibre');
    expect(table(container).textContent).not.toMatch(/sincronizado/i);
    expect(getComputedStyle(estado).color).toBe(tokenColor('--text-tertiary'));
  });

  /**
   * The panel is nested inside the product tree and can end up narrow. The
   * accepted outcome is a table that SCROLLS: a grid that reflows turns five
   * aligned columns into five stacked strings, which is the exact loss of
   * alignment this redesign undoes. What must never happen is the table
   * pushing the panel around it wider.
   */
  it('scrolls instead of spilling out of a narrow panel', async () => {
    const container = await renderPanel();
    container.style.width = '260px';

    const t = table(container);
    expect(getComputedStyle(t).overflowX).toBe('auto');
    expect(t.getBoundingClientRect().right).toBeLessThanOrEqual(container.getBoundingClientRect().right + 1);
    expect(t.scrollWidth).toBeGreaterThan(t.clientWidth);
  });
});

/**
 * The markup cell, in real CSS.
 *
 * This is the layer that had to catch it: `PxqPanel` referenced
 * `styles.pxqMarkupPending` and `styles.pxqMarkupUnavailable` while
 * `promociones.module.css` defined NEITHER, so both resolved to `undefined`
 * and the cell painted with no styling at all. The unit project cannot see
 * that -- it runs with `css: false`, where the CSS-module object echoes back
 * any key it is handed. Only a real stylesheet tells a defined class from an
 * imagined one.
 */
describe('PxQ markup cell — the number is emphasised, the excuse is not', () => {
  const MIRROR_TIER = { id: 1, cantidad_minima: 3, precio_unitario: 900, costo_envio_total: 1500, estado: 'listo', ml_price_id: null };

  async function renderWithMarkup(tiers) {
    pxqAPI.getLive.mockResolvedValue({
      data: { item_id: 'MLA001', live_status: 'ok', live_tiers: [], mirror_tiers: [MIRROR_TIER], fetched_at: '2026-08-18T10:00:00Z' },
    });
    pxqAPI.getMarkup.mockResolvedValue({ data: { item_id: 'MLA001', tiers } });
    const { container } = await render(<PxqPanel itemId="MLA001" pxqCacheRef={{ current: new Map() }} />);
    return container;
  }

  const findByText = async (container, re) => {
    let found;
    await vi.waitFor(() => {
      found = [...container.querySelectorAll('span')].find((el) => re.test(el.textContent) && el.children.length === 0);
      if (!found) throw new Error(`no element matching ${re}`);
    });
    return found;
  };

  it('paints a resolved percentage in the success tone', async () => {
    const container = await renderWithMarkup([{ tier_id: 1, markup: 0.184 }]);
    const percent = await findByText(container, /18,4%/);

    expect(getComputedStyle(percent).color).toBe(tokenColor('--success-text'));
    // Emphasis is what separates it from the cells around it; equal weight
    // would put the panel's whole point back into the visual noise.
    expect(Number(getComputedStyle(percent).fontWeight)).toBeGreaterThanOrEqual(600);
  });

  it('paints the unavailable reason in a muted tone, never like a value', async () => {
    const container = await renderWithMarkup([{ tier_id: 1, reason: 'shipping_unavailable' }]);
    const reason = await findByText(container, /Falta el costo de env/);

    expect(getComputedStyle(reason).color).toBe(tokenColor('--text-tertiary'));
    expect(getComputedStyle(reason).color).not.toBe(tokenColor('--success-text'));
  });

  it('paints the in-flight placeholder in a muted tone too', async () => {
    pxqAPI.getLive.mockResolvedValue({
      data: { item_id: 'MLA001', live_status: 'ok', live_tiers: [], mirror_tiers: [MIRROR_TIER], fetched_at: '2026-08-18T10:00:00Z' },
    });
    pxqAPI.getMarkup.mockReturnValue(new Promise(() => {}));
    const { container } = await render(<PxqPanel itemId="MLA001" pxqCacheRef={{ current: new Map() }} />);

    const pending = await findByText(container, /Calculando markup/);
    expect(getComputedStyle(pending).color).toBe(tokenColor('--text-tertiary'));
  });
});

/**
 * A tier with no shipping cost, painted.
 *
 * The old panel put a sentence in the markup cell and left the cost cell
 * empty. The cell that is missing something now carries the action that fills
 * it, and the two cells that cannot be computed carry a dash — never a 0.
 */
describe('PxQ read table — a tier with no shipping cost', () => {
  const INCOMPLETE_TIER = { id: 1, cantidad_minima: 3, precio_unitario: 900, costo_envio_total: null, estado: 'listo', ml_price_id: null };

  async function renderIncomplete() {
    pxqAPI.getLive.mockResolvedValue({
      data: { item_id: 'MLA001', live_status: 'ok', live_tiers: [], mirror_tiers: [INCOMPLETE_TIER], fetched_at: '2026-08-18T10:00:00Z' },
    });
    pxqAPI.getMarkup.mockResolvedValue({ data: { item_id: 'MLA001', tiers: [{ tier_id: 1, reason: 'shipping_unavailable' }] } });
    const { container } = await render(<PxqPanel itemId="MLA001" pxqCacheRef={{ current: new Map() }} />);
    await vi.waitFor(() => {
      if (!container.querySelector('[class*="pxqLoadCost"]')) throw new Error('cost affordance not rendered yet');
    });
    return container;
  }

  it('offers the action in the cell that is missing the number', async () => {
    const container = await renderIncomplete();
    const button = container.querySelector('[class*="pxqLoadCost"]');

    expect(button.textContent).toBe('Cargar costo');
    // Dashed: the cell is a hole to be filled, and it should not look like a
    // finished value nor like the panel's primary action.
    expect(getComputedStyle(button).borderTopStyle).toBe('dashed');
    expect(getComputedStyle(button).cursor).toBe('pointer');
  });

  it('shows a muted dash where a number cannot be computed, never a zero', async () => {
    const container = await renderIncomplete();
    const dashes = [...container.querySelectorAll('[class*="pxqEmpty"]')];
    expect(dashes.length).toBeGreaterThan(0);
    for (const dash of dashes) {
      expect(dash.textContent).toBe('—');
      expect(getComputedStyle(dash).color).toBe(tokenColor('--text-tertiary'));
    }
    expect(container.querySelector('[data-testid="pxq-tramos"]').textContent).not.toMatch(/\$0\b/);
  });
});

/**
 * The net per unit, which the markup endpoint has always returned and the
 * panel never showed. It is context for the markup, so it is secondary — the
 * percentage stays the loudest thing on the row.
 */
describe('PxQ read table — limpio por unidad', () => {
  it('paints it in the secondary tone, quieter than the markup', async () => {
    pxqAPI.getLive.mockResolvedValue({
      data: {
        item_id: 'MLA001',
        live_status: 'ok',
        live_tiers: [],
        mirror_tiers: [{ id: 1, cantidad_minima: 3, precio_unitario: 900, costo_envio_total: 1500, estado: 'listo', ml_price_id: null }],
        fetched_at: '2026-08-18T10:00:00Z',
      },
    });
    pxqAPI.getMarkup.mockResolvedValue({ data: { item_id: 'MLA001', tiers: [{ tier_id: 1, markup: 0.184, limpio: 6470 }] } });
    const { container } = await render(<PxqPanel itemId="MLA001" pxqCacheRef={{ current: new Map() }} />);

    let limpio;
    await vi.waitFor(() => {
      limpio = container.querySelector('[class*="pxqLimpio"]');
      if (!limpio || !/6\.470/.test(limpio.textContent)) throw new Error('limpio not painted yet');
    });

    expect(getComputedStyle(limpio).color).toBe(tokenColor('--text-secondary'));
    expect(getComputedStyle(limpio).fontVariantNumeric).toContain('tabular-nums');
  });
});

/**
 * The longest thing the Markup column can ever be handed, measured.
 *
 * The column is a FIXED track — that is what keeps the figures in a line — and
 * `PxqTierMarkup` can put a 47-character sentence in it ("Faltan datos del
 * producto para calcular el markup") when the markup cannot be computed. The
 * existing tests all feed it either a percentage or a shorter reason, so the
 * one input that can stretch a row was never put in front of a layout engine.
 *
 * WRAPPING IS THE ACCEPTED OUTCOME, stated here rather than merely tolerated,
 * the same way the old `estado` test stated it: the row has no fixed height and
 * grows. What is NOT accepted is the sentence being clipped, escaping its
 * column, or turning one tier into a five-line block — hence the track is wide
 * enough (128px) to hold it in a few lines, and this test pins the ceiling.
 */
describe('PxQ read table — the longest markup reason', () => {
  it('wraps inside its column, without clipping, spilling or exploding the row', async () => {
    pxqAPI.getLive.mockResolvedValue({
      data: {
        item_id: 'MLA001',
        live_status: 'ok',
        live_tiers: [],
        mirror_tiers: [{ id: 1, cantidad_minima: 3, precio_unitario: 900, costo_envio_total: 1500, estado: 'listo', ml_price_id: null }],
        fetched_at: '2026-08-18T10:00:00Z',
      },
    });
    pxqAPI.getMarkup.mockResolvedValue({ data: { item_id: 'MLA001', tiers: [{ tier_id: 1, reason: 'product_data_missing' }] } });
    const { container } = await render(<PxqPanel itemId="MLA001" pxqCacheRef={{ current: new Map() }} />);

    let reason;
    await vi.waitFor(() => {
      reason = container.querySelector('[class*="pxqMarkupUnavailable"]');
      if (!reason) throw new Error('reason not painted yet');
    });
    expect(reason.textContent).toBe('Faltan datos del producto para calcular el markup');

    const cell = reason.closest('[role="cell"]');
    const row = cell.closest('[role="row"]');
    // One line, measured rather than assumed: `line-height` on these cells
    // resolves to `normal`, which `getComputedStyle` reports as the keyword and
    // not as a length. The quantity can only ever be one line, so it is the
    // reference.
    const oneLine = row.querySelector('[class*="pxqNum"]').getBoundingClientRect().height;
    // It DOES wrap here — a single line would mean the track grew and the
    // columns stopped lining up.
    const lines = Math.round(reason.getBoundingClientRect().height / oneLine);
    expect(lines).toBeGreaterThan(1);
    // …but not into a block that dwarfs every other tier on the panel.
    expect(lines).toBeLessThanOrEqual(3);
    // Not paid for with clipped text…
    expect(reason.scrollWidth).toBeLessThanOrEqual(cell.clientWidth + 1);
    // …nor with a cell that spills past the row it belongs to.
    expect(cell.getBoundingClientRect().right).toBeLessThanOrEqual(row.getBoundingClientRect().right + 1);
  });
});
