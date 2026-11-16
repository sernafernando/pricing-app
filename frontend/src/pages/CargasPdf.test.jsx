/**
 * Cargas de PDF (/metricas-ml/cargas; ODD `vpf-metricas-canal-fe` T3, mockup 4, contract C2/C4, S9): the history of
 * PDF loads with its filters, the detail of one load (file names, no download), the missing-report flags, and the
 * upload entry only for `ventas_fuera.subir_pdf`.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import api from '../services/api';
import CargasPdf from './CargasPdf';
import { ALCANCES, CARGA, HISTORIAL, PREVIEW } from '../components/ventasFueraPdf/fixtures';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}));

const { permisos } = vi.hoisted(() => ({ permisos: { actuales: new Set() } }));
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [...permisos.actuales],
    tienePermiso: (codigo) => permisos.actuales.has(codigo),
    tieneAlgunPermiso: (codigos) => codigos.some((c) => permisos.actuales.has(c)),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const TODOS = ['ventas_fuera.subir_pdf', 'ventas_fuera.ver_metricas_pdf', 'ventas_fuera.ver_dashboard'];

function routeGet(url) {
  if (url === '/ventas-fuera-pdf/cargas') return Promise.resolve({ data: HISTORIAL });
  if (url === '/ventas-fuera-pdf/alcances') return Promise.resolve({ data: ALCANCES });
  return Promise.resolve({ data: [] });
}

async function renderPage(codigos = TODOS) {
  permisos.actuales = new Set(codigos);
  render(
    <MemoryRouter initialEntries={['/metricas-ml/cargas']}>
      <CargasPdf />
    </MemoryRouter>,
  );
  await screen.findByRole('row', { name: /16\/11 12:10/ });
}

const cargasCalls = () => api.get.mock.calls.filter(([url]) => url === '/ventas-fuera-pdf/cargas');

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation(routeGet);
});

describe('Cargas de PDF: history', () => {
  it('asks GET /ventas-fuera-pdf/cargas for the last 90 days and lists every load', async () => {
    await renderPage();
    expect(cargasCalls()[0][1]).toEqual({ params: { dias: 90, page: 1, page_size: 50 } });
    expect(screen.getByText('Cargas de PDF', { selector: 'h1' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Historial de cargas · 5 cargas' })).toBeInTheDocument();
    for (const name of ['Fecha de carga', 'Empresa', 'Vendedor', 'Rango del PDF', 'Comprob.', 'Líneas', 'Total líneas', 'Reemplazó', 'Sin producto', 'Control', 'Subido por']) {
      expect(screen.getByRole('columnheader', { name })).toBeInTheDocument();
    }
    const fila = screen.getByRole('row', { name: /16\/11 12:10/ });
    const celdas = within(fila).getAllByRole('cell').map((c) => c.textContent);
    expect(celdas).toEqual([
      '16/11 12:10',
      'EMPRESA NORTE SRL',
      'Lucía Ferreyra',
      '01/10 – 31/10/2026',
      '98',
      '160',
      '$ 84.512.330,40',
      '90',
      '7',
      '2 avisos',
      'Ramiro',
    ]);
  });

  it('mutes replaced loads with a tag, pills the control state and shows "—" for unknown columns', async () => {
    await renderPage();
    const reemplazada = screen.getByRole('row', { name: /09\/11 09:42/ });
    expect(reemplazada).toHaveAttribute('data-estado', 'reemplazada');
    expect(within(reemplazada).getByText('reemplazada')).toBeInTheDocument();
    expect(within(screen.getByRole('row', { name: /05\/11 17:05/ })).getByText('OK')).toBeInTheDocument();
    expect(within(screen.getByRole('row', { name: /03\/11 11:20/ })).getByText('sin resumen')).toBeInTheDocument();
    expect(within(screen.getByRole('row', { name: /05\/11 17:05/ })).getByText(/Todos/)).toHaveTextContent('Todos (4)');

    const vieja = within(screen.getByRole('row', { name: /02\/10 08:55/ })).getAllByRole('cell').map((c) => c.textContent);
    expect(vieja.slice(5, 9)).toEqual(['—', '—', '0', '—']);
    expect(vieja.at(-1)).toBe('—');
  });

  it('filters by company, salesperson and days', async () => {
    const user = userEvent.setup();
    await renderPage();

    await user.click(screen.getByRole('button', { name: 'EMPRESA SUR SA' }));
    await waitFor(() => expect(cargasCalls().at(-1)[1].params).toMatchObject({ empresa: 'EMPRESA SUR SA', dias: 90 }));
    await user.selectOptions(screen.getByLabelText('Vendedor'), 'Tomás Quiroga');
    await waitFor(() => expect(cargasCalls().at(-1)[1].params).toMatchObject({ empresa: 'EMPRESA SUR SA', vendedor: 'Tomás Quiroga' }));
    await user.selectOptions(screen.getByLabelText('Cargas'), '30');
    await waitFor(() => expect(cargasCalls().at(-1)[1].params).toMatchObject({ dias: 30 }));
    await user.click(screen.getByRole('button', { name: 'Todas' }));
    await waitFor(() => expect(cargasCalls().at(-1)[1].params).not.toHaveProperty('empresa'));
  });

  it('says so when the history cannot be loaded', async () => {
    api.get.mockImplementation((url) =>
      url === '/ventas-fuera-pdf/cargas' ? Promise.reject(new Error('500')) : routeGet(url),
    );
    permisos.actuales = new Set(TODOS);
    render(
      <MemoryRouter>
        <CargasPdf />
      </MemoryRouter>,
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo cargar el historial');
  });
});

describe('Cargas de PDF: detail of a load', () => {
  it('shows the first load: range, documents, lines, total, file names (no download), control, replace and no-product', async () => {
    await renderPage();
    const detalle = screen.getByRole('complementary', { name: 'Detalle de la carga' });
    expect(within(detalle).getByRole('heading', { name: 'Carga del 16/11 12:10' })).toBeInTheDocument();
    expect(detalle).toHaveTextContent('EMPRESA NORTE SRL · Lucía Ferreyra');
    expect(detalle).toHaveTextContent('01/10/2026 – 31/10/2026');
    expect(detalle).toHaveTextContent('160 · 840 u');
    expect(within(detalle).getByText('lucia detallada.pdf')).toBeInTheDocument();
    expect(within(detalle).getByText('lucia ventas.pdf')).toBeInTheDocument();
    expect(within(detalle).queryByRole('link')).not.toBeInTheDocument();
    expect(within(detalle).queryByRole('button', { name: /descargar/i })).not.toBeInTheDocument();
    expect(detalle).toHaveTextContent('Totales distintos');
    expect(detalle).toHaveTextContent('Resumen $ 114.945.236,25 vs líneas $ 114.632.785,50');
    expect(detalle).toHaveTextContent('3 facturas con cheque ($ 312.450,75), guardado aparte');
    expect(detalle).toHaveTextContent('Reemplazó la carga del 09/11 09:42 (90 comprobantes del mismo vendedor y rango).');
    expect(detalle).toHaveTextContent('7 líneas sin producto · $ 4.931.300,20 sin IVA');
  });

  it('switches to the clicked load', async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByRole('row', { name: /03\/11 11:20/ }));
    const detalle = screen.getByRole('complementary', { name: 'Detalle de la carga' });
    expect(within(detalle).getByRole('heading', { name: 'Carga del 03/11 11:20' })).toBeInTheDocument();
    expect(detalle).toHaveTextContent('tomas detallada.pdf');
    expect(detalle).toHaveTextContent('Sin resumen: los totales no se controlaron.');
    expect(screen.getByRole('row', { name: /03\/11 11:20/ })).toHaveAttribute('aria-selected', 'true');
  });
});

describe('Cargas de PDF: detail additions (C5)', () => {
  it('breaks the documents down by type', async () => {
    await renderPage();
    const detalle = screen.getByRole('complementary', { name: 'Detalle de la carga' });
    expect(within(detalle).getByText('Comprobantes').nextElementSibling).toHaveTextContent('98 · 60 Fc A · 34 Fc B · 3 Nc A · 1 Nd A');
  });

  it('keeps the plain document count and the old replace text when the new columns are null', async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByRole('row', { name: /05\/11 17:05/ }));
    const detalle = screen.getByRole('complementary', { name: 'Detalle de la carga' });
    expect(within(detalle).getByText('Comprobantes').nextElementSibling).toHaveTextContent(/^180$/);
    expect(detalle).not.toHaveTextContent('Reemplazó');
  });

  it('says "Reemplazó N comprobantes…" when the replaced load date is unknown', async () => {
    api.get.mockImplementation((url) =>
      url === '/ventas-fuera-pdf/cargas'
        ? Promise.resolve({ data: [{ ...HISTORIAL[0], carga_anterior_at: null }] })
        : routeGet(url),
    );
    await renderPage();
    const detalle = screen.getByRole('complementary', { name: 'Detalle de la carga' });
    expect(detalle).toHaveTextContent('Reemplazó 90 comprobantes del mismo vendedor y rango.');
  });

  it('does not repeat the cheque explanation of the control box as an aviso, and keeps every other aviso', async () => {
    await renderPage();
    const detalle = screen.getByRole('complementary', { name: 'Detalle de la carga' });
    expect(detalle).toHaveTextContent('Totales distintos');
    expect(detalle).not.toHaveTextContent(HISTORIAL[0].avisos[0]);
    expect(detalle).toHaveTextContent(HISTORIAL[0].avisos[1]);
  });

  it('shows that same aviso when no control box explains the difference', async () => {
    api.get.mockImplementation((url) =>
      url === '/ventas-fuera-pdf/cargas'
        ? Promise.resolve({ data: [{ ...HISTORIAL[0], control_detalle: null }] })
        : routeGet(url),
    );
    await renderPage();
    const detalle = screen.getByRole('complementary', { name: 'Detalle de la carga' });
    expect(detalle).toHaveTextContent(HISTORIAL[0].avisos[0]);
    expect(detalle).toHaveTextContent(HISTORIAL[0].avisos[1]);
  });
});

describe('Cargas de PDF: missing reports (L8/L11)', () => {
  it('lists the parts no report of the other kind covers, from GET /alcances', async () => {
    await renderPage();
    const faltan = screen.getByRole('region', { name: 'Faltan reportes' });
    expect(faltan).toHaveTextContent('Falta el resumen');
    expect(faltan).toHaveTextContent('EMPRESA NORTE SRL · Tomás Quiroga · 01/10 – 31/10/2026');
    expect(within(faltan).getAllByRole('listitem')).toHaveLength(1);
  });
});

describe('Cargas de PDF: permissions (C4)', () => {
  it('without subir_pdf: no upload button and no drop zone', async () => {
    await renderPage(['ventas_fuera.ver_metricas_pdf']);
    expect(screen.queryByRole('button', { name: /Subir PDF de ventas/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Arrastrá el Reporte de Ventas Detalladas/)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Vendedores excluidos' })).not.toBeInTheDocument();
  });

  it('with subir_pdf: the button opens the upload modal and a finished load refreshes the history', async () => {
    const user = userEvent.setup();
    await renderPage();
    expect(screen.getByText(/Arrastrá el Reporte de Ventas Detalladas/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Subir PDF de ventas/ }));
    expect(screen.getByRole('heading', { name: 'Subir PDF de ventas por fuera' })).toBeInTheDocument();

    api.post.mockResolvedValueOnce({ data: PREVIEW }).mockResolvedValueOnce({ data: CARGA });
    await user.upload(screen.getByLabelText(/Reporte de Ventas Detalladas/), new File(['x'], 'a detallada.pdf'));
    await user.click(screen.getByRole('button', { name: 'Leer PDF' }));
    await user.click(await screen.findByRole('button', { name: /^Importar/ }));
    await screen.findByText('Resultado de la carga');
    await waitFor(() => expect(cargasCalls()).toHaveLength(2));
  });

  it('links the excluded-salespeople admin for whoever has its permission', async () => {
    await renderPage();
    expect(screen.getByRole('link', { name: 'Vendedores excluidos' })).toHaveAttribute(
      'href',
      '/dashboard-ventas-fuera/vendedores-excluidos',
    );
  });
});
