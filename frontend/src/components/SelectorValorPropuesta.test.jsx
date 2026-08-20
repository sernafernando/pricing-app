import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import SelectorValorPropuesta from './SelectorValorPropuesta';

/**
 * Covers spec `frontend/tickets-correction-ui` — "Confirm Offers A Value
 * Selector For Severidad/Urgencia" — at the component level, isolated from
 * `TicketProposals`. Per tasks doc #1505 PR2 task 1: renders a `<select>`
 * defaulted to the AI-proposed value; options match the field's closed
 * vocabulary; `onChange` fires with the new value.
 *
 * Known trap (obs #1350 / this PR's prompt): `user.type()` has shown
 * flakiness in this suite — `fireEvent.change` is used instead, matching
 * the workaround already used in `TicketProposals.test.jsx`.
 */
describe('SelectorValorPropuesta', () => {
  it('defaults to the AI-proposed value for severidad', () => {
    render(<SelectorValorPropuesta campo="severidad" valorPropuesto="mayor" onChange={vi.fn()} />);
    expect(screen.getByRole('combobox')).toHaveValue('mayor');
  });

  it('defaults to the AI-proposed value for urgencia', () => {
    render(<SelectorValorPropuesta campo="urgencia" valorPropuesto="alta" onChange={vi.fn()} />);
    expect(screen.getByRole('combobox')).toHaveValue('alta');
  });

  it('offers exactly the severidad vocabulary and nothing else', () => {
    render(<SelectorValorPropuesta campo="severidad" valorPropuesto="mayor" onChange={vi.fn()} />);
    const opciones = screen.getAllByRole('option').map((o) => o.value);
    expect(opciones).toEqual(['trivial', 'menor', 'mayor', 'critica']);
  });

  it('offers exactly the urgencia vocabulary and nothing else', () => {
    render(<SelectorValorPropuesta campo="urgencia" valorPropuesto="alta" onChange={vi.fn()} />);
    const opciones = screen.getAllByRole('option').map((o) => o.value);
    expect(opciones).toEqual(['baja', 'normal', 'alta', 'inmediata']);
  });

  it('fires onChange with the newly selected value', () => {
    const onChange = vi.fn();
    render(<SelectorValorPropuesta campo="severidad" valorPropuesto="mayor" onChange={onChange} />);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'menor' } });
    expect(onChange).toHaveBeenCalledWith('menor');
  });

  it('shows the AI-proposed value as reference copy, es_AR', () => {
    render(<SelectorValorPropuesta campo="severidad" valorPropuesto="mayor" onChange={vi.fn()} />);
    expect(screen.getByText((text) => text.includes('IA propuso') && text.includes('mayor'))).toBeInTheDocument();
  });

  it('shows a "Corregido a" indicator only when the selection differs from the AI value', () => {
    const { rerender } = render(
      <SelectorValorPropuesta campo="severidad" valorPropuesto="mayor" value="mayor" onChange={vi.fn()} />
    );
    expect(screen.queryByText((text) => text.includes('Corregido a'))).not.toBeInTheDocument();

    rerender(<SelectorValorPropuesta campo="severidad" valorPropuesto="mayor" value="menor" onChange={vi.fn()} />);
    expect(screen.getByText((text) => text.includes('Corregido a') && text.includes('menor'))).toBeInTheDocument();
  });
});
