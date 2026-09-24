/**
 * Tests for VentasMLLayout.jsx (ventas-ml-rediseno PR13, PANEL R16/R17/R18/R20).
 *
 * Scope:
 *  - Renders a CSS grid with `minmax(0,1fr) var(--ventas-panel-width)` only
 *    while a row is selected; a single column otherwise (R16, R18).
 *  - The panel is a sticky `<aside aria-label="Detalle de venta">` — never
 *    an overlay, never `aria-modal`, never a focus trap (R16, R20).
 *  - Escape clears the selection via `onClear`, without moving focus
 *    anywhere (no trap) (R20).
 *  - Deselecting (no `selectedOrderId`) hides the panel entirely (R18).
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import VentasMLLayout from './VentasMLLayout';

describe('Grid layout', () => {
  it('renders a single column when no row is selected', () => {
    render(
      <VentasMLLayout selectedOrderId={null} onClear={vi.fn()} panel={<div>panel content</div>}>
        <table>
          <tbody>
            <tr>
              <td>row</td>
            </tr>
          </tbody>
        </table>
      </VentasMLLayout>,
    );

    expect(screen.getByText('row')).toBeInTheDocument();
    expect(screen.queryByLabelText('Detalle de venta')).not.toBeInTheDocument();
  });

  it('renders the sticky aside panel when a row is selected', () => {
    render(
      <VentasMLLayout selectedOrderId={1001} onClear={vi.fn()} panel={<div>panel content</div>}>
        <table>
          <tbody>
            <tr>
              <td>row</td>
            </tr>
          </tbody>
        </table>
      </VentasMLLayout>,
    );

    const aside = screen.getByLabelText('Detalle de venta');
    expect(aside.tagName).toBe('ASIDE');
    expect(screen.getByText('panel content')).toBeInTheDocument();
  });
});

describe('Non-modal contract (PANEL R16, R20)', () => {
  it('never carries aria-modal or role="dialog" on the panel', () => {
    render(
      <VentasMLLayout selectedOrderId={1001} onClear={vi.fn()} panel={<div>panel content</div>}>
        <table>
          <tbody>
            <tr>
              <td>row</td>
            </tr>
          </tbody>
        </table>
      </VentasMLLayout>,
    );

    const aside = screen.getByLabelText('Detalle de venta');
    expect(aside).not.toHaveAttribute('aria-modal');
    expect(aside).not.toHaveAttribute('role', 'dialog');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps the table in the accessibility tree — reachable by role, not aria-hidden/inert — while the panel is open', () => {
    render(
      <VentasMLLayout selectedOrderId={1001} onClear={vi.fn()} panel={<div>panel content</div>}>
        <table>
          <tbody>
            <tr>
              <td>row</td>
            </tr>
          </tbody>
        </table>
      </VentasMLLayout>,
    );

    // `getByRole` excludes any subtree hidden with `aria-hidden`/`hidden`
    // from the accessibility tree (jsdom's `dom-accessibility-api`, same as
    // a real screen reader) — so this genuinely fails if a background-
    // hiding overlay technique gets reintroduced around the table, unlike a
    // grep for one known testid.
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'row' })).toBeInTheDocument();
    // No element anywhere marks the rest of the page inert or hidden from
    // assistive tech and pointer interaction — the real mechanism a modal
    // overlay uses to block the background, CSS `position: fixed` aside.
    expect(document.querySelector('[aria-hidden="true"]')).toBeNull();
    expect(document.querySelector('[inert]')).toBeNull();
  });

  it('clears the selection on Escape without trapping focus anywhere', async () => {
    const onClear = vi.fn();
    const user = userEvent.setup();
    render(
      <VentasMLLayout selectedOrderId={1001} onClear={onClear} panel={<button>panel button</button>}>
        <button>table button</button>
      </VentasMLLayout>,
    );

    // Focus starts OUTSIDE the panel and stays there — a real trap would
    // move focus into the panel on mount, which this component must not do.
    screen.getByText('table button').focus();
    expect(screen.getByText('table button')).toHaveFocus();

    await user.keyboard('{Escape}');

    expect(onClear).toHaveBeenCalledTimes(1);
    expect(screen.getByText('table button')).toHaveFocus();
  });
});

describe('Deselecting closes the panel automatically (PANEL R18)', () => {
  it('removes the aside from the DOM once selectedOrderId goes back to null', () => {
    const { rerender } = render(
      <VentasMLLayout selectedOrderId={1001} onClear={vi.fn()} panel={<div>panel content</div>}>
        <table>
          <tbody>
            <tr>
              <td>row</td>
            </tr>
          </tbody>
        </table>
      </VentasMLLayout>,
    );
    expect(screen.getByLabelText('Detalle de venta')).toBeInTheDocument();

    rerender(
      <VentasMLLayout selectedOrderId={null} onClear={vi.fn()} panel={<div>panel content</div>}>
        <table>
          <tbody>
            <tr>
              <td>row</td>
            </tr>
          </tbody>
        </table>
      </VentasMLLayout>,
    );

    expect(screen.queryByLabelText('Detalle de venta')).not.toBeInTheDocument();
  });
});

describe('Focus restoration on close (L1)', () => {
  it('returns focus to the element that opened the panel once it closes', () => {
    const { rerender } = render(
      <VentasMLLayout selectedOrderId={null} onClear={vi.fn()} panel={<button>panel button</button>}>
        <button>opener button</button>
      </VentasMLLayout>,
    );

    // Simulates the real keyboard route (the "Ver desglose de costos"
    // button): it has focus at the moment the parent flips selection on.
    screen.getByText('opener button').focus();
    expect(screen.getByText('opener button')).toHaveFocus();

    rerender(
      <VentasMLLayout selectedOrderId={1001} onClear={vi.fn()} panel={<button>panel button</button>}>
        <button>opener button</button>
      </VentasMLLayout>,
    );
    expect(screen.getByLabelText('Detalle de venta')).toBeInTheDocument();

    // Focus is INSIDE the panel when it closes — same as clicking its own
    // "Cerrar" button. Without restoration, unmounting the `<aside>` drops
    // focus to `<body>` instead of giving it back to the opener.
    screen.getByText('panel button').focus();
    expect(screen.getByText('panel button')).toHaveFocus();

    // Parent clears the selection (Cerrar button, Escape, row re-click...)
    rerender(
      <VentasMLLayout selectedOrderId={null} onClear={vi.fn()} panel={<button>panel button</button>}>
        <button>opener button</button>
      </VentasMLLayout>,
    );

    expect(screen.queryByLabelText('Detalle de venta')).not.toBeInTheDocument();
    expect(screen.getByText('opener button')).toHaveFocus();
  });
});

describe('Escape does not steal input from a modal above this layout (L2)', () => {
  it('ignores Escape when the event already carries defaultPrevented', async () => {
    const onClear = vi.fn();
    render(
      <VentasMLLayout selectedOrderId={1001} onClear={onClear} panel={<div>panel content</div>}>
        <button>table button</button>
      </VentasMLLayout>,
    );

    screen.getByText('table button').focus();
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    event.preventDefault();
    window.dispatchEvent(event);

    expect(onClear).not.toHaveBeenCalled();
  });

  it('ignores Escape while focus sits inside an open role="dialog"', async () => {
    const onClear = vi.fn();
    const user = userEvent.setup();
    render(
      <VentasMLLayout selectedOrderId={1001} onClear={onClear} panel={<div>panel content</div>}>
        <div role="dialog">
          <input aria-label="dialog input" />
        </div>
      </VentasMLLayout>,
    );

    screen.getByLabelText('dialog input').focus();
    await user.keyboard('{Escape}');

    expect(onClear).not.toHaveBeenCalled();
  });

  it('ignores Escape while the operator is typing in an input', async () => {
    const onClear = vi.fn();
    const user = userEvent.setup();
    render(
      <VentasMLLayout selectedOrderId={1001} onClear={onClear} panel={<div>panel content</div>}>
        <input aria-label="a filter" />
      </VentasMLLayout>,
    );

    screen.getByLabelText('a filter').focus();
    await user.keyboard('{Escape}');

    expect(onClear).not.toHaveBeenCalled();
  });
});

describe('Live region announces content, even the first open (L3)', () => {
  it('keeps the aria-live region mounted before any selection exists', () => {
    const { container } = render(
      <VentasMLLayout selectedOrderId={null} onClear={vi.fn()} panel={<div>panel content</div>}>
        <table>
          <tbody>
            <tr>
              <td>row</td>
            </tr>
          </tbody>
        </table>
      </VentasMLLayout>,
    );

    // A live region inserted ALREADY containing its text is generally not
    // announced by screen readers — only a later change to text inside an
    // already-mounted region is. It must exist BEFORE the first selection.
    const liveRegion = container.querySelector('[aria-live="polite"]');
    expect(liveRegion).not.toBeNull();
  });

  it('changes only the live region text on the first selection, without remounting it', () => {
    const { container, rerender } = render(
      <VentasMLLayout selectedOrderId={null} onClear={vi.fn()} panel={<div>panel content</div>}>
        <table>
          <tbody>
            <tr>
              <td>row</td>
            </tr>
          </tbody>
        </table>
      </VentasMLLayout>,
    );
    const liveRegionBeforeOpen = container.querySelector('[aria-live="polite"]');
    expect(liveRegionBeforeOpen).not.toBeNull();
    expect(liveRegionBeforeOpen.textContent).toBe('');

    rerender(
      <VentasMLLayout selectedOrderId={1001} onClear={vi.fn()} panel={<div>panel content</div>}>
        <table>
          <tbody>
            <tr>
              <td>row</td>
            </tr>
          </tbody>
        </table>
      </VentasMLLayout>,
    );

    const liveRegionAfterOpen = container.querySelector('[aria-live="polite"]');
    // Same DOM node, not a fresh one born already containing the text.
    expect(liveRegionAfterOpen).toBe(liveRegionBeforeOpen);
    expect(liveRegionAfterOpen.textContent).toBe('Mostrando el detalle de la venta 1001');
  });
});

describe('Table rows stay independently selectable while the panel is open (PANEL R17)', () => {
  it('lets a table row receive focus and text selection with no blocking overlay in between', () => {
    render(
      <VentasMLLayout selectedOrderId={1001} onClear={vi.fn()} panel={<div>panel content</div>}>
        <table>
          <tbody>
            <tr>
              <td>
                <button>row button</button>
              </td>
            </tr>
          </tbody>
        </table>
      </VentasMLLayout>,
    );

    const rowButton = screen.getByText('row button');
    rowButton.focus();
    expect(rowButton).toHaveFocus();

    // Structural proof the panel is a SIBLING of the table, never a
    // wrapper around it — a modal reintroduced as an ancestor of `.main`
    // would fail this even though it renders no `.overlay` element at all.
    const aside = screen.getByLabelText('Detalle de venta');
    expect(aside.contains(rowButton)).toBe(false);
    expect(rowButton.closest('aside')).toBeNull();

    // No element anywhere marks the table (or anything else) inert/hidden
    // from assistive tech — the real mechanism a modal overlay uses to
    // take the background out of interaction, CSS `position: fixed` aside.
    expect(document.querySelector('[aria-hidden="true"]')).toBeNull();
    expect(document.querySelector('[inert]')).toBeNull();
  });
});
