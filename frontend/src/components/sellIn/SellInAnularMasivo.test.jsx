import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SellInAnularMasivo from './SellInAnularMasivo';
import { ANULAR_MASIVO_MAX } from './sellInAnularMasivo';

const props = (over = {}) => ({
  sustantivo: { singular: 'compra', plural: 'compras' },
  seleccionados: [7, 8],
  total: 30,
  revierte: 'Se liberan sus unidades.',
  onSeleccionarFiltrado: vi.fn(),
  onLimpiar: vi.fn(),
  anular: vi.fn().mockResolvedValue({ data: { anuladas: [7], ya_anuladas: [8] } }),
  onHecho: vi.fn(),
  ...over,
});

describe('SellInAnularMasivo — selection bar and confirmation', () => {
  it('shows nothing until something is selected, but offers selecting everything filtered', async () => {
    const p = props({ seleccionados: [] });
    render(<SellInAnularMasivo {...p} />);
    expect(screen.queryByRole('button', { name: 'Anular seleccionados' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Seleccionar todo lo filtrado (30)' }));
    expect(p.onSeleccionarFiltrado).toHaveBeenCalled();
  });

  it('confirms how many are voided and what is reversed, then voids with the reason', async () => {
    const user = userEvent.setup();
    const p = props();
    render(<SellInAnularMasivo {...p} />);
    expect(screen.getByText('2 seleccionados')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    const pane = screen.getByRole('dialog', { name: 'Anular 2 compras' });
    expect(pane).toHaveTextContent('Se van a anular 2 compras. Se liberan sus unidades.');
    expect(p.anular).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText('Motivo (opcional)'), 'Cargadas dos veces');
    await user.click(screen.getByRole('button', { name: 'Sí, anular 2' }));

    expect(p.anular).toHaveBeenCalledWith([7, 8], 'Cargadas dos veces');
    expect(p.onHecho).toHaveBeenCalledWith('Se anuló 1 compra. 1 ya estaba anulada.', { anuladas: [7], ya_anuladas: [8] });
  });

  it('a void that went through is never reported as failed, even when refreshing the page afterwards fails', async () => {
    const user = userEvent.setup();
    const p = props({ onHecho: vi.fn(() => { throw new Error('boom'); }) });
    render(<SellInAnularMasivo {...p} />);
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(screen.getByRole('button', { name: 'Sí, anular 2' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Se anularon, pero la pantalla no se pudo actualizar. Recargá la página.');
    expect(screen.queryByText(/No se pudieron anular/)).not.toBeInTheDocument();
  });

  it('cancelling the confirmation voids nothing', async () => {
    const user = userEvent.setup();
    const p = props();
    render(<SellInAnularMasivo {...p} />);
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(p.anular).not.toHaveBeenCalled();
  });

  it('a refused set voids nothing and names each refused record', async () => {
    const user = userEvent.setup();
    const error = Object.assign(new Error('409'), {
      response: {
        status: 409,
        data: { mensaje: 'No se anuló ninguna: 1 no se puede anular', rechazadas: [{ id: 8, motivo: 'La compra 8 la genera el bono de marca 3' }] },
      },
    });
    const p = props({ anular: vi.fn().mockRejectedValue(error) });
    render(<SellInAnularMasivo {...p} />);
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(screen.getByRole('button', { name: 'Sí, anular 2' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('No se anuló ninguna: 1 no se puede anular');
    expect(alert).toHaveTextContent('#8: La compra 8 la genera el bono de marca 3');
    expect(p.onHecho).not.toHaveBeenCalled();
  });

  it('a failed "todo lo filtrado" shows why and sends nothing', async () => {
    const p = props({ seleccionados: [], onSeleccionarFiltrado: vi.fn().mockRejectedValue(new Error('La lista cambió mientras se seleccionaba (2 de 3). Volvé a intentarlo.')) });
    render(<SellInAnularMasivo {...p} />);
    await userEvent.click(screen.getByRole('button', { name: 'Seleccionar todo lo filtrado (30)' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('La lista cambió mientras se seleccionaba (2 de 3).');
    expect(p.anular).not.toHaveBeenCalled();
  });

  it('speaks of bonuses in the masculine', async () => {
    const user = userEvent.setup();
    const p = props({ sustantivo: { singular: 'bono', plural: 'bonos' }, anular: vi.fn().mockRejectedValue(new Error('red')) });
    render(<SellInAnularMasivo {...p} />);
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('si alguno no se puede anular, no se anula ninguno. Los ya anulados se saltean.');
    await user.click(screen.getByRole('button', { name: 'Sí, anular 2' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron anular los bonos.');
  });

  it('the confirmation closes when the selection empties, and does not come back by itself', async () => {
    const user = userEvent.setup();
    const p = props();
    const { rerender } = render(<SellInAnularMasivo {...p} />);
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    rerender(<SellInAnularMasivo {...p} seleccionados={[]} />);
    rerender(<SellInAnularMasivo {...p} seleccionados={[9]} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('refuses more than the bulk limit before confirming', async () => {
    const user = userEvent.setup();
    const p = props({ seleccionados: Array.from({ length: ANULAR_MASIVO_MAX + 1 }, (_, i) => i + 1) });
    render(<SellInAnularMasivo {...p} />);
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    expect(screen.getByRole('alert')).toHaveTextContent(`Son ${ANULAR_MASIVO_MAX + 1}: se pueden anular hasta ${ANULAR_MASIVO_MAX} por vez.`);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(p.anular).not.toHaveBeenCalled();
  });

  it('says "1 seleccionado" for a single row', () => {
    render(<SellInAnularMasivo {...props({ seleccionados: [7] })} />);
    expect(screen.getByText('1 seleccionado')).toBeInTheDocument();
  });

  it('a failed list read says so in Spanish, not with the raw request error', async () => {
    const error = Object.assign(new Error('Network Error'), { isAxiosError: true });
    render(<SellInAnularMasivo {...props({ seleccionados: [], onSeleccionarFiltrado: vi.fn().mockRejectedValue(error) })} />);
    await userEvent.click(screen.getByRole('button', { name: 'Seleccionar todo lo filtrado (30)' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo leer la lista para seleccionar todo lo filtrado.');
    expect(screen.getByRole('alert')).not.toHaveTextContent('Network Error');
  });

  it('an old refusal goes away on "Cancelar", on "Limpiar selección" and when the selection empties', async () => {
    const user = userEvent.setup();
    const error = Object.assign(new Error('409'), { response: { status: 409, data: { mensaje: 'No se anuló ninguna: 1 no se puede anular', rechazadas: [] } } });
    const p = props({ anular: vi.fn().mockRejectedValue(error) });
    const { rerender } = render(<SellInAnularMasivo {...p} />);
    const rechazar = async () => {
      await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
      await user.click(screen.getByRole('button', { name: 'Sí, anular 2' }));
      await screen.findByRole('alert');
    };

    await rechazar();
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    await rechazar();
    await user.click(screen.getByRole('button', { name: 'Limpiar selección' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    await rechazar();
    rerender(<SellInAnularMasivo {...p} seleccionados={[]} />);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
