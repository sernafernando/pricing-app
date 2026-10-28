/**
 * "Actualizar en ML" (publicaciones-ml-producto-propio T8c): after a confirmation, send the publication's override to
 * Mercado Libre (`POST /ml-item-overrides/{mla}/ml`) and show how each field went: sent, rejected with ML's reason,
 * unconfirmed, not sent, or left out because ML does not let it change.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PushToMl from './PushToMl';
import { mlItemOverridesAPI } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  mlItemOverridesAPI: { get: vi.fn(), save: vi.fn(), pushToMl: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

// The push answers its own body on every status (it is not an error envelope).
const httpFailure = (status, data) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data } });

const renderPush = () => {
  const onPushed = vi.fn();
  render(<PushToMl itemId="MLA1" onPushed={onPushed} />);
  return onPushed;
};

const confirmPush = async () => {
  await userEvent.click(screen.getByRole('button', { name: 'Actualizar en ML' }));
  await userEvent.click(screen.getByRole('button', { name: 'Confirmar' }));
};

const result = () => screen.getByRole('region', { name: 'Resultado en Mercado Libre' });

beforeEach(() => {
  mlItemOverridesAPI.pushToMl.mockReset();
});

describe('confirming', () => {
  it('asks before sending, and Cancelar sends nothing', async () => {
    renderPush();
    await userEvent.click(screen.getByRole('button', { name: 'Actualizar en ML' }));

    expect(screen.getByText('Se envían a Mercado Libre los datos sobrescritos que difieren del original. ¿Actualizar MLA1?')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancelar' }));

    expect(mlItemOverridesAPI.pushToMl).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Actualizar en ML' })).toBeEnabled();
  });

  it('says it is sending and does not send twice', async () => {
    mlItemOverridesAPI.pushToMl.mockReturnValue(new Promise(() => {}));
    renderPush();
    await confirmPush();

    expect(screen.getByText('Enviando a Mercado Libre…')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirmar' })).not.toBeInTheDocument();
    expect(mlItemOverridesAPI.pushToMl).toHaveBeenCalledTimes(1);
    expect(mlItemOverridesAPI.pushToMl).toHaveBeenCalledWith('MLA1');
  });
});

describe('each field says how it went', () => {
  it('sent: submitted, rejected with ML message, unconfirmed and left out, one line each', async () => {
    mlItemOverridesAPI.pushToMl.mockResolvedValue({
      data: {
        status: 'sent',
        message: null,
        partes: [
          { campo: 'fotos', estado: 'submitted', motivo: null },
          { campo: 'atributos', estado: 'rejected', motivo: 'Attribute MODEL is not modifiable' },
          { campo: 'descripcion', estado: 'ambiguous', motivo: 'No se sabe si Mercado Libre aplicó el cambio: se vuelve a consultar.' },
          { campo: 'titulo', estado: 'omitted', motivo: 'La publicación tiene ventas: Mercado Libre no deja cambiar el título.' },
        ],
      },
    });
    const onPushed = renderPush();
    await confirmPush();

    const lines = within(await screen.findByRole('region', { name: 'Resultado en Mercado Libre' })).getAllByRole('listitem');
    expect(lines.map((line) => line.textContent)).toEqual([
      'Fotos: enviado a Mercado Libre.',
      'Atributos: Mercado Libre lo rechazó. Attribute MODEL is not modifiable',
      'Descripción: sin confirmar. No se sabe si Mercado Libre aplicó el cambio: se vuelve a consultar.',
      'Título: no se puede cambiar en Mercado Libre. La publicación tiene ventas: Mercado Libre no deja cambiar el título.',
    ]);
    expect(onPushed).toHaveBeenCalledTimes(1);
  });

  it('nothing to send says so', async () => {
    mlItemOverridesAPI.pushToMl.mockResolvedValue({ data: { status: 'nothing', message: 'No hay cambios para enviar a Mercado Libre.', partes: [] } });
    const onPushed = renderPush();
    await confirmPush();

    expect(await screen.findByRole('status')).toHaveTextContent('No hay cambios para enviar a Mercado Libre.');
    expect(onPushed).not.toHaveBeenCalled();
  });
});

describe('nothing reached ML', () => {
  it('503 not_sent (the write service does not forward it yet) explains it, lists each field and offers a retry', async () => {
    mlItemOverridesAPI.pushToMl.mockRejectedValueOnce(
      httpFailure(503, {
        status: 'not_sent',
        message: 'Ningún cambio llegó a Mercado Libre: el servicio de escritura lo rechazó.',
        partes: [{ campo: 'titulo', estado: 'not_sent', motivo: 'El cambio no se envió: el servicio de escritura lo rechazó.' }],
      }),
    );
    const onPushed = renderPush();
    await confirmPush();

    expect(await screen.findByRole('alert')).toHaveTextContent('Ningún cambio llegó a Mercado Libre: el servicio de escritura lo rechazó.');
    expect(within(result()).getByRole('listitem')).toHaveTextContent('Título: no se envió. El cambio no se envió: el servicio de escritura lo rechazó.');
    expect(onPushed).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Actualizar en ML' })).toBeEnabled();
  });

  it('409 says why the publication cannot be modified in ML', async () => {
    mlItemOverridesAPI.pushToMl.mockRejectedValue(
      httpFailure(409, { status: 'not_eligible', message: 'Las publicaciones de catálogo no se pueden modificar en Mercado Libre.', partes: [] }),
    );
    renderPush();
    await confirmPush();

    expect(await screen.findByRole('alert')).toHaveTextContent('Las publicaciones de catálogo no se pueden modificar en Mercado Libre.');
  });

  it('403 names the permission', async () => {
    mlItemOverridesAPI.pushToMl.mockRejectedValue(httpFailure(403, { error: { code: 'forbidden', message: 'forbidden' } }));
    renderPush();
    await confirmPush();

    expect(await screen.findByRole('alert')).toHaveTextContent('No tenés permiso para actualizar la publicación en Mercado Libre.');
  });

  it('a 5xx without the push body (gateway, crash after forwarding) may have landed: check first, read again', async () => {
    mlItemOverridesAPI.pushToMl.mockRejectedValue(httpFailure(502, '<html>Bad Gateway</html>'));
    const onPushed = renderPush();
    await confirmPush();

    expect(await screen.findByRole('alert')).toHaveTextContent('No se sabe si llegó a Mercado Libre. Revisá la publicación antes de volver a enviar.');
    expect(onPushed).toHaveBeenCalledTimes(1);
  });

  it('a push still out when the panel moves to another publication does not read that one again', async () => {
    let answer;
    mlItemOverridesAPI.pushToMl.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    const onPushed = vi.fn();
    const { unmount } = render(<PushToMl itemId="MLA1" onPushed={onPushed} />);
    await confirmPush();

    unmount();
    answer({ data: { status: 'sent', message: null, partes: [{ campo: 'titulo', estado: 'submitted', motivo: null }] } });
    await Promise.resolve();

    expect(onPushed).not.toHaveBeenCalled();
  });

  it('no answer at all is not a failure: it may have reached ML, so it says to check first', async () => {
    mlItemOverridesAPI.pushToMl.mockRejectedValue(new Error('timeout'));
    const onPushed = renderPush();
    await confirmPush();

    expect(await screen.findByRole('alert')).toHaveTextContent('No se sabe si llegó a Mercado Libre. Revisá la publicación antes de volver a enviar.');
    expect(onPushed).toHaveBeenCalledTimes(1);
  });
});
