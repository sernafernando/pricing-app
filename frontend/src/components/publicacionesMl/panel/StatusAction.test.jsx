/**
 * "Pausar" / "Activar" in the publication panel (publicaciones-ml-producto-propio T4): only for who has
 * `ml_publicaciones.pausar`, only on an active or paused publication, always after a confirmation, and what
 * the server answered is said in words.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import StatusAction from './StatusAction';
import { readDetail } from './detailModel';
import { publicacionesMlAPI } from '../../../services/api';
import { ITEMS, makeDetail } from '../../../test/visual/publicacionesMlFixtures';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  publicacionesMlAPI: { setItemStatus: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

const ITEM_ID = 'MLA1100000001';
const httpError = (status, data) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data } });

const detailWith = ({ status = 'active', gone = false, subStatus = [], can = true } = {}) =>
  readDetail(makeDetail({ row: { ...ITEMS[0], status, gone }, sub_status: subStatus, can_change_status: can }));

const renderAction = (options, onChanged = vi.fn()) => {
  render(<StatusAction detail={detailWith(options)} itemId={ITEM_ID} onChanged={onChanged} />);
  return onChanged;
};

beforeEach(() => {
  publicacionesMlAPI.setItemStatus.mockReset();
  publicacionesMlAPI.setItemStatus.mockResolvedValue({ status: 200, data: { status: 'submitted', message: null } });
});

describe('who sees it and on what', () => {
  it('an active publication offers Pausar', () => {
    renderAction();
    expect(screen.getByRole('button', { name: 'Pausar' })).toBeInTheDocument();
  });

  it('a paused publication offers Activar', () => {
    renderAction({ status: 'paused' });
    expect(screen.getByRole('button', { name: 'Activar' })).toBeInTheDocument();
  });

  it.each([
    ['without the permission', { can: false }],
    ['on a closed publication', { status: 'closed' }],
    ['on one under review', { status: 'under_review' }],
    ['on one gone from ML', { gone: true }],
    ['on a deleted one', { status: 'paused', subStatus: ['deleted'] }],
  ])('nothing is offered %s', (_, options) => {
    renderAction(options);
    expect(screen.queryByRole('button', { name: /Pausar|Activar/ })).not.toBeInTheDocument();
  });
});

describe('the confirmation', () => {
  it('asks before writing, and Cancelar writes nothing', async () => {
    const user = userEvent.setup();
    renderAction();
    await user.click(screen.getByRole('button', { name: 'Pausar' }));
    expect(screen.getByText('¿Pausar la publicación en Mercado Libre?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(publicacionesMlAPI.setItemStatus).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Pausar' })).toBeInTheDocument();
  });

  it('Confirmar sends the target status once and re-reads the panel', async () => {
    const user = userEvent.setup();
    const onChanged = renderAction({ status: 'paused' });
    await user.click(screen.getByRole('button', { name: 'Activar' }));
    await user.click(screen.getByRole('button', { name: 'Confirmar' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Publicación activada en Mercado Libre.'));
    expect(publicacionesMlAPI.setItemStatus).toHaveBeenCalledTimes(1);
    expect(publicacionesMlAPI.setItemStatus).toHaveBeenCalledWith(ITEM_ID, 'active');
    expect(onChanged).toHaveBeenCalledTimes(1);
    // The store catches up in seconds: the button does not come back saying the old thing.
    expect(screen.queryByRole('button', { name: /Pausar|Activar/ })).not.toBeInTheDocument();
  });
});

describe('what the server answered', () => {
  const confirm = async (user) => {
    await user.click(screen.getByRole('button', { name: 'Pausar' }));
    await user.click(screen.getByRole('button', { name: 'Confirmar' }));
  };

  it('a publication already paused says so', async () => {
    publicacionesMlAPI.setItemStatus.mockResolvedValue({ status: 200, data: { status: 'unchanged', message: null } });
    const user = userEvent.setup();
    renderAction();
    await confirm(user);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('La publicación ya estaba pausada.'));
  });

  it('an ambiguous write shows the server message and still re-reads', async () => {
    publicacionesMlAPI.setItemStatus.mockResolvedValue({
      status: 202,
      data: { status: 'ambiguous', message: 'No se sabe si Mercado Libre aplicó el cambio: se vuelve a consultar.' },
    });
    const user = userEvent.setup();
    const onChanged = renderAction();
    await confirm(user);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('No se sabe si Mercado Libre aplicó el cambio'));
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('a refusal shows the server message, keeps the button and re-reads nothing', async () => {
    publicacionesMlAPI.setItemStatus.mockRejectedValue(httpError(422, { status: 'rejected', message: 'item has no stock' }));
    const user = userEvent.setup();
    const onChanged = renderAction();
    await confirm(user);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('item has no stock'));
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Pausar' })).toBeInTheDocument();
  });

  it('a 403 says the permission is missing', async () => {
    publicacionesMlAPI.setItemStatus.mockRejectedValue(httpError(403, { detail: 'forbidden' }));
    const user = userEvent.setup();
    renderAction();
    await confirm(user);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('No tenés permiso para pausar o activar publicaciones.'));
  });

  it('no answer at all asks to try again', async () => {
    publicacionesMlAPI.setItemStatus.mockRejectedValue(new Error('Network Error'));
    const user = userEvent.setup();
    renderAction();
    await confirm(user);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('No se pudo cambiar el estado. Probá de nuevo.'));
  });
});
