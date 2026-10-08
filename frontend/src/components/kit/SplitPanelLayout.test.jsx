/**
 * SplitPanelLayout (publicaciones-ml-vista P10b.T1). Behaviour and DOM
 * contract only: this project's unit project runs with `css: false`, so the
 * "never an overlay" geometry is proved in real Chromium by
 * `src/test/visual/kit.visual.test.jsx`.
 */
import { useState } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SplitPanelLayout from './SplitPanelLayout';

const renderLayout = (props = {}) =>
  render(
    <SplitPanelLayout open panel={<div>panel content</div>} onClose={vi.fn()} ariaLabel="Detalle" {...props}>
      <div>table content</div>
    </SplitPanelLayout>,
  );

describe('open / closed', () => {
  it('renders only the children while closed', () => {
    renderLayout({ open: false });
    expect(screen.getByText('table content')).toBeInTheDocument();
    expect(screen.queryByLabelText('Detalle')).not.toBeInTheDocument();
    expect(screen.queryByText('panel content')).not.toBeInTheDocument();
  });

  it('renders the panel as a labelled aside next to the children while open', () => {
    renderLayout();
    const panel = screen.getByLabelText('Detalle');
    expect(panel.tagName).toBe('ASIDE');
    expect(panel).toHaveTextContent('panel content');
    expect(screen.getByText('table content')).toBeInTheDocument();
  });
});

describe('non-modal', () => {
  it('is never a dialog, never aria-modal and renders no overlay/backdrop element', () => {
    const { container } = renderLayout();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(container.querySelector('[aria-modal]')).toBeNull();
    expect(container.querySelector('[class*="overlay" i], [class*="backdrop" i]')).toBeNull();
  });

  it('does not move focus on open', () => {
    renderLayout();
    expect(document.body).toHaveFocus();
  });
});

describe('width', () => {
  it('defaults to md', () => {
    const { container } = renderLayout();
    expect(container.firstChild).toHaveAttribute('data-width', 'md');
  });

  it('accepts lg', () => {
    const { container } = renderLayout({ width: 'lg' });
    expect(container.firstChild).toHaveAttribute('data-width', 'lg');
  });

  it('falls back to md for an unknown width', () => {
    const { container } = renderLayout({ width: 'xxl' });
    expect(container.firstChild).toHaveAttribute('data-width', 'md');
  });
});

describe('Escape (S63.1)', () => {
  it('calls onClose', async () => {
    const onClose = vi.fn();
    renderLayout({ onClose });
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does nothing while closed', async () => {
    const onClose = vi.fn();
    renderLayout({ open: false, onClose });
    await userEvent.keyboard('{Escape}');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('ignores other keys', async () => {
    const onClose = vi.fn();
    renderLayout({ onClose });
    await userEvent.keyboard('a');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('leaves Escape to a focused text input', async () => {
    const onClose = vi.fn();
    renderLayout({ onClose, panel: <input aria-label="nota" /> });
    await userEvent.click(screen.getByLabelText('nota'));
    await userEvent.keyboard('{Escape}');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('leaves Escape to an open ModalTesla overlay', async () => {
    const onClose = vi.fn();
    renderLayout({ onClose });
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay-tesla';
    document.body.append(overlay);
    try {
      await userEvent.keyboard('{Escape}');
      expect(onClose).not.toHaveBeenCalled();
    } finally {
      overlay.remove();
    }
  });

  it('leaves Escape to focus inside a role=dialog', async () => {
    const onClose = vi.fn();
    render(
      <>
        <div role="dialog" aria-label="otro">
          <button type="button">dentro</button>
        </div>
        <SplitPanelLayout open panel={<div>p</div>} onClose={onClose} ariaLabel="Detalle">
          <div>t</div>
        </SplitPanelLayout>
      </>,
    );
    screen.getByText('dentro').focus();
    await userEvent.keyboard('{Escape}');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('ignores an Escape another handler already claimed', () => {
    const onClose = vi.fn();
    renderLayout({ onClose });
    const claim = (e) => e.preventDefault();
    document.addEventListener('keydown', claim);
    try {
      document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    } finally {
      document.removeEventListener('keydown', claim);
    }
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe('focus restore (S63.1)', () => {
  const Harness = ({ onCloseSpy }) => {
    const [open, setOpen] = useState(false);
    return (
      <SplitPanelLayout
        open={open}
        ariaLabel="Detalle"
        onClose={() => {
          onCloseSpy?.();
          setOpen(false);
        }}
        panel={
          <>
            <button type="button">en panel</button>
          </>
        }
      >
        <button type="button" onClick={() => setOpen(true)}>
          opener
        </button>
        <button type="button">otra fila</button>
      </SplitPanelLayout>
    );
  };

  it('returns focus to the opener when the panel closes with focus inside it', async () => {
    render(<Harness />);
    const opener = screen.getByText('opener');
    await userEvent.click(opener);
    expect(screen.getByLabelText('Detalle')).toBeInTheDocument();
    await userEvent.click(screen.getByText('en panel'));
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByLabelText('Detalle')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it('does not steal focus when the operator already moved elsewhere', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByText('opener'));
    const other = screen.getByText('otra fila');
    await userEvent.click(other);
    other.focus();
    // close through the keyboard from a non-editable control outside the panel
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByLabelText('Detalle')).not.toBeInTheDocument();
    expect(other).toHaveFocus();
  });
});
