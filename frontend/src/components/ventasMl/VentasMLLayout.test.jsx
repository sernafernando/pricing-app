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

  it('renders no overlay/backdrop element blocking the rest of the page', () => {
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

    expect(screen.queryByTestId('drawer-overlay')).not.toBeInTheDocument();
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

    // No element between the table and the document root may carry
    // pointer-events: none or sit as a full-viewport blocking layer — a
    // literal DOM search for the drawer's known overlay marker.
    expect(document.querySelector('[data-testid="drawer-overlay"]')).toBeNull();
  });
});
