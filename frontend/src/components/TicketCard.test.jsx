import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import TicketCard from './TicketCard';

/**
 * Covers spec `frontend/tickets-board`:
 * - "Provenance Is Always Visible" — distinct badges per *_origen value.
 * - The board's whole point: a pending-proposals indicator so the
 *   maintainer knows where his attention is owed (obs #1305's slice note).
 */

function ticket(overrides = {}) {
  return {
    id: 42,
    titulo: 'No puedo facturar desde ayer',
    resumen: 'El cliente no puede generar la factura',
    severidad: 'critica',
    urgencia: 'alta',
    severidad_origen: 'ia_confirmada',
    urgencia_origen: 'humano',
    estado: { id: 1, codigo: 'abierto', nombre: 'Abierto', es_final: false },
    sector: { id: 1, codigo: 'soporte', nombre: 'Soporte' },
    created_at: '2026-08-06T10:00:00Z',
    propuestas_pendientes: 0,
    ...overrides,
  };
}

describe('TicketCard', () => {
  it('shows titulo, resumen and severity/urgency with distinct provenance badges', () => {
    render(<TicketCard ticket={ticket()} />);

    expect(screen.getByText('No puedo facturar desde ayer')).toBeInTheDocument();
    expect(screen.getByText('El cliente no puede generar la factura')).toBeInTheDocument();
    expect(screen.getByText('critica')).toBeInTheDocument();
    expect(screen.getByText('alta')).toBeInTheDocument();

    const badges = screen.getAllByText(/Manual|IA confirmada/);
    expect(badges).toHaveLength(2);
    // Visibly distinct — not just different text, different class too.
    expect(badges[0].className).not.toBe(badges[1].className);
  });

  it('shows a pending-proposals indicator when propuestas_pendientes > 0', () => {
    render(<TicketCard ticket={ticket({ propuestas_pendientes: 3 })} />);

    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('shows no pending-proposals indicator when propuestas_pendientes is 0', () => {
    render(<TicketCard ticket={ticket({ propuestas_pendientes: 0 })} />);

    expect(screen.queryByTitle(/propuesta/i)).not.toBeInTheDocument();
  });

  it('calls onClick with the ticket id when clicked', () => {
    const onClick = vi.fn();
    render(<TicketCard ticket={ticket({ id: 99 })} onClick={onClick} />);

    fireEvent.click(screen.getByRole('button'));

    expect(onClick).toHaveBeenCalledWith(99);
  });
});
