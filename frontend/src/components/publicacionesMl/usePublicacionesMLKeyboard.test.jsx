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

function Harness({ onOpen = () => {}, onExport, showToast = () => {}, rows = ROWS }) {
  const searchRef = useRef(null);
  const [help, setHelp] = useState(false);
  usePublicacionesMLKeyboard({
    searchRef,
    findRow: (key) => rows.find((row) => row.item_id === key),
    onExport,
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
