/**
 * TacticalPicker — the product / invoice picker of a tactical line, and Seg, the design's segmented control.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TacticalPicker from './TacticalPicker';
import Seg from './Seg';
import { CATALOGO } from './tacticalFixtures';

function abrir({ inicial = [], minimo = 2 } = {}) {
  const props = {
    titulo: 'Agregar productos a la línea',
    buscarLabel: 'Buscar productos',
    placeholder: 'Buscar por código o descripción',
    vacio: 'No hay productos para',
    minimo,
    buscar: vi.fn((q) =>
      Promise.resolve(CATALOGO.filter((p) => p.descripcion.toLowerCase().includes(q.toLowerCase()))),
    ),
    claveDe: (p) => p.item_id,
    fila: (p) => ({ codigo: p.codigo, descripcion: p.descripcion, meta: `Marca ${p.marca}` }),
    inicial,
    singular: 'seleccionado',
    plural: 'seleccionados',
    onAgregar: vi.fn(),
    onCerrar: vi.fn(),
  };
  render(
    <div>
      <p>Afuera</p>
      <TacticalPicker {...props} />
    </div>,
  );
  return { props, picker: screen.getByRole('dialog', { name: 'Agregar productos a la línea' }) };
}

describe('TacticalPicker', () => {
  it('searches from the shortest query it accepts and adds what is checked', async () => {
    const user = userEvent.setup();
    const { props, picker } = abrir();
    const buscar = within(picker).getByLabelText('Buscar productos');
    expect(buscar).toHaveFocus();
    await user.type(buscar, 'm');
    expect(props.buscar).not.toHaveBeenCalled();
    await user.type(buscar, 'onitor');
    await user.click(await within(picker).findByRole('checkbox', { name: /Monitor HP V24i G5/ }));
    expect(picker).toHaveTextContent('1 seleccionado');
    await user.click(within(picker).getByRole('button', { name: 'Agregar a la línea' }));
    expect(props.onAgregar).toHaveBeenCalledWith([CATALOGO.find((p) => p.item_id === 201)]);
  });

  it('opens with the line items checked and marked; unchecking one leaves it out', async () => {
    const user = userEvent.setup();
    const [v24, v27] = CATALOGO.filter((p) => [201, 202].includes(p.item_id));
    const { props, picker } = abrir({ inicial: [v24, v27] });
    expect(picker).toHaveTextContent('2 seleccionados');
    await user.type(within(picker).getByLabelText('Buscar productos'), 'monitor');
    const checkbox = await within(picker).findByRole('checkbox', { name: /Monitor HP V24i G5/ });
    expect(checkbox).toBeChecked();
    expect(within(picker).getAllByText('En la línea')).toHaveLength(2);
    await user.click(checkbox);
    // Enter in the search box adds too.
    await user.click(within(picker).getByLabelText('Buscar productos'));
    await user.keyboard('{Enter}');
    expect(props.onAgregar).toHaveBeenCalledWith([v27]);
  });

  it('says when nothing matches, and cannot add nothing', async () => {
    const user = userEvent.setup();
    const { picker } = abrir();
    expect(within(picker).getByRole('button', { name: 'Agregar a la línea' })).toBeDisabled();
    await user.type(within(picker).getByLabelText('Buscar productos'), 'zzz');
    expect(await within(picker).findByText('No hay productos para “zzz”.')).toBeInTheDocument();
  });

  it('closes on Escape, on Cancelar and on a click outside', async () => {
    const user = userEvent.setup();
    const { props, picker } = abrir();
    await user.keyboard('{Escape}');
    await user.click(within(picker).getByRole('button', { name: 'Cancelar' }));
    await user.click(screen.getByText('Afuera'));
    expect(props.onCerrar).toHaveBeenCalledTimes(3);
  });
});

describe('Seg', () => {
  it('presses the current option, changes only to another one, and keeps disabled ones out', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Seg
        label="Unidad del monto"
        options={[
          { value: 'por_unidad', label: 'por unidad' },
          { value: 'porcentaje', label: '%' },
          { value: 'monto_total', label: 'monto total' },
        ]}
        value="por_unidad"
        disabled={['monto_total']}
        onChange={onChange}
      />,
    );
    const grupo = screen.getByRole('group', { name: 'Unidad del monto' });
    expect(within(grupo).getByRole('button', { name: 'por unidad' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(grupo).getByRole('button', { name: 'monto total' })).toBeDisabled();
    await user.click(within(grupo).getByRole('button', { name: 'por unidad' }));
    await user.click(within(grupo).getByRole('button', { name: '%' }));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('porcentaje');
  });
});
