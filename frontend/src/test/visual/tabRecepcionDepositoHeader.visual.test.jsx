/**
 * Empirical check for design D7's open question (compras-recepcion-
 * visibilidad-items, task 5.4): does `.headerBadges` crowd the estado badge,
 * copy button and retiro button when a SIN-OC pedido carries BOTH
 * identification chips (factura + a long observaciones)?
 *
 * jsdom does no layout, so the unit suite can prove the chip TEXT is right and
 * nothing about whether the row actually fits. This is the one place that
 * question can be answered honestly: real geometry, in Chromium.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import TabRecepcionDeposito from '../../components/compras/TabRecepcionDeposito';
import api from '../../services/api';

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
}));

// Worst case for D7's crowding question: a SIN-OC pedido carrying BOTH chips
// AND requiere_envio (so the retiro tag + button also compete for space), with
// a long proveedor name so `.pedidoProveedor` is under real pressure too.
const PEDIDO_CROWDED = {
  id: 1,
  numero: 'PC-9001',
  proveedor_id: 1,
  proveedor_nombre: 'Proveedor con Razón Social Bastante Larga SA',
  estado: 'pagado',
  numero_factura: 'A-0001-00099999',
  observaciones:
    'Coordinar entrega con el encargado de turno tarde antes de las 18 horas, sin excepciones.',
  requiere_envio: true,
  oc_poh_id: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockResolvedValue({
    data: { items: [PEDIDO_CROWDED], total: 1, page: 1, page_size: 200 },
  });
});

describe('TabRecepcionDeposito header — SIN-OC chips vs. estado badge/copy/retiro (D7, task 5.4)', () => {
  it('keeps every header control fully laid out inside the card, no clipping or zero-width squeeze', async () => {
    const { container } = await render(<TabRecepcionDeposito />);

    // Wait for the row (including the retiro button, the last thing to mount)
    // to be laid out.
    await vi.waitFor(() => {
      const found = [...container.querySelectorAll('button')].some((b) =>
        /Coordinar retiro/.test(b.textContent),
      );
      if (!found) throw new Error('row not mounted yet');
    });

    const header = container.querySelector('[class*="accordionHeader"]');
    const card = header.parentElement;
    // .headerBadges is the toggle button's sibling, i.e. the header's last child.
    const badgesBox = header.lastElementChild;

    const estadoBadgeEl = [...badgesBox.children].find((el) => el.textContent === 'Pagado');
    const copyBtn = [...badgesBox.querySelectorAll('button')].find((b) =>
      /Copiar datos/.test(b.getAttribute('aria-label') || ''),
    );
    const retiroBtn = [...badgesBox.querySelectorAll('button')].find((b) =>
      /Coordinar retiro/.test(b.textContent),
    );

    expect(estadoBadgeEl).toBeTruthy();
    expect(copyBtn).toBeTruthy();
    expect(retiroBtn).toBeTruthy();

    const cardRect = card.getBoundingClientRect();
    for (const el of [estadoBadgeEl, copyBtn, retiroBtn]) {
      const rect = el.getBoundingClientRect();
      // Not squeezed to nothing…
      expect(rect.width).toBeGreaterThan(0);
      // …and not clipped outside the card's own box (which would mean the
      // header row overflowed horizontally instead of the proveedor name
      // absorbing the pressure via its existing ellipsis).
      expect(rect.right).toBeLessThanOrEqual(cardRect.right + 1);
      expect(rect.left).toBeGreaterThanOrEqual(cardRect.left - 1);
    }

    // The two chips themselves must be present and bounded by their own
    // max-width (22ch) rather than growing unbounded with observaciones length.
    //
    // Identify them by the class the component actually applies, NOT by
    // subtracting the elements we happen to know about. The exclusion form also
    // matched `.tagRetiro` (a <span> sibling rendered by requiere_envio), so a
    // `>= 2` assertion still passed with one identification chip MISSING — the
    // test would have stayed green through the exact regression it exists to
    // catch. Exact count, positive selector.
    const chips = [...badgesBox.querySelectorAll('span[class*="chipIdent"]')];
    expect(chips).toHaveLength(2);
    for (const chip of chips) {
      expect(chip.getBoundingClientRect().width).toBeLessThan(250);
    }
  });
});
