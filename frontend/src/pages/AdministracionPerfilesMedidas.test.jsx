/**
 * Tests for AdministracionPerfilesMedidas.jsx (PR-8) — the admin screen
 * for `tn_measurement_profile` CRUD. Covers: list rendering ("Se usa en"
 * pill vs "Sin uso"), the empty state, create-form measurement validation
 * (>0), and the two distinct delete-confirmation states (in-use vs
 * not-in-use).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdministracionPerfilesMedidas from './AdministracionPerfilesMedidas';
import api from '../services/api';

const PROFILE_UNUSED = {
  id: 1,
  name: '30x20x20',
  weight: '0.300',
  width: '30.00',
  height: '20.00',
  depth: '20.00',
  categorias_en_uso: 0,
  categorias_afectadas: [],
  total_categorias_afectadas: 0,
};

const PROFILE_USED = {
  id: 2,
  name: '50x40x20',
  weight: '0.600',
  width: '50.00',
  height: '40.00',
  depth: '20.00',
  categorias_en_uso: 2,
  categorias_afectadas: ['Hogar', 'Deco'],
  total_categorias_afectadas: 2,
};

function mockList(profiles) {
  api.get.mockImplementation((url) => {
    if (url === '/tn-measurement-profiles') return Promise.resolve({ data: profiles });
    return Promise.resolve({ data: [] });
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  api.post.mockResolvedValue({ data: {} });
  api.put.mockResolvedValue({ data: {} });
  api.delete.mockResolvedValue({ data: {} });
});

describe('lista de perfiles', () => {
  it('renders profiles with "Sin uso" and the usage pill', async () => {
    mockList([PROFILE_UNUSED, PROFILE_USED]);
    render(<AdministracionPerfilesMedidas />);

    expect(await screen.findByText('30x20x20')).toBeInTheDocument();
    expect(screen.getByText('Sin uso')).toBeInTheDocument();
    expect(screen.getByText('2 categorías')).toBeInTheDocument();
  });

  it('shows the empty state when there are no profiles', async () => {
    mockList([]);
    render(<AdministracionPerfilesMedidas />);

    expect(await screen.findByText('Todavía no hay perfiles')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /crear el primero/i })).toBeInTheDocument();
  });
});

describe('crear/editar perfil', () => {
  it('keeps submit disabled and shows an error when a measurement is <= 0', async () => {
    const user = userEvent.setup();
    mockList([]);
    render(<AdministracionPerfilesMedidas />);

    await user.click(await screen.findByRole('button', { name: /crear el primero/i }));
    await user.type(screen.getByLabelText('Nombre'), '30x20x20');
    await user.type(screen.getByLabelText('Peso'), '0');
    await user.type(screen.getByLabelText('Ancho'), '30');
    await user.type(screen.getByLabelText('Alto'), '20');
    await user.type(screen.getByLabelText('Profundidad'), '20');

    const submit = screen.getByRole('button', { name: /guardar perfil/i });
    expect(submit).toBeDisabled();

    await user.click(submit);
    expect(screen.getByText(/tiene que ser mayor a cero/i)).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('submits a valid profile via POST', async () => {
    const user = userEvent.setup();
    mockList([]);
    render(<AdministracionPerfilesMedidas />);

    await user.click(await screen.findByRole('button', { name: /crear el primero/i }));
    fireEvent.change(screen.getByLabelText('Nombre'), { target: { value: '30x20x20' } });
    fireEvent.change(screen.getByLabelText('Peso'), { target: { value: '0.3' } });
    fireEvent.change(screen.getByLabelText('Ancho'), { target: { value: '30' } });
    fireEvent.change(screen.getByLabelText('Alto'), { target: { value: '20' } });
    fireEvent.change(screen.getByLabelText('Profundidad'), { target: { value: '20' } });

    const submit = screen.getByRole('button', { name: /guardar perfil/i });
    expect(submit).not.toBeDisabled();
    await user.click(submit);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        '/tn-measurement-profiles',
        expect.objectContaining({ name: '30x20x20', weight: 0.3, width: 30, height: 20, depth: 20 })
      );
    });
  });
});

describe('confirmación de borrado', () => {
  it('shows the amber in-use warning with affected categories when categorias_en_uso > 0', async () => {
    const user = userEvent.setup();
    mockList([PROFILE_USED]);
    render(<AdministracionPerfilesMedidas />);

    await user.click(await screen.findByRole('button', { name: /^borrar$/i }));

    expect(screen.getByText(/se viene usando en/i)).toBeInTheDocument();
    expect(screen.getByText('Hogar')).toBeInTheDocument();
    expect(screen.getByText('Deco')).toBeInTheDocument();
    expect(screen.getByText(/no se toca/i)).toBeInTheDocument();
  });

  it('shows the red no-consequences state when categorias_en_uso is 0', async () => {
    const user = userEvent.setup();
    mockList([PROFILE_UNUSED]);
    render(<AdministracionPerfilesMedidas />);

    await user.click(await screen.findByRole('button', { name: /^borrar$/i }));

    expect(screen.getByText(/ninguna categoría lo está usando/i)).toBeInTheDocument();
  });

  it('confirming delete calls DELETE with the profile id', async () => {
    const user = userEvent.setup();
    mockList([PROFILE_UNUSED]);
    render(<AdministracionPerfilesMedidas />);

    await user.click(await screen.findByRole('button', { name: /^borrar$/i }));
    await user.click(screen.getByRole('button', { name: /borrar perfil/i }));

    await waitFor(() => {
      expect(api.delete).toHaveBeenCalledWith('/tn-measurement-profiles/1');
    });
  });
});
