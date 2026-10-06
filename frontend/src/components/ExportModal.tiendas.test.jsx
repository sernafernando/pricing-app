import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ExportModal from './ExportModal';
import { serializarTiendasOficiales } from './exportTiendas';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: () => true }),
}));

beforeEach(() => {
  seedTiendasOficiales([
    { store_id: 57997, nombre: 'Primera', clave: null, orden: 0, activa: true },
    { store_id: 2645, nombre: 'Segunda vieja', clave: 'tplink', orden: 1, activa: false },
    { store_id: 471846, nombre: 'Segunda', clave: 'tplink', orden: 2, activa: true },
  ]);
});

afterAll(resetTiendasOficiales);

const openRebate = async () => {
  render(<ExportModal onClose={() => {}} filtrosActivos={{}} showToast={() => {}} />);
  await userEvent.click(await screen.findByRole('button', { name: /rebate/i }));
  return screen.getByText('Tiendas oficiales (MLAs):').closest('div');
};

describe('ExportModal official stores', () => {
  it('lists "Sin tienda" plus the active stores by their admin-defined names, all checked', async () => {
    const group = await openRebate();
    const boxes = within(group).getAllByRole('checkbox');
    expect(boxes.map((b) => b.parentElement.textContent.trim())).toEqual(['Sin tienda', 'Primera', 'Segunda']);
    expect(boxes.every((b) => b.checked)).toBe(true);
  });

  it('unticking one store reports the subset as the active filter', async () => {
    const group = await openRebate();
    await userEvent.click(within(group).getByRole('checkbox', { name: 'Segunda' }));
    await waitFor(() =>
      expect(within(group).getByText('Filtro activo en MLAs: Sin tienda, Primera')).toBeInTheDocument(),
    );
  });
});

describe('serializarTiendasOficiales', () => {
  const opciones = [
    { id: 'sin_tienda', label: 'Sin tienda' },
    { id: '57997', label: 'Primera' },
    { id: '2645,471846', label: 'Segunda' },
  ];

  it('sends every id of a grouped store (inactive ones included)', () => {
    expect(serializarTiendasOficiales(opciones, new Set(['57997']))).toBe('sin_tienda,2645,471846');
  });

  it('is null when everything or nothing is ticked', () => {
    expect(serializarTiendasOficiales(opciones, new Set())).toBeNull();
    expect(serializarTiendasOficiales(opciones, new Set(opciones.map((o) => o.id)))).toBeNull();
  });
});
