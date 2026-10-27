/**
 * NOTA: vite.config.js corre la suite con `css: false`, así que los nombres de
 * clase de CSS Modules NO resuelven. Nunca asertar sobre className — asertar
 * sobre texto y roles.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';

const { getMock, postMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
}));

vi.mock('../services/api', () => ({
  default: { get: getMock, post: postMock },
}));

let mockTienePermiso = () => false;
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (codigo) => mockTienePermiso(codigo),
  }),
}));

const ImpuestosVentaModal = (await import('./ImpuestosVentaModal')).default;

const SOBRETASA = 'tax_withholding_sirtac_sobretasa-jujuy';
const SIRTAC = 'tax_withholding_sirtac-caba';
const IMPUESTOS = [
  {
    charge_name: SOBRETASA,
    etiqueta: 'Retención IIBB por falta de alta Jujuy',
    informativo_por_defecto: false,
    informativo_hoy: true,
    versiones: [{ id: 7, informativo: true, fecha_desde: '2026-09-01', fecha_hasta: null }],
  },
  {
    charge_name: SIRTAC,
    etiqueta: 'Retención IIBB CABA (SIRTAC)',
    informativo_por_defecto: true,
    informativo_hoy: true,
    versiones: [],
  },
];

const fila = (etiqueta) => screen.getByText(etiqueta).closest('tr');

describe('ImpuestosVentaModal', () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    mockTienePermiso = () => false;
    getMock.mockResolvedValue({ data: IMPUESTOS });
  });

  it('lista cada impuesto con su tratamiento de hoy y su historial', async () => {
    render(<ImpuestosVentaModal isOpen={true} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText('Retención IIBB por falta de alta Jujuy')).toBeInTheDocument());
    expect(getMock).toHaveBeenCalledWith('/impuestos-venta');

    const sobretasa = fila('Retención IIBB por falta de alta Jujuy');
    expect(within(sobretasa).getByRole('checkbox', { name: /Descontar/ })).not.toBeChecked();
    expect(within(sobretasa).getByText('Informativo desde 01/09/2026')).toBeInTheDocument();
    expect(within(fila('Retención IIBB CABA (SIRTAC)')).getByText('Informativo (por defecto)')).toBeInTheDocument();
  });

  it('sin permiso de edición: las tildes están deshabilitadas y no hay botón de guardar', async () => {
    mockTienePermiso = (codigo) => codigo !== 'ml_ops.varios_editar';

    render(<ImpuestosVentaModal isOpen={true} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText('Retención IIBB CABA (SIRTAC)')).toBeInTheDocument());
    for (const checkbox of screen.getAllByRole('checkbox')) {
      expect(checkbox).toBeDisabled();
    }
    expect(screen.queryByRole('button', { name: /Guardar cambios/ })).not.toBeInTheDocument();
  });

  it('con permiso: guarda solo los impuestos cambiados desde la fecha elegida y avisa cuántas ventas recalcula', async () => {
    mockTienePermiso = () => true;
    postMock.mockResolvedValue({ data: { mensaje: 'Versión creada', id: 9, recalculando: 12 } });

    render(<ImpuestosVentaModal isOpen={true} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText('Retención IIBB CABA (SIRTAC)')).toBeInTheDocument());
    const guardar = screen.getByRole('button', { name: /Guardar cambios/ });
    expect(guardar).toBeDisabled();

    fireEvent.click(within(fila('Retención IIBB por falta de alta Jujuy')).getByRole('checkbox', { name: /Descontar/ }));
    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2026-10-01' } });
    fireEvent.click(guardar);

    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    expect(postMock).toHaveBeenCalledWith('/impuestos-venta', {
      charge_name: SOBRETASA,
      informativo: false,
      fecha_desde: '2026-10-01',
    });
    await waitFor(() => expect(screen.getByText('Guardado. Se recalculan 12 ventas.')).toBeInTheDocument());
    expect(getMock).toHaveBeenCalledTimes(2);
  });

  it('muestra el error del backend al guardar', async () => {
    mockTienePermiso = () => true;
    postMock.mockRejectedValue({ response: { data: { detail: 'Ya existe una versión para esa fecha' } } });

    render(<ImpuestosVentaModal isOpen={true} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText('Retención IIBB CABA (SIRTAC)')).toBeInTheDocument());
    fireEvent.click(within(fila('Retención IIBB CABA (SIRTAC)')).getByRole('checkbox', { name: /Descontar/ }));
    fireEvent.click(screen.getByRole('button', { name: /Guardar cambios/ }));

    await waitFor(() => expect(screen.getByText('Ya existe una versión para esa fecha')).toBeInTheDocument());
  });
});
