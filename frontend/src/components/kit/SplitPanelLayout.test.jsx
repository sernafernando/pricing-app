/**
 * SplitPanelLayout (publicaciones-ml-vista P10b.T1). Behaviour and DOM
 * contract only: this project's unit project runs with `css: false`, so the
 * "never an overlay" geometry is proved in real Chromium by
 * `src/test/visual/kit.visual.test.jsx`.
 */
import { useState } from 'react';
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SplitPanelLayout, { PANEL_MIN_WIDTH, RESIZE_STEP, TABLE_MIN_WIDTH } from './SplitPanelLayout';

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
  const Harness = ({ onCloseSpy, resizeKey }) => {
    const [open, setOpen] = useState(false);
    return (
      <SplitPanelLayout
        open={open}
        resizeKey={resizeKey}
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

  it('returns focus to the opener when Escape closes the panel from the resize handle', async () => {
    render(<Harness resizeKey="pubml" />);
    const opener = screen.getByText('opener');
    await userEvent.click(opener);
    screen.getByRole('separator').focus();
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

describe('resizing (opt-in by resizeKey)', () => {
  const STORAGE = 'split-panel-width:pubml';
  let GRID = 1600;
  let PANEL = 560;

  beforeEach(() => {
    GRID = 1600;
    PANEL = 560;
    localStorage.clear();
    // jsdom has no layout: the grid and the panel report fixed boxes.
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function rect() {
      const width = this.hasAttribute('data-split-panel') ? PANEL : this.hasAttribute('data-split-grid') ? GRID : 0;
      return { width, height: 0, top: 0, left: 0, right: width, bottom: 0, x: 0, y: 0 };
    });
  });

  afterEach(() => vi.restoreAllMocks());

  const separator = () => screen.getByRole('separator', { name: 'Ancho del panel' });
  const dragWidth = (container) => container.firstChild.style.getPropertyValue('--split-panel-drag-width');

  it('without resizeKey there is no handle, so the other screens stay as they are', () => {
    const { container } = renderLayout();
    expect(screen.queryByRole('separator')).not.toBeInTheDocument();
    expect(dragWidth(container)).toBe('');
  });

  it('has no handle while closed', () => {
    renderLayout({ open: false, resizeKey: 'pubml' });
    expect(screen.queryByRole('separator')).not.toBeInTheDocument();
  });

  it('is a focusable vertical separator whose value is the panel width, bounded on both sides', () => {
    const { container } = renderLayout({ resizeKey: 'pubml' });
    const handle = separator();
    expect(handle).toHaveAttribute('tabindex', '0');
    expect(handle).toHaveAttribute('aria-orientation', 'vertical');
    expect(handle).toHaveAttribute('aria-valuenow', String(PANEL));
    expect(handle).toHaveAttribute('aria-valuemin', String(PANEL_MIN_WIDTH));
    expect(handle).toHaveAttribute('aria-valuemax', String(GRID - TABLE_MIN_WIDTH));
    // The default stays today's width: nothing overrides the token until the operator resizes.
    expect(dragWidth(container)).toBe('');
  });

  it('the arrows move the divider: left widens the panel, right narrows it, and the width is remembered', async () => {
    const { container } = renderLayout({ resizeKey: 'pubml' });
    separator().focus();

    await userEvent.keyboard('{ArrowLeft}');
    expect(dragWidth(container)).toBe(`${PANEL + RESIZE_STEP}px`);
    expect(separator()).toHaveAttribute('aria-valuenow', String(PANEL + RESIZE_STEP));
    expect(localStorage.getItem(STORAGE)).toBe(String(PANEL + RESIZE_STEP));

    await userEvent.keyboard('{ArrowRight}{ArrowRight}');
    expect(dragWidth(container)).toBe(`${PANEL - RESIZE_STEP}px`);
    expect(localStorage.getItem(STORAGE)).toBe(String(PANEL - RESIZE_STEP));
  });

  it('never goes past either minimum', async () => {
    // A step that would cross a minimum lands on it.
    PANEL = PANEL_MIN_WIDTH + 4;
    const { container } = renderLayout({ resizeKey: 'pubml' });
    separator().focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(dragWidth(container)).toBe(`${PANEL_MIN_WIDTH}px`);

    PANEL = GRID - TABLE_MIN_WIDTH - 4;
    await userEvent.keyboard('{ArrowLeft}');
    expect(dragWidth(container)).toBe(`${GRID - TABLE_MIN_WIDTH}px`);

    // Already on it, the step does nothing.
    PANEL = GRID - TABLE_MIN_WIDTH;
    await userEvent.keyboard('{ArrowLeft}');
    expect(dragWidth(container)).toBe(`${GRID - TABLE_MIN_WIDTH}px`);
  });

  it('a click on the handle without moving it is not a resize, so nothing is remembered', () => {
    const { container } = renderLayout({ resizeKey: 'pubml' });
    fireEvent.pointerDown(separator(), { button: 0, clientX: 1000 });
    fireEvent.pointerUp(window, { clientX: 1000 });
    expect(localStorage.getItem(STORAGE)).toBeNull();
    expect(dragWidth(container)).toBe('');
  });

  it('dragging moves the divider by the distance dragged, and the width is remembered on release', () => {
    const { container } = renderLayout({ resizeKey: 'pubml' });
    fireEvent.pointerDown(separator(), { button: 0, clientX: 1000 });
    fireEvent.pointerMove(window, { buttons: 1, clientX: 900 });
    expect(dragWidth(container)).toBe(`${PANEL + 100}px`);
    fireEvent.pointerUp(window, { clientX: 900 });
    expect(localStorage.getItem(STORAGE)).toBe(String(PANEL + 100));
  });

  it('a saved width wider than the window allows reports the width it can have and steps from the one on screen', async () => {
    localStorage.setItem(STORAGE, '1300');
    // The CSS clamp shows the panel at the widest the window allows.
    PANEL = GRID - TABLE_MIN_WIDTH;
    const { container } = renderLayout({ resizeKey: 'pubml' });
    expect(separator()).toHaveAttribute('aria-valuenow', String(PANEL));
    separator().focus();
    await userEvent.keyboard('{ArrowRight}');
    // One step right narrows what is on screen; it is not lost against 1300.
    expect(dragWidth(container)).toBe(`${PANEL - RESIZE_STEP}px`);
  });

  it('on a narrow window whose default panel is outside the bounds, each key still moves the divider its way', async () => {
    // Too wide for the table's minimum: left must not narrow it, right narrows it.
    GRID = 840;
    PANEL = 378;
    const { container, unmount } = renderLayout({ resizeKey: 'pubml' });
    separator().focus();
    await userEvent.keyboard('{ArrowLeft}');
    expect(dragWidth(container)).toBe('');
    expect(localStorage.getItem(STORAGE)).toBeNull();
    // Right narrows it, onto the widest the table's minimum allows.
    await userEvent.keyboard('{ArrowRight}');
    expect(dragWidth(container)).toBe(`${GRID - TABLE_MIN_WIDTH}px`);
    unmount();

    // Already under the panel's minimum: right must not widen it, left widens it.
    localStorage.clear();
    GRID = 800;
    PANEL = 340;
    const second = renderLayout({ resizeKey: 'pubml' });
    separator().focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(dragWidth(second.container)).toBe('');
    // Left lands on the panel's minimum, the narrowest width the layout shows.
    await userEvent.keyboard('{ArrowLeft}');
    expect(dragWidth(second.container)).toBe(`${PANEL_MIN_WIDTH}px`);
    expect(localStorage.getItem(STORAGE)).toBe(String(PANEL_MIN_WIDTH));
  });

  it.each([
    ['ArrowLeft', 884, 420.42],
    ['ArrowRight', 800, 340.2],
  ])('a fractional default width outside the bounds is not resized the wrong way by %s', async (key, grid, panel) => {
    GRID = grid;
    PANEL = panel;
    const { container } = renderLayout({ resizeKey: 'pubml' });
    separator().focus();
    await userEvent.keyboard(`{${key}}`);
    expect(dragWidth(container)).toBe('');
    expect(localStorage.getItem(STORAGE)).toBeNull();
  });

  it('a click that jitters without moving sideways is not a resize', () => {
    const { container } = renderLayout({ resizeKey: 'pubml' });
    fireEvent.pointerDown(separator(), { button: 0, clientX: 1000, clientY: 300 });
    fireEvent.pointerMove(window, { buttons: 1, clientX: 1000, clientY: 304 });
    fireEvent.pointerUp(window, { clientX: 1000, clientY: 304 });
    expect(dragWidth(container)).toBe('');
    expect(localStorage.getItem(STORAGE)).toBeNull();
  });

  it('closing the panel mid-drag ends the drag: the release afterwards saves nothing', () => {
    const view = renderLayout({ resizeKey: 'pubml' });
    fireEvent.pointerDown(separator(), { button: 0, pointerId: 1, clientX: 1000 });
    view.rerender(
      <SplitPanelLayout open={false} panel={<div>panel content</div>} onClose={vi.fn()} ariaLabel="Detalle" resizeKey="pubml">
        <div>table content</div>
      </SplitPanelLayout>,
    );
    fireEvent.pointerMove(window, { buttons: 1, pointerId: 1, clientX: 900 });
    fireEvent.pointerUp(window, { pointerId: 1, clientX: 900 });
    expect(localStorage.getItem(STORAGE)).toBeNull();
  });

  it('closing the panel after dragging drops the unsaved width: it reopens as it was', () => {
    const layout = (open) => (
      <SplitPanelLayout open={open} panel={<div>panel content</div>} onClose={vi.fn()} ariaLabel="Detalle" resizeKey="pubml">
        <div>table content</div>
      </SplitPanelLayout>
    );
    const view = render(layout(true));
    fireEvent.pointerDown(separator(), { button: 0, pointerId: 1, clientX: 1000 });
    fireEvent.pointerMove(window, { buttons: 1, pointerId: 1, clientX: 900 });
    expect(dragWidth(view.container)).toBe(`${PANEL + 100}px`);
    view.rerender(layout(false));
    view.rerender(layout(true));
    expect(dragWidth(view.container)).toBe('');
    expect(localStorage.getItem(STORAGE)).toBeNull();
  });

  it('a drag the browser cancels goes back to where it started and saves nothing', () => {
    const { container } = renderLayout({ resizeKey: 'pubml' });
    fireEvent.pointerDown(separator(), { button: 0, pointerId: 1, clientX: 1000 });
    fireEvent.pointerMove(window, { buttons: 1, pointerId: 1, clientX: 900 });
    fireEvent.pointerCancel(window, { pointerId: 1 });
    expect(dragWidth(container)).toBe('');
    expect(localStorage.getItem(STORAGE)).toBeNull();
  });

  it('a move with the button already up ends a drag whose release got lost, and the handle takes presses again', () => {
    const { container } = renderLayout({ resizeKey: 'pubml' });
    fireEvent.pointerDown(separator(), { button: 0, pointerId: 1, clientX: 1000 });
    fireEvent.pointerMove(window, { buttons: 1, pointerId: 1, clientX: 900 });
    // No pointerup ever arrives (a context menu ate it); the mouse just hovers on.
    fireEvent.pointerMove(window, { buttons: 0, pointerId: 1, clientX: 700 });
    expect(dragWidth(container)).toBe(`${PANEL + 100}px`);
    expect(localStorage.getItem(STORAGE)).toBe(String(PANEL + 100));

    fireEvent.pointerDown(separator(), { button: 0, pointerId: 1, clientX: 1000 });
    fireEvent.pointerMove(window, { buttons: 1, pointerId: 1, clientX: 950 });
    fireEvent.pointerUp(window, { pointerId: 1, clientX: 950 });
    expect(localStorage.getItem(STORAGE)).toBe(String(PANEL + 50));
  });

  it('follows only the pointer that started the drag; a second touch starts nothing', () => {
    const { container } = renderLayout({ resizeKey: 'pubml' });
    fireEvent.pointerDown(separator(), { button: 0, pointerId: 1, clientX: 1000 });
    fireEvent.pointerDown(separator(), { button: 0, pointerId: 2, clientX: 500 });
    fireEvent.pointerMove(window, { buttons: 1, pointerId: 2, clientX: 300 });
    expect(dragWidth(container)).toBe('');
    fireEvent.pointerMove(window, { buttons: 1, pointerId: 1, clientX: 900 });
    fireEvent.pointerUp(window, { pointerId: 2, clientX: 300 });
    fireEvent.pointerUp(window, { pointerId: 1, clientX: 900 });
    expect(dragWidth(container)).toBe(`${PANEL + 100}px`);
    expect(localStorage.getItem(STORAGE)).toBe(String(PANEL + 100));
  });

  it('pressing the handle focuses it, so the arrows work right after a drag', () => {
    renderLayout({ resizeKey: 'pubml' });
    fireEvent.pointerDown(separator(), { button: 0, pointerId: 1, clientX: 1000 });
    expect(separator()).toHaveFocus();
    fireEvent.pointerUp(window, { pointerId: 1, clientX: 1000 });
  });

  it.each(['Alt', 'Meta', 'Control', 'Shift'])('leaves %s + arrow to the browser', async (modifier) => {
    const { container } = renderLayout({ resizeKey: 'pubml' });
    separator().focus();
    const notPrevented = fireEvent.keyDown(separator(), {
      key: 'ArrowLeft',
      altKey: modifier === 'Alt',
      metaKey: modifier === 'Meta',
      ctrlKey: modifier === 'Control',
      shiftKey: modifier === 'Shift',
    });
    expect(notPrevented).toBe(true);
    expect(dragWidth(container)).toBe('');
  });

  it('storage that throws neither breaks the screen nor stops resizing', async () => {
    vi.spyOn(localStorage, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const errors = [];
    const onError = (event) => {
      event.preventDefault();
      errors.push(event.error);
    };
    window.addEventListener('error', onError);
    try {
      const { container } = renderLayout({ resizeKey: 'pubml' });
      expect(dragWidth(container)).toBe('');
      separator().focus();
      await userEvent.keyboard('{ArrowLeft}');
      expect(dragWidth(container)).toBe(`${PANEL + RESIZE_STEP}px`);
      expect(errors).toEqual([]);
    } finally {
      window.removeEventListener('error', onError);
    }
  });

  it('the bounds follow the window when it is resized', () => {
    renderLayout({ resizeKey: 'pubml' });
    GRID = 1200;
    act(() => window.dispatchEvent(new Event('resize')));
    expect(separator()).toHaveAttribute('aria-valuemax', String(1200 - TABLE_MIN_WIDTH));
  });

  it('opens at the width remembered by this browser', () => {
    localStorage.setItem(STORAGE, '720');
    const { container } = renderLayout({ resizeKey: 'pubml' });
    expect(dragWidth(container)).toBe('720px');
    expect(separator()).toHaveAttribute('aria-valuenow', '720');
  });

  it.each(['abc', '-5', '10'])('ignores a stored width it cannot use (%s) and keeps the default', (stored) => {
    localStorage.setItem(STORAGE, stored);
    const { container } = renderLayout({ resizeKey: 'pubml' });
    expect(dragWidth(container)).toBe('');
  });
});
