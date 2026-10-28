/**
 * Publicaciones ML's keyboard shortcuts (Productos' `useProductosKeyboard`, over what this screen has): the arrows
 * move the focus over the list's rows (Enter opens the focused one, the table's own key), Ctrl+F the search, Ctrl+E
 * the export, `?` the help, and Ctrl+F1/F2/F3 copy the focused publication's product code and its two ML links.
 */
import { describe, it, expect, vi } from 'vitest';
import { useRef, useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TableShell from '../kit/TableShell';
import ModalTesla from '../ModalTesla';
import usePublicacionesMLKeyboard from './usePublicacionesMLKeyboard';

const ROWS = Array.from({ length: 15 }, (_, index) => ({
  item_id: `MLA${index + 1}`,
  titulo: `Publicación ${index + 1}`,
  link: { codigo: index === 1 ? null : `COD-${index + 1}` },
}));
const COLUMNS = [{ key: 'titulo', label: 'Título', render: (row) => row.titulo }];

function Harness({ onOpen = () => {}, onExport, onPaintRow, onToggleRow, onExtendRow, onCycleLayer, onCycleMode, onBulkAction, onOpenFilter, onToggleAutoRecalc, onShowInfo, showToast = () => {}, rows = ROWS }) {
  const searchRef = useRef(null);
  const [help, setHelp] = useState(false);
  usePublicacionesMLKeyboard({
    searchRef,
    findRow: (key) => rows.find((row) => row.item_id === key),
    onExport,
    onPaintRow,
    onToggleRow,
    onExtendRow,
    onCycleLayer,
    onCycleMode,
    onBulkAction,
    onOpenFilter,
    onToggleAutoRecalc,
    onShowInfo,
    onToggleHelp: () => setHelp((open) => !open),
    showToast,
  });
  return (
    <div>
      <input ref={searchRef} aria-label="Buscar" />
      {help && <p>Ayuda abierta</p>}
      <TableShell
        columns={COLUMNS}
        rows={ROWS}
        getRowKey={(row) => row.item_id}
        onRowClick={onOpen}
        ariaLabel="Publicaciones"
      />
    </div>
  );
}

const row = (n) => screen.getByText(`Publicación ${n}`).closest('tr');

// userEvent.setup() puts its own clipboard in place: what a shortcut copied is read back from it.
const copied = () => navigator.clipboard.readText();

describe('usePublicacionesMLKeyboard', () => {
  it('ArrowDown with nothing focused enters the list on its first row; the arrows then move the focus', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.keyboard('{ArrowDown}');
    expect(row(1)).toHaveFocus();
    await user.keyboard('{ArrowDown}{ArrowDown}');
    expect(row(3)).toHaveFocus();
    await user.keyboard('{ArrowUp}');
    expect(row(2)).toHaveFocus();
  });

  it('PageDown and PageUp jump ten rows, Home and End go to the ends, never past them', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.keyboard('{ArrowDown}{PageDown}');
    expect(row(11)).toHaveFocus();
    await user.keyboard('{PageDown}');
    expect(row(15)).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(row(15)).toHaveFocus();
    await user.keyboard('{Home}');
    expect(row(1)).toHaveFocus();
    await user.keyboard('{ArrowUp}{End}');
    expect(row(15)).toHaveFocus();
    await user.keyboard('{PageUp}');
    expect(row(5)).toHaveFocus();
  });

  it('Enter opens the focused row', async () => {
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(<Harness onOpen={onOpen} />);
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}');
    expect(onOpen).toHaveBeenCalledWith(ROWS[1], expect.anything());
  });

  it('ArrowDown from a focused control outside the list leaves the focus there', async () => {
    const user = userEvent.setup();
    render(
      <>
        <button type="button">Fuera de la lista</button>
        <Harness />
      </>,
    );
    screen.getByRole('button', { name: 'Fuera de la lista' }).focus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('button', { name: 'Fuera de la lista' })).toHaveFocus();
  });

  it('with another dialog open (a bulk action) no shortcut runs', async () => {
    const onExport = vi.fn();
    const user = userEvent.setup();
    render(
      <>
        <ModalTesla isOpen onClose={() => {}} title="Calcular Web Transf.">
          <p>Modal abierto</p>
        </ModalTesla>
        <Harness onExport={onExport} />
      </>,
    );
    await user.keyboard('{Control>}e{/Control}?');
    expect(onExport).not.toHaveBeenCalled();
    expect(screen.queryByText('Ayuda abierta')).not.toBeInTheDocument();
  });

  it('the arrows do nothing while the operator types in a field', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByLabelText('Buscar'));
    await user.keyboard('{ArrowDown}');
    expect(screen.getByLabelText('Buscar')).toHaveFocus();
  });

  it('Ctrl+F focuses the search', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.keyboard('{ArrowDown}{Control>}f{/Control}');
    expect(screen.getByLabelText('Buscar')).toHaveFocus();
  });

  it('Ctrl+F and Ctrl+E work with Caps Lock on', () => {
    const onExport = vi.fn();
    render(<Harness onExport={onExport} />);
    fireEvent.keyDown(document.body, { key: 'E', code: 'KeyE', ctrlKey: true });
    expect(onExport).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document.body, { key: 'F', code: 'KeyF', ctrlKey: true });
    expect(screen.getByLabelText('Buscar')).toHaveFocus();
  });

  it('Ctrl+E exports when the view can, and is left to the browser when it cannot', async () => {
    const onExport = vi.fn();
    const user = userEvent.setup();
    const { unmount } = render(<Harness onExport={onExport} />);
    await user.keyboard('{Control>}e{/Control}');
    expect(onExport).toHaveBeenCalledTimes(1);
    unmount();
    render(<Harness onExport={undefined} />);
    await user.keyboard('{Control>}e{/Control}');
    expect(onExport).toHaveBeenCalledTimes(1);
  });

  it('? toggles the help, but types a ? in a field', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.keyboard('?');
    expect(screen.getByText('Ayuda abierta')).toBeInTheDocument();
    await user.keyboard('?');
    expect(screen.queryByText('Ayuda abierta')).not.toBeInTheDocument();
    await user.click(screen.getByLabelText('Buscar'));
    await user.keyboard('?');
    expect(screen.queryByText('Ayuda abierta')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Buscar')).toHaveValue('?');
  });

  it("Ctrl+F1/F2/F3 copy the focused publication's product code and its two ML links, like Productos", async () => {
    const showToast = vi.fn();
    const user = userEvent.setup();
    render(<Harness showToast={showToast} />);
    await user.keyboard('{ArrowDown}{Control>}{F1}{/Control}');
    expect(await copied()).toBe('COD-1');
    await user.keyboard('{Control>}{F2}{/Control}');
    expect(await copied()).toBe('https://listado.mercadolibre.com.ar/COD-1_OrderId_PRICE_NoIndex_True');
    await user.keyboard('{Control>}{F3}{/Control}');
    expect(await copied()).toBe(
      'https://www.mercadolibre.com.ar/publicaciones/listado/promos?page=1&search=COD-1&sort=lowest_price',
    );
    await vi.waitFor(() => expect(showToast).toHaveBeenLastCalledWith('Enlace 2 copiado: COD-1'));
  });

  it('a focused row that is not a publication of the list says where copying works', async () => {
    const showToast = vi.fn();
    const user = userEvent.setup();
    render(<Harness showToast={showToast} rows={[]} />);
    await user.keyboard('{ArrowDown}{Control>}{F1}{/Control}');
    expect(showToast).toHaveBeenLastCalledWith('Los atajos de copia funcionan en la vista Publicaciones', 'error');
  });

  it('Ctrl+Shift+1 copies too (Ctrl+F1 is taken on some keyboards)', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.keyboard('{ArrowDown}{Control>}{Shift>}!{/Shift}{/Control}');
    expect(await copied()).toBe('COD-1');
  });

  it('copying says why it cannot: no focused publication, or one without a linked product', async () => {
    const showToast = vi.fn();
    const user = userEvent.setup();
    render(<Harness showToast={showToast} />);
    await user.keyboard('{Control>}{F1}{/Control}');
    expect(showToast).toHaveBeenLastCalledWith('Posicionate sobre una publicación (flecha abajo) para usar este atajo', 'error');
    await user.keyboard('{ArrowDown}{ArrowDown}{Control>}{F1}{/Control}');
    expect(showToast).toHaveBeenLastCalledWith('La publicación no tiene producto vinculado', 'error');
    expect(await copied()).toBe('');
  });
});

describe("r / w / o (S9): the focused row's product rebate, web transfer and fuera de tarjetas, as in Productos", () => {
  it('each key flips its toggle on the focused row', async () => {
    const onToggleRow = vi.fn();
    const user = userEvent.setup();
    render(<Harness onToggleRow={onToggleRow} />);
    await user.keyboard('{ArrowDown}r');
    expect(onToggleRow).toHaveBeenLastCalledWith('MLA1', 'rebate');
    await user.keyboard('{ArrowDown}w');
    expect(onToggleRow).toHaveBeenLastCalledWith('MLA2', 'web');
    await user.keyboard('o');
    expect(onToggleRow).toHaveBeenLastCalledWith('MLA2', 'tarjetas');
    // A held key repeats: only its first press flips.
    fireEvent.keyDown(document.activeElement, { key: 'r', code: 'KeyR', repeat: true });
    expect(onToggleRow).toHaveBeenCalledTimes(3);
  });

  it('says where to stand without a focused row, and never runs while typing, with a modifier or where not offered', async () => {
    const onToggleRow = vi.fn();
    const showToast = vi.fn();
    const user = userEvent.setup();
    const { unmount } = render(<Harness onToggleRow={onToggleRow} showToast={showToast} />);
    await user.keyboard('r');
    expect(showToast).toHaveBeenCalledWith('Posicionate sobre una publicación (flecha abajo) para usar este atajo', 'error');
    await user.click(screen.getByRole('textbox', { name: 'Buscar' }));
    await user.keyboard('rwo');
    screen.getByRole('textbox', { name: 'Buscar' }).blur();
    await user.keyboard('{ArrowDown}{Shift>}r{/Shift}');
    expect(onToggleRow).not.toHaveBeenCalled();
    unmount();
    showToast.mockClear();
    render(<Harness showToast={showToast} />);
    await user.keyboard('{ArrowDown}r');
    expect(showToast).not.toHaveBeenCalled();
  });
});

describe("Shift+Up / Shift+Down (S12d): move and check the row moved to, as in Productos", () => {
  it('moves the focus like the plain arrow and hands the new row to onExtendRow', async () => {
    const onExtendRow = vi.fn();
    const user = userEvent.setup();
    render(<Harness onExtendRow={onExtendRow} />);
    await user.keyboard('{ArrowDown}{Shift>}{ArrowDown}{ArrowDown}{/Shift}');
    expect(row(3)).toHaveFocus();
    expect(onExtendRow.mock.calls).toEqual([['MLA2'], ['MLA3']]);
    await user.keyboard('{Shift>}{ArrowUp}{/Shift}');
    expect(row(2)).toHaveFocus();
    expect(onExtendRow).toHaveBeenLastCalledWith('MLA2');
  });

  it('checks nothing with the plain arrows, past the last row, or where not offered', async () => {
    const onExtendRow = vi.fn();
    const user = userEvent.setup();
    const { unmount } = render(<Harness onExtendRow={onExtendRow} />);
    await user.keyboard('{ArrowDown}{ArrowDown}{End}{Shift>}{ArrowDown}{/Shift}');
    expect(row(15)).toHaveFocus();
    expect(onExtendRow).not.toHaveBeenCalled();
    unmount();
    render(<Harness />);
    await user.keyboard('{ArrowDown}{Shift>}{ArrowDown}{/Shift}');
    expect(row(2)).toHaveFocus();
  });
});

describe('colors (S8): 0-7 paint the focused row, F6/F7 change the layer, as in Productos', () => {
  it("0-7 paint the focused row's product with Productos' colors in Productos' order (0 = no color)", async () => {
    const onPaintRow = vi.fn();
    const user = userEvent.setup();
    render(<Harness onPaintRow={onPaintRow} />);
    await user.keyboard('{ArrowDown}{ArrowDown}1');
    expect(onPaintRow).toHaveBeenLastCalledWith('MLA2', 'rojo');
    await user.keyboard('7');
    expect(onPaintRow).toHaveBeenLastCalledWith('MLA2', 'gris');
    await user.keyboard('0');
    expect(onPaintRow).toHaveBeenLastCalledWith('MLA2', null);
    await user.keyboard('8');
    expect(onPaintRow).toHaveBeenCalledTimes(3);
  });

  it('says where to stand without a focused row, and never paints while typing or with a modifier', async () => {
    const onPaintRow = vi.fn();
    const showToast = vi.fn();
    const user = userEvent.setup();
    render(<Harness onPaintRow={onPaintRow} showToast={showToast} />);
    await user.keyboard('3');
    expect(showToast).toHaveBeenCalledWith('Posicionate sobre una publicación (flecha abajo) para usar este atajo', 'error');
    await user.click(screen.getByRole('textbox', { name: 'Buscar' }));
    await user.keyboard('3');
    screen.getByRole('textbox', { name: 'Buscar' }).blur();
    await user.keyboard('{ArrowDown}{Alt>}3{/Alt}');
    expect(onPaintRow).not.toHaveBeenCalled();
  });

  it('leaves the digits alone where painting is not offered', async () => {
    const showToast = vi.fn();
    const user = userEvent.setup();
    render(<Harness showToast={showToast} />);
    await user.keyboard('{ArrowDown}3');
    expect(showToast).not.toHaveBeenCalled();
  });

  it('F6 / F7 step to the previous / next layer, from anywhere but a field', async () => {
    const onCycleLayer = vi.fn();
    const user = userEvent.setup();
    render(<Harness onCycleLayer={onCycleLayer} />);
    expect(fireEvent.keyDown(document.body, { key: 'F7', code: 'F7' })).toBe(false);
    expect(onCycleLayer).toHaveBeenLastCalledWith(1);
    await user.keyboard('{F6}');
    expect(onCycleLayer).toHaveBeenLastCalledWith(-1);
    await user.click(screen.getByRole('textbox', { name: 'Buscar' }));
    await user.keyboard('{F7}');
    expect(onCycleLayer).toHaveBeenCalledTimes(2);
  });
});

describe("Ctrl+I: the focused row's product information, as in Productos", () => {
  it('opens it for the focused row (Ctrl or Cmd, the key not the character), taken from the browser', async () => {
    const onShowInfo = vi.fn();
    const user = userEvent.setup();
    render(<Harness onShowInfo={onShowInfo} />);
    await user.click(row(2));
    expect(fireEvent.keyDown(document.body, { key: 'i', code: 'KeyI', ctrlKey: true })).toBe(false);
    expect(onShowInfo).toHaveBeenLastCalledWith(ROWS[1].item_id);
    fireEvent.keyDown(document.body, { key: 'I', code: 'KeyI', metaKey: true });
    expect(onShowInfo).toHaveBeenCalledTimes(2);
  });

  it('with no row focused it says how, and it does nothing while typing', async () => {
    const onShowInfo = vi.fn();
    const showToast = vi.fn();
    const user = userEvent.setup();
    render(<Harness onShowInfo={onShowInfo} showToast={showToast} />);
    fireEvent.keyDown(document.body, { key: 'i', code: 'KeyI', ctrlKey: true });
    expect(onShowInfo).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('Posicionate'), 'error');
    await user.click(screen.getByRole('textbox', { name: 'Buscar' }));
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Buscar' }), { key: 'i', code: 'KeyI', ctrlKey: true });
    expect(onShowInfo).not.toHaveBeenCalled();
  });

  it("Productos' info modal (`.modal-overlay`) owns the keyboard while open: the arrows do not move the list", async () => {
    const user = userEvent.setup();
    render(
      <>
        <Harness />
        <div className="modal-overlay" />
      </>,
    );
    await user.click(row(1));
    fireEvent.keyDown(row(1), { key: 'ArrowDown' });
    expect(row(1)).toHaveFocus();
  });
});

describe("Productos' bulk and filter shortcuts (S9b)", () => {
  it('Ctrl+K opens Calcular Web Transf., Ctrl+Shift+P Calcular PVP, taken from the browser (Caps Lock or not)', () => {
    const onBulkAction = vi.fn();
    render(<Harness onBulkAction={onBulkAction} />);
    expect(fireEvent.keyDown(document.body, { key: 'k', code: 'KeyK', ctrlKey: true })).toBe(false);
    expect(onBulkAction).toHaveBeenLastCalledWith('web');
    expect(fireEvent.keyDown(document.body, { key: 'P', code: 'KeyP', ctrlKey: true, shiftKey: true })).toBe(false);
    expect(onBulkAction).toHaveBeenLastCalledWith('pvp');
    fireEvent.keyDown(document.body, { key: 'p', code: 'KeyP', ctrlKey: true });
    expect(onBulkAction).toHaveBeenCalledTimes(2);
  });

  it('Alt+M / Alt+S / Alt+P open the Marca, Subcategoría and PM filters (the key, not the character a Mac types)', () => {
    const onOpenFilter = vi.fn();
    render(<Harness onOpenFilter={onOpenFilter} />);
    expect(fireEvent.keyDown(document.body, { key: 'µ', code: 'KeyM', altKey: true })).toBe(false);
    expect(onOpenFilter).toHaveBeenLastCalledWith('marcas');
    fireEvent.keyDown(document.body, { key: 's', code: 'KeyS', altKey: true });
    expect(onOpenFilter).toHaveBeenLastCalledWith('subcategorias');
    fireEvent.keyDown(document.body, { key: 'p', code: 'KeyP', altKey: true });
    expect(onOpenFilter).toHaveBeenLastCalledWith('pms');
  });

  it("Alt+A opens the Auditoría filters and Alt+C / Alt+F the presence ones (Productos' Avanzados), by the key", () => {
    const onOpenFilter = vi.fn();
    render(<Harness onOpenFilter={onOpenFilter} />);
    expect(fireEvent.keyDown(document.body, { key: 'å', code: 'KeyA', altKey: true })).toBe(false);
    expect(onOpenFilter).toHaveBeenLastCalledWith('auditoria');
    expect(fireEvent.keyDown(document.body, { key: 'ç', code: 'KeyC', altKey: true })).toBe(false);
    expect(onOpenFilter).toHaveBeenLastCalledWith('presencia');
    // Alt+F is the browsers' menu key: taken from them too.
    expect(fireEvent.keyDown(document.body, { key: 'ƒ', code: 'KeyF', altKey: true })).toBe(false);
    expect(onOpenFilter).toHaveBeenLastCalledWith('presencia');
    expect(onOpenFilter).toHaveBeenCalledTimes(3);
  });

  it("Alt+V steps through the price columns' modes (the key, not the character a Mac types), not while typing", async () => {
    const onCycleMode = vi.fn();
    const user = userEvent.setup();
    render(<Harness onCycleMode={onCycleMode} />);
    expect(fireEvent.keyDown(document.body, { key: '√', code: 'KeyV', altKey: true })).toBe(false);
    expect(onCycleMode).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('textbox', { name: 'Buscar' }));
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Buscar' }), { key: 'v', code: 'KeyV', altKey: true });
    expect(onCycleMode).toHaveBeenCalledTimes(1);
  });

  it("Alt+R flips Productos' Auto-recalcular cuotas (S12f2; the key, not the character a Mac types), once per press, not while typing", async () => {
    const onToggleAutoRecalc = vi.fn();
    const onToggleRow = vi.fn();
    const user = userEvent.setup();
    render(<Harness onToggleAutoRecalc={onToggleAutoRecalc} onToggleRow={onToggleRow} />);
    expect(fireEvent.keyDown(document.body, { key: '®', code: 'KeyR', altKey: true })).toBe(false);
    expect(onToggleAutoRecalc).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document.body, { key: 'r', code: 'KeyR', altKey: true, repeat: true });
    expect(onToggleAutoRecalc).toHaveBeenCalledTimes(1);
    // Plain r is still the focused row's rebate, never Auto-recalcular.
    await user.click(row(1));
    fireEvent.keyDown(document.body, { key: 'r', code: 'KeyR' });
    expect(onToggleRow).toHaveBeenCalledTimes(1);
    expect(onToggleAutoRecalc).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('textbox', { name: 'Buscar' }));
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Buscar' }), { key: 'r', code: 'KeyR', altKey: true });
    expect(onToggleAutoRecalc).toHaveBeenCalledTimes(1);
  });

  it('none of them runs while typing in a field', async () => {
    const onBulkAction = vi.fn();
    const onOpenFilter = vi.fn();
    const user = userEvent.setup();
    render(<Harness onBulkAction={onBulkAction} onOpenFilter={onOpenFilter} />);
    await user.click(screen.getByRole('textbox', { name: 'Buscar' }));
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Buscar' }), { key: 'k', code: 'KeyK', ctrlKey: true });
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Buscar' }), { key: 'm', code: 'KeyM', altKey: true });
    expect(onBulkAction).not.toHaveBeenCalled();
    expect(onOpenFilter).not.toHaveBeenCalled();
  });
});
