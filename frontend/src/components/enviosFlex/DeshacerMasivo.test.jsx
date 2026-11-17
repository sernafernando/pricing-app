import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../../services/api';
import DeshacerSeleccionModal from './DeshacerSeleccionModal';
import OperacionesMasivasModal from './OperacionesMasivasModal';
import SobrescribirLogisticaModal from './SobrescribirLogisticaModal';

const RAYO = { id: 1, nombre: 'Rayo Express', color: '#2563eb' };
const MOTO = { id: 2, nombre: 'Moto Sur', color: '#16a34a' };

const RESULTADO = {
  revertidas: 3,
  no_revertidas: 2,
  no_revertidas_por_motivo: [
    {
      motivo: 'La etiqueta cambió de logística después de esta operación.',
      cantidad: 1,
      shipping_ids: ['44800000002'],
    },
    { motivo: 'La logística anterior está inactiva.', cantidad: 1, shipping_ids: ['44800000005'] },
  ],
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('DeshacerSeleccionModal (S2)', () => {
  const renderModal = () => {
    const onClose = vi.fn();
    const onListo = vi.fn();
    render(
      <DeshacerSeleccionModal
        shippingIds={['44800000001', '44800000002', '44800000003']}
        operadorId={7}
        onClose={onClose}
        onListo={onListo}
      />,
    );
    return { onClose, onListo };
  };

  it('asks before undoing, naming how many labels', () => {
    const post = vi.spyOn(api, 'post');
    renderModal();

    expect(screen.getByText(/3 etiquetas seleccionadas/)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it('undoes the selection and reports reverted and skipped labels with the reasons', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: RESULTADO });
    const { onListo } = renderModal();

    await userEvent.click(screen.getByRole('button', { name: /Deshacer 3 etiquetas/ }));

    expect(post).toHaveBeenCalledWith('/etiquetas-envio/deshacer-logistica-masivo', {
      shipping_ids: ['44800000001', '44800000002', '44800000003'],
      operador_id: 7,
    });
    const resultado = await screen.findByRole('status');
    expect(within(resultado).getByText(/3 volvieron a su logística anterior/)).toBeInTheDocument();
    expect(within(resultado).getByText(/2 no se pudieron deshacer/)).toBeInTheDocument();
    expect(
      within(resultado).getByText('La etiqueta cambió de logística después de esta operación.'),
    ).toBeInTheDocument();
    expect(within(resultado).getByText('44800000005')).toBeInTheDocument();
    expect(onListo).toHaveBeenCalledWith(RESULTADO);
  });

  it('shows the server error and stays open', async () => {
    vi.spyOn(api, 'post').mockRejectedValue({ response: { data: { detail: 'Operador no encontrado o inactivo' } } });
    const { onListo } = renderModal();

    await userEvent.click(screen.getByRole('button', { name: /Deshacer 3 etiquetas/ }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Operador no encontrado o inactivo');
    expect(onListo).not.toHaveBeenCalled();
  });
});

describe('OperacionesMasivasModal (S3)', () => {
  const OPERACIONES = [
    {
      id: 41,
      usuario_nombre: 'Ana Gómez',
      cambiado_en: new Date(2026, 10, 17, 14, 32).toISOString(),
      logistica: MOTO,
      etiquetas: 120,
    },
    {
      id: 30,
      usuario_nombre: null,
      cambiado_en: new Date(2026, 10, 17, 9, 5).toISOString(),
      logistica: RAYO,
      etiquetas: 1,
    },
  ];

  const renderModal = () => {
    const onClose = vi.fn();
    const onListo = vi.fn();
    render(<OperacionesMasivasModal operadorId={null} onClose={onClose} onListo={onListo} />);
    return { onClose, onListo };
  };

  it('lists who, when, target logistics and how many labels', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: OPERACIONES });
    renderModal();

    const filas = await screen.findAllByRole('listitem');
    expect(api.get).toHaveBeenCalledWith('/etiquetas-envio/operaciones-masivas-logistica');
    expect(filas).toHaveLength(2);
    expect(within(filas[0]).getByText('17/11 14:32')).toBeInTheDocument();
    expect(within(filas[0]).getByText('Ana Gómez')).toBeInTheDocument();
    expect(within(filas[0]).getByText('Moto Sur')).toBeInTheDocument();
    expect(within(filas[0]).getByText('120 etiquetas')).toBeInTheDocument();
    expect(within(filas[1]).getByText('1 etiqueta')).toBeInTheDocument();
  });

  it('reverts a whole operation after confirming and reports the result', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: OPERACIONES });
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: RESULTADO });
    const { onListo } = renderModal();

    const filas = await screen.findAllByRole('listitem');
    await userEvent.click(within(filas[0]).getByRole('button', { name: /Deshacer/ }));
    expect(post).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: /Confirmar/ }));

    expect(post).toHaveBeenCalledWith('/etiquetas-envio/operaciones-masivas-logistica/41/deshacer', {
      operador_id: null,
    });
    const resultado = await screen.findByRole('status');
    expect(within(resultado).getByText(/3 volvieron a su logística anterior/)).toBeInTheDocument();
    expect(within(resultado).getByText('44800000002')).toBeInTheDocument();
    expect(onListo).toHaveBeenCalledWith(RESULTADO);
  });

  it('says when there are no bulk assignments', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: [] });
    renderModal();

    expect(await screen.findByText('No hay asignaciones masivas registradas.')).toBeInTheDocument();
  });
});

describe('SobrescribirLogisticaModal (S4)', () => {
  const renderModal = () => {
    const onClose = vi.fn();
    const onAsignado = vi.fn();
    render(
      <SobrescribirLogisticaModal
        shippingIds={['44800000001', '44800000002', '44800000003', '44800000004']}
        logistica={MOTO}
        sobrescribiria={3}
        onClose={onClose}
        onAsignado={onAsignado}
      />,
    );
    return { onClose, onAsignado };
  };

  it('warns how many labels already have another logistics', () => {
    renderModal();

    expect(screen.getByText(/3 de las 4 etiquetas ya tienen otra logística/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Sobrescribir todas/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Solo las sin logística/ })).toBeInTheDocument();
  });

  it('overwrite all assigns every label', async () => {
    const put = vi.spyOn(api, 'put').mockResolvedValue({ data: { actualizadas: 4, salteadas: 0 } });
    const { onAsignado } = renderModal();

    await userEvent.click(screen.getByRole('button', { name: /Sobrescribir todas/ }));

    expect(put).toHaveBeenCalledWith('/etiquetas-envio/asignar-masivo', {
      shipping_ids: ['44800000001', '44800000002', '44800000003', '44800000004'],
      logistica_id: 2,
      solo_sin_logistica: false,
    });
    await waitFor(() =>
      expect(onAsignado).toHaveBeenCalledWith({ actualizadas: 4, salteadas: 0 }, { soloSinLogistica: false }),
    );
  });

  it('only without logistics skips the others and reports how many', async () => {
    const put = vi.spyOn(api, 'put').mockResolvedValue({ data: { actualizadas: 1, salteadas: 3 } });
    const { onAsignado } = renderModal();

    await userEvent.click(screen.getByRole('button', { name: /Solo las sin logística/ }));

    expect(put).toHaveBeenCalledWith(
      '/etiquetas-envio/asignar-masivo',
      expect.objectContaining({ solo_sin_logistica: true }),
    );
    const resultado = await screen.findByRole('status');
    expect(resultado).toHaveTextContent('1 etiqueta pasó a Moto Sur');
    expect(resultado).toHaveTextContent('3 se saltearon porque ya tenían otra logística');
    expect(onAsignado).toHaveBeenCalledWith({ actualizadas: 1, salteadas: 3 }, { soloSinLogistica: true });
  });
});

describe('mass undo modals close only through their buttons', () => {
  it.each([
    ['DeshacerSeleccionModal', (onClose) => <DeshacerSeleccionModal shippingIds={['1']} onClose={onClose} />],
    ['OperacionesMasivasModal', (onClose) => <OperacionesMasivasModal onClose={onClose} />],
    [
      'SobrescribirLogisticaModal',
      (onClose) => (
        <SobrescribirLogisticaModal shippingIds={['1', '2']} logistica={MOTO} sobrescribiria={1} onClose={onClose} />
      ),
    ],
  ])('%s ignores Escape and overlay clicks', async (_name, crear) => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: [] });
    const onClose = vi.fn();
    render(crear(onClose));

    await userEvent.keyboard('{Escape}');
    await userEvent.click(document.querySelector('.modal-overlay-tesla') ?? document.body);

    expect(onClose).not.toHaveBeenCalled();
  });
});
