/**
 * Banning a product from the product panel (publicaciones-ml-paridad-productos S12b), like Productos' ban: only for
 * ADMIN / SUPERADMIN or `admin.gestionar_mla_banlist` (the server checks the same), after typing back a word of the
 * product's description, with an optional reason. What the server answered is said in words.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductBanAction from './ProductBanAction';
import { productoBanlistAPI } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  productoBanlistAPI: { add: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

let access = { rol: 'ADMIN', granted: new Set() };
vi.mock('../../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ rol: access.rol, tienePermiso: (permiso) => access.granted.has(permiso) }),
}));

const httpError = (status, message) =>
  Object.assign(new Error(`HTTP ${status}`), { response: { status, data: { error: { code: 'error', message } } } });

const answer = (overrides = {}) => ({
  data: { agregados: ['Item ID 4101 - Router'], duplicados: [], no_encontrados: [], total_agregados: 1, ...overrides },
});

const renderAction = (description = 'Router Archer AX55') =>
  render(<ProductBanAction productItemId={4101} description={description} />);

/** Opens the confirmation and types back the word it asks for. */
async function confirmWith(user, { word, reason } = {}) {
  await user.click(screen.getByRole('button', { name: 'Agregar a la banlist' }));
  const asked = screen.getByTestId('ban-word').textContent;
  await user.type(screen.getByLabelText('Palabra de verificación'), word ?? asked);
  if (reason) await user.type(screen.getByLabelText('Motivo (opcional)'), reason);
  return asked;
}

beforeEach(() => {
  access = { rol: 'ADMIN', granted: new Set() };
  productoBanlistAPI.add.mockReset();
  productoBanlistAPI.add.mockResolvedValue(answer());
});

describe('who sees it', () => {
  it.each(['ADMIN', 'SUPERADMIN'])('%s sees the action', (rol) => {
    access = { rol, granted: new Set() };
    renderAction();
    expect(screen.getByRole('button', { name: 'Agregar a la banlist' })).toBeInTheDocument();
  });

  it('another role with admin.gestionar_mla_banlist sees it', () => {
    access = { rol: 'GERENTE', granted: new Set(['admin.gestionar_mla_banlist']) };
    renderAction();
    expect(screen.getByRole('button', { name: 'Agregar a la banlist' })).toBeInTheDocument();
  });

  it('another role without the permission does not', () => {
    access = { rol: 'GERENTE', granted: new Set() };
    renderAction();
    expect(screen.queryByRole('button', { name: 'Agregar a la banlist' })).not.toBeInTheDocument();
  });
});

describe('the confirmation', () => {
  it('asks for a word of the description, and Confirmar stays off until it matches', async () => {
    const user = userEvent.setup();
    renderAction();
    await user.click(screen.getByRole('button', { name: 'Agregar a la banlist' }));
    expect(['Router', 'Archer', 'AX55']).toContain(screen.getByTestId('ban-word').textContent);
    expect(screen.getByRole('button', { name: 'Confirmar' })).toBeDisabled();
    await user.type(screen.getByLabelText('Palabra de verificación'), 'otra');
    expect(screen.getByRole('button', { name: 'Confirmar' })).toBeDisabled();
  });

  it('a short description asks for the product id instead', async () => {
    const user = userEvent.setup();
    renderAction('AX 55');
    await user.click(screen.getByRole('button', { name: 'Agregar a la banlist' }));
    expect(screen.getByTestId('ban-word')).toHaveTextContent('4101');
  });

  it('Cancelar sends nothing', async () => {
    const user = userEvent.setup();
    renderAction();
    await confirmWith(user);
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(productoBanlistAPI.add).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Agregar a la banlist' })).toBeInTheDocument();
  });

  it('the word matches ignoring case, and Confirmar sends the product and the reason once', async () => {
    const user = userEvent.setup();
    renderAction();
    await user.click(screen.getByRole('button', { name: 'Agregar a la banlist' }));
    const asked = screen.getByTestId('ban-word').textContent;
    await user.type(screen.getByLabelText('Palabra de verificación'), asked.toUpperCase());
    await user.type(screen.getByLabelText('Motivo (opcional)'), 'Discontinuado');
    await user.click(screen.getByRole('button', { name: 'Confirmar' }));

    expect(await screen.findByRole('status')).toHaveTextContent('Producto agregado a la banlist.');
    expect(productoBanlistAPI.add).toHaveBeenCalledTimes(1);
    expect(productoBanlistAPI.add).toHaveBeenCalledWith(4101, 'Discontinuado');
    expect(screen.queryByRole('button', { name: 'Agregar a la banlist' })).not.toBeInTheDocument();
  });

  it('without a reason it sends the same default as Productos', async () => {
    const user = userEvent.setup();
    renderAction();
    await confirmWith(user);
    await user.click(screen.getByRole('button', { name: 'Confirmar' }));
    await screen.findByRole('status');
    expect(productoBanlistAPI.add).toHaveBeenCalledWith(4101, 'Sin motivo especificado');
  });
});

describe('what the server answered', () => {
  it('a product already banned says so', async () => {
    productoBanlistAPI.add.mockResolvedValue(answer({ agregados: [], duplicados: ['Item ID 4101'], total_agregados: 0 }));
    const user = userEvent.setup();
    renderAction();
    await confirmWith(user);
    await user.click(screen.getByRole('button', { name: 'Confirmar' }));
    expect(await screen.findByRole('status')).toHaveTextContent('El producto ya estaba en la banlist.');
  });

  it('a product the ERP does not have is an error and nothing is claimed', async () => {
    productoBanlistAPI.add.mockResolvedValue(
      answer({ agregados: [], no_encontrados: ['Item ID 4101 no encontrado en ERP'], total_agregados: 0 }),
    );
    const user = userEvent.setup();
    renderAction();
    await confirmWith(user);
    await user.click(screen.getByRole('button', { name: 'Confirmar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Item ID 4101 no encontrado en ERP');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('a 403 names the permission and keeps the confirmation open', async () => {
    productoBanlistAPI.add.mockRejectedValue(httpError(403, 'No tenés permiso para agregar productos a la banlist'));
    const user = userEvent.setup();
    renderAction();
    await confirmWith(user);
    await user.click(screen.getByRole('button', { name: 'Confirmar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No tenés permiso para agregar productos a la banlist.');
    expect(screen.getByRole('button', { name: 'Confirmar' })).toBeEnabled();
  });

  it("another failure shows the server's reason", async () => {
    productoBanlistAPI.add.mockRejectedValue(httpError(500, 'Error interno'));
    const user = userEvent.setup();
    renderAction();
    await confirmWith(user);
    await user.click(screen.getByRole('button', { name: 'Confirmar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Error interno');
  });

  it('a failure with no reason asks to try again', async () => {
    productoBanlistAPI.add.mockRejectedValue(new Error('Network Error'));
    const user = userEvent.setup();
    renderAction();
    await confirmWith(user);
    await user.click(screen.getByRole('button', { name: 'Confirmar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo agregar a la banlist. Probá de nuevo.');
  });
});
