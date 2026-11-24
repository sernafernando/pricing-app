/**
 * The approval box a bonus, purchase or campaign panel shows while the record waits for approval (tacticals approval
 * S6, S8): what pending means, and Aprobar (with a confirmation) for a record loaded on its own when the user holds
 * `tacticals.aprobar`; a tactical's line says it is approved with its tactical.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AprobacionCarga from './AprobacionCarga';

describe('AprobacionCarga', () => {
  it('shows nothing for an approved or voided record', () => {
    const { container, rerender } = render(<AprobacionCarga estado="activa" puedeAprobar onAprobar={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<AprobacionCarga estado="anulada" puedeAprobar onAprobar={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('a pending record says it applies nothing, and without the permission offers no button', () => {
    render(<AprobacionCarga estado="pendiente" onAprobar={vi.fn()} />);

    expect(screen.getByRole('note')).toHaveTextContent('Pendiente de aprobación: no aplica hasta que lo aprueben.');
    expect(screen.queryByRole('button', { name: 'Aprobar' })).not.toBeInTheDocument();
  });

  it("a tactical's line is approved with its tactical", () => {
    render(<AprobacionCarga estado="pendiente" tacticalId={4} puedeAprobar onAprobar={vi.fn()} />);

    expect(screen.getByRole('note')).toHaveTextContent('Se aprueba desde su tactical.');
    expect(screen.queryByRole('button', { name: 'Aprobar' })).not.toBeInTheDocument();
  });

  it('asks for confirmation before approving; Cancelar approves nothing', async () => {
    const user = userEvent.setup();
    const onAprobar = vi.fn().mockResolvedValue(undefined);
    render(<AprobacionCarga estado="pendiente" puedeAprobar onAprobar={onAprobar} />);

    await user.click(screen.getByRole('button', { name: 'Aprobar' }));
    expect(screen.getByText('¿Aprobarlo? Empieza a aplicar desde ahora.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(onAprobar).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Aprobar' }));
    await user.click(screen.getByRole('button', { name: 'Confirmar aprobación' }));
    await waitFor(() => expect(onAprobar).toHaveBeenCalledTimes(1));
  });

  it("shows the server's refusal", async () => {
    const user = userEvent.setup();
    const onAprobar = vi.fn().mockRejectedValue({ response: { status: 409, data: { error: { message: 'El bono 3 ya está aprobado' } } } });
    render(<AprobacionCarga estado="pendiente" puedeAprobar onAprobar={onAprobar} />);

    await user.click(screen.getByRole('button', { name: 'Aprobar' }));
    await user.click(screen.getByRole('button', { name: 'Confirmar aprobación' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('El bono 3 ya está aprobado');
  });
});
