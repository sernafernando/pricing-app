/**
 * NOTA: vite.config.js corre la suite con `css: false`, así que los nombres de
 * clase de CSS Modules NO resuelven. Nunca asertar sobre className — asertar
 * sobre texto y roles.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { reporteMock, listarTemplatesMock, obtenerTemplateMock, generateMock } = vi.hoisted(() => ({
  reporteMock: vi.fn(),
  listarTemplatesMock: vi.fn(),
  obtenerTemplateMock: vi.fn(),
  generateMock: vi.fn(),
}));

vi.mock('../services/api', () => ({
  rrhhAPI: { reporteHorariosDocumento: reporteMock },
  documentTemplatesAPI: { listar: listarTemplatesMock, obtener: obtenerTemplateMock },
}));

vi.mock('@pdfme/generator', () => ({ generate: generateMock }));
vi.mock('../utils/pdfmePlugins', () => ({ plugins: {} }));
vi.mock('../utils/pdfmeFonts', () => ({ getFont: () => Promise.resolve({}) }));

const HorariosDocumentoModal = (await import('./HorariosDocumentoModal')).default;
const { MAX_DIAS_DOCUMENTO } = await import('./HorariosDocumentoModal');

const EMPLEADOS = [
  { id: 1, legajo: '0001', nombre: 'Juan', apellido: 'Pérez' },
  { id: 2, legajo: '0002', nombre: 'Ana', apellido: 'Gómez' },
  { id: 3, legajo: '0003', nombre: 'Luis', apellido: 'Rodríguez' },
];

const TEMPLATE_JSON = {
  basePdf: { width: 210, height: 297 },
  schemas: [
    [
      {
        name: 'tabla_dias_1',
        type: 'table',
        content: '',
        head: ['Día', 'Entrada', 'Salida', 'Hs'],
        headWidthPercentages: [34, 23, 23, 20],
      },
    ],
  ],
};

const dias = (n) =>
  Array.from({ length: n }, (_, i) => ({
    fecha_label: `${String(i + 1).padStart(2, '0')}/08`,
    dia_semana: 'Lun',
    entrada: '09:00',
    salida: '18:00',
    horas_hhmm: '09:00',
    estado: 'presente',
    sin_fichadas: false,
    incompleto: false,
  }));

const respuesta = (empleados) => ({
  data: { fecha_desde: '2026-08-01', fecha_hasta: '2026-08-31', empleados },
});

const renderModal = (props = {}) =>
  render(
    <HorariosDocumentoModal
      isOpen
      onClose={vi.fn()}
      empleados={EMPLEADOS}
      fechaDesde="2026-08-01"
      fechaHasta="2026-08-31"
      {...props}
    />
  );

beforeEach(() => {
  listarTemplatesMock.mockResolvedValue({ data: [{ id: 5, nombre: 'Registro de Horarios' }] });
  obtenerTemplateMock.mockResolvedValue({ data: { template_json: TEMPLATE_JSON } });
  generateMock.mockResolvedValue(new Uint8Array([1]));
  reporteMock.mockResolvedValue(
    respuesta([
      {
        empleado_id: 1,
        legajo: '0001',
        nombre_completo: 'Pérez, Juan',
        dias: dias(20),
        total_horas_hhmm: '176:30',
        total_dias: 20,
      },
    ])
  );
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:fake');
  globalThis.URL.revokeObjectURL = vi.fn();
  vi.spyOn(window, 'open').mockImplementation(() => null);
});

describe('HorariosDocumentoModal', () => {
  it('renderiza el rango precargado y la nómina', async () => {
    renderModal();

    expect(screen.getByText('Registro de horarios')).toBeInTheDocument();
    expect(screen.getByLabelText('Fecha desde')).toHaveValue('2026-08-01');
    expect(screen.getByLabelText('Fecha hasta')).toHaveValue('2026-08-31');
    expect(screen.getByText('0001 - Pérez, Juan')).toBeInTheDocument();
    expect(screen.getByText('0003 - Rodríguez, Luis')).toBeInTheDocument();
    await waitFor(() => expect(listarTemplatesMock).toHaveBeenCalled());
  });

  it('la checkbox de horas diarias viene tildada', () => {
    renderModal();
    expect(screen.getByLabelText('Incluir cuenta de horas diaria')).toBeChecked();
  });

  it('el filtro de texto acota la lista', async () => {
    const user = userEvent.setup();
    renderModal();

    await user.type(screen.getByLabelText('Buscar empleado'), 'gómez');

    expect(screen.getByText('0002 - Gómez, Ana')).toBeInTheDocument();
    expect(screen.queryByText('0001 - Pérez, Juan')).not.toBeInTheDocument();
  });

  it('"Todos" selecciona lo visible y después alterna a "Ninguno"', async () => {
    const user = userEvent.setup();
    renderModal();

    await user.click(screen.getByRole('button', { name: 'Todos' }));
    expect(screen.getByText('3 seleccionados')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Ninguno' }));
    expect(screen.getByText('0 seleccionados')).toBeInTheDocument();
  });

  it('"Todos" con filtro activo solo selecciona lo filtrado', async () => {
    const user = userEvent.setup();
    renderModal();

    await user.type(screen.getByLabelText('Buscar empleado'), 'pérez');
    await user.click(screen.getByRole('button', { name: 'Todos' }));

    expect(screen.getByText('1 seleccionados')).toBeInTheDocument();
  });

  it('Generar está deshabilitado sin empleados seleccionados', async () => {
    const user = userEvent.setup();
    renderModal();

    expect(screen.getByRole('button', { name: /Generar/ })).toBeDisabled();

    await user.click(screen.getByLabelText('0001 - Pérez, Juan'));
    expect(screen.getByRole('button', { name: 'Generar (1)' })).toBeEnabled();
  });

  it('pide los ids seleccionados y genera un registro por empleado', async () => {
    const user = userEvent.setup();
    reporteMock.mockResolvedValue(
      respuesta([
        { empleado_id: 1, nombre_completo: 'Pérez, Juan', dias: dias(10), total_horas_hhmm: '80:00' },
        { empleado_id: 2, nombre_completo: 'Gómez, Ana', dias: dias(10), total_horas_hhmm: '80:00' },
      ])
    );
    renderModal();

    await user.click(screen.getByLabelText('0001 - Pérez, Juan'));
    await user.click(screen.getByLabelText('0002 - Gómez, Ana'));
    await user.click(screen.getByRole('button', { name: 'Generar (2)' }));

    await waitFor(() => expect(generateMock).toHaveBeenCalled());
    expect(reporteMock).toHaveBeenCalledWith({
      fecha_desde: '2026-08-01',
      fecha_hasta: '2026-08-31',
      empleado_ids: [1, 2],
    });
    expect(generateMock.mock.calls[0][0].inputs).toHaveLength(2);
  });

  it('sin la columna de horas el template pierde la última columna', async () => {
    const user = userEvent.setup();
    renderModal();

    await user.click(screen.getByLabelText('Incluir cuenta de horas diaria'));
    await user.click(screen.getByLabelText('0001 - Pérez, Juan'));
    await user.click(screen.getByRole('button', { name: 'Generar (1)' }));

    await waitFor(() => expect(generateMock).toHaveBeenCalled());
    const { template } = generateMock.mock.calls[0][0];
    expect(template.schemas[0][0].head).toEqual(['Día', 'Entrada', 'Salida']);
  });

  it(`avisa y BLOQUEA cuando un empleado supera los ${MAX_DIAS_DOCUMENTO} días`, async () => {
    const user = userEvent.setup();
    reporteMock.mockResolvedValue(
      respuesta([
        { empleado_id: 1, nombre_completo: 'Pérez, Juan', dias: dias(10), total_horas_hhmm: '80:00' },
        { empleado_id: 2, nombre_completo: 'Gómez, Ana', dias: dias(41), total_horas_hhmm: '300:00' },
      ])
    );
    renderModal();

    await user.click(screen.getByLabelText('0001 - Pérez, Juan'));
    await user.click(screen.getByLabelText('0002 - Gómez, Ana'));
    await user.click(screen.getByRole('button', { name: 'Generar (2)' }));

    const aviso = await screen.findByRole('alert');
    expect(aviso).toHaveTextContent(`El documento entra hasta ${MAX_DIAS_DOCUMENTO} días`);
    expect(within(aviso).getByText('Gómez, Ana: 41 días')).toBeInTheDocument();
    expect(generateMock).not.toHaveBeenCalled();
  });

  it('muestra el error del backend en línea, sin alert()', async () => {
    const user = userEvent.setup();
    reporteMock.mockRejectedValue({ response: { data: { detail: 'Rango máximo: 62 días' } } });
    renderModal();

    await user.click(screen.getByLabelText('0001 - Pérez, Juan'));
    await user.click(screen.getByRole('button', { name: 'Generar (1)' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Rango máximo: 62 días');
    expect(generateMock).not.toHaveBeenCalled();
  });

  it('con más de un template exige elegir uno', async () => {
    const user = userEvent.setup();
    listarTemplatesMock.mockResolvedValue({
      data: [
        { id: 5, nombre: 'Registro de Horarios' },
        { id: 6, nombre: 'Registro de Horarios (compacto)' },
      ],
    });
    renderModal();

    const selector = await screen.findByLabelText('Template');
    await user.click(screen.getByLabelText('0001 - Pérez, Juan'));
    await user.click(screen.getByRole('button', { name: 'Generar (1)' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Elegí un template');

    await user.selectOptions(selector, '6');
    await user.click(screen.getByRole('button', { name: 'Generar (1)' }));

    await waitFor(() => expect(obtenerTemplateMock).toHaveBeenCalledWith(6));
  });

  it('con un solo template no obliga a elegir', async () => {
    const user = userEvent.setup();
    renderModal();

    await waitFor(() => expect(listarTemplatesMock).toHaveBeenCalled());
    expect(screen.queryByLabelText('Template')).not.toBeInTheDocument();

    await user.click(screen.getByLabelText('0001 - Pérez, Juan'));
    await user.click(screen.getByRole('button', { name: 'Generar (1)' }));

    await waitFor(() => expect(obtenerTemplateMock).toHaveBeenCalledWith(5));
  });

  it('cerrado no renderiza nada', () => {
    const { container } = renderModal({ isOpen: false });
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText('Registro de horarios')).not.toBeInTheDocument();
  });
});
