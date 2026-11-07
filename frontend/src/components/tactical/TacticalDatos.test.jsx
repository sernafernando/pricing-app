/**
 * TacticalDatos (the type and data card of Nuevo tactical) and TacticalDescartar (its discard dialog).
 */
import { describe, it, expect, vi } from 'vitest';
import { useState } from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TacticalDatos from './TacticalDatos';
import TacticalDescartar from './TacticalDescartar';

const FORM = {
  tipo: 'sell_out',
  nombre: '',
  marca: '',
  referencia: '',
  fechaDesde: '',
  fechaHasta: '',
  moneda: 'USD',
  tcModo: 'al_cobro',
  tipoCambio: '',
  incluyeIva: false,
  acumulable: true,
  todasTiendas: true,
  topeCompartido: false,
  tiendaKeys: [],
  nota: '',
};

function Holder({ inicial = {}, onTipo = vi.fn(), tiposNoDisponibles, onForm = vi.fn() }) {
  const [form, setForm] = useState({ ...FORM, ...inicial });
  onForm(form);
  return (
    <TacticalDatos
      form={form}
      onChange={(cambios) => setForm((f) => ({ ...f, ...cambios }))}
      onTipo={onTipo}
      tiposNoDisponibles={tiposNoDisponibles}
      marcas={['HP', 'TP-Link']}
    />
  );
}

describe('TacticalDatos', () => {
  it('offers the types the user can manage and says which is on', async () => {
    const user = userEvent.setup();
    const onTipo = vi.fn();
    render(<Holder onTipo={onTipo} tiposNoDisponibles={['sell_in']} />);
    const tipo = screen.getByRole('group', { name: 'Tipo' });
    expect(within(tipo).getByRole('button', { name: 'Sell out' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(tipo).getByRole('button', { name: 'Sell in' })).toBeDisabled();
    expect(screen.getByRole('heading', { name: 'Datos del tactical' })).toBeInTheDocument();
    await user.click(within(tipo).getByRole('button', { name: 'Sell in' }));
    expect(onTipo).not.toHaveBeenCalled();
  });

  it('switches the type through onTipo', async () => {
    const user = userEvent.setup();
    const onTipo = vi.fn();
    render(<Holder onTipo={onTipo} />);
    await user.click(within(screen.getByRole('group', { name: 'Tipo' })).getByRole('button', { name: 'Sell in' }));
    expect(onTipo).toHaveBeenCalledWith('sell_in');
  });

  it('fills the data as typed', async () => {
    const user = userEvent.setup();
    const onForm = vi.fn();
    render(<Holder onForm={onForm} />);
    await user.type(screen.getByLabelText('Nombre'), 'Tacticals BPS');
    await user.selectOptions(screen.getByLabelText('Marca'), 'HP');
    await user.type(screen.getByLabelText('Referencia de la marca'), 'Q1 FY27');
    await user.type(screen.getByLabelText('Desde'), '2026-11-01');
    await user.type(screen.getByLabelText('Hasta'), '2026-11-30');
    await user.click(screen.getByLabelText('Los montos incluyen IVA'));
    await user.click(screen.getByLabelText('Se acumula con otras campañas'));
    await user.type(screen.getByLabelText('Nota'), 'Acuerdo 77');
    expect(screen.getByText('Cómo se aplica el tope')).toBeInTheDocument();
    expect(onForm).toHaveBeenLastCalledWith({
      ...FORM,
      nombre: 'Tacticals BPS',
      marca: 'HP',
      referencia: 'Q1 FY27',
      fechaDesde: '2026-11-01',
      fechaHasta: '2026-11-30',
      incluyeIva: true,
      acumulable: false,
      nota: 'Acuerdo 77',
    });
  });

  it('caps the texts at what the contract accepts', () => {
    render(<Holder />);
    expect(screen.getByLabelText('Nombre')).toHaveAttribute('maxLength', '200');
    expect(screen.getByLabelText('Referencia de la marca')).toHaveAttribute('maxLength', '200');
    expect(screen.getByLabelText('Nota')).toHaveAttribute('maxLength', '2000');
  });

  it('tells assistive tech which fields are required, not only the hidden asterisk', () => {
    render(<Holder />);
    for (const campo of ['Nombre', 'Marca', 'Desde', 'Hasta']) {
      expect(screen.getByLabelText(campo)).toHaveAttribute('aria-required', 'true');
    }
    expect(screen.getByLabelText('Referencia de la marca')).not.toHaveAttribute('aria-required');
  });

  it('renders with no brands passed', () => {
    render(<TacticalDatos form={FORM} onChange={vi.fn()} onTipo={vi.fn()} />);
    expect(within(screen.getByLabelText('Marca')).getAllByRole('option').map((o) => o.textContent)).toEqual(['Elegí una marca']);
  });

  it('asks the exchange-rate mode only in USD, and the value only for a fixed rate', async () => {
    const user = userEvent.setup();
    const onForm = vi.fn();
    render(<Holder onForm={onForm} />);
    expect(screen.queryByLabelText('Tipo de cambio fijo')).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Tipo de cambio'), 'Fijo');
    await user.type(screen.getByLabelText('Tipo de cambio fijo'), '1.450,5');
    expect(onForm).toHaveBeenLastCalledWith(expect.objectContaining({ tcModo: 'fijo', tipoCambio: '1.450,5' }));
    await user.click(within(screen.getByRole('group', { name: 'Moneda' })).getByRole('button', { name: 'ARS' }));
    expect(screen.queryByLabelText('Tipo de cambio')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Tipo de cambio fijo')).not.toBeInTheDocument();
  });
});

describe('TacticalDescartar', () => {
  it('starts on "Seguir editando", keeps Tab inside, and Escape or a choice answers', async () => {
    const user = userEvent.setup();
    const onSeguir = vi.fn();
    const onDescartar = vi.fn();
    render(<TacticalDescartar onSeguir={onSeguir} onDescartar={onDescartar} />);
    const dialog = screen.getByRole('dialog', { name: '¿Descartar el tactical?' });
    const seguir = within(dialog).getByRole('button', { name: 'Seguir editando' });
    expect(seguir).toHaveFocus();
    await user.tab();
    expect(within(dialog).getByRole('button', { name: 'Descartar' })).toHaveFocus();
    await user.tab();
    expect(seguir).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(onSeguir).toHaveBeenCalledTimes(1);
    await user.click(within(dialog).getByRole('button', { name: 'Descartar' }));
    expect(onDescartar).toHaveBeenCalledTimes(1);
  });
});
