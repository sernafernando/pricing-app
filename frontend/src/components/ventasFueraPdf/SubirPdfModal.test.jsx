/**
 * SubirPdfModal (ODD `vpf-metricas-canal-fe` T3; S7 = L22, C1): pick the GBP reports, read them (POST
 * /cargas/preview, nothing stored), tick the salespeople to import (excluded ones unticked), import them (POST
 * /cargas with `vendedores`) and read the result (mockup 3).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import api from '../../services/api';
import SubirPdfModal from './SubirPdfModal';
import { CARGA, PREVIEW } from './fixtures';

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}));

const pdf = (name) => new File(['%PDF-1.4'], name, { type: 'application/pdf' });

function Location() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

function renderModal(props = {}) {
  const onClose = vi.fn();
  const onCargado = vi.fn();
  render(
    <MemoryRouter initialEntries={['/metricas-ml/cargas']}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <SubirPdfModal isOpen onClose={onClose} onCargado={onCargado} {...props} />
              <Location />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
  return { onClose, onCargado };
}

async function elegirArchivos(user, { resumen = true } = {}) {
  await user.upload(screen.getByLabelText(/Reporte de Ventas Detalladas/), pdf('reporte detallada octubre.pdf'));
  if (resumen) await user.upload(screen.getByLabelText(/Reporte de Ventas \(resumen\)/), pdf('reporte ventas octubre.pdf'));
}

async function hastaPreview(user) {
  api.post.mockResolvedValueOnce({ data: PREVIEW });
  await elegirArchivos(user);
  await user.click(screen.getByRole('button', { name: 'Leer PDF' }));
  await screen.findByRole('checkbox', { name: /Lucía Ferreyra/ });
}

async function hastaResultado(user, carga = CARGA) {
  await hastaPreview(user);
  api.post.mockResolvedValueOnce({ data: carga });
  await user.click(screen.getByRole('button', { name: /^Importar/ }));
  await screen.findByText('Resultado de la carga');
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SubirPdfModal: picking and reading the reports (preview)', () => {
  it('reads both files with POST /ventas-fuera-pdf/cargas/preview and stores nothing yet', async () => {
    const user = userEvent.setup();
    renderModal();
    await hastaPreview(user);

    expect(api.post).toHaveBeenCalledTimes(1);
    const [url, form] = api.post.mock.calls[0];
    expect(url).toBe('/ventas-fuera-pdf/cargas/preview');
    expect(form.get('detallada').name).toBe('reporte detallada octubre.pdf');
    expect(form.get('resumen').name).toBe('reporte ventas octubre.pdf');
    expect(form.has('vendedores')).toBe(false);
  });

  it('does not read until the detailed or the summary report is chosen', async () => {
    renderModal();
    expect(screen.getByRole('button', { name: 'Leer PDF' })).toBeDisabled();
  });

  it('lists each salesperson with documents and amount; excluded ones come unticked with a quiet tag', async () => {
    const user = userEvent.setup();
    renderModal();
    await hastaPreview(user);

    const lucia = screen.getByRole('checkbox', { name: /Lucía Ferreyra/ });
    const ml = screen.getByRole('checkbox', { name: /VENDEDOR ML/ });
    expect(lucia).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /Tomás Quiroga/ })).toBeChecked();
    expect(ml).not.toBeChecked();
    const filaMl = ml.closest('label');
    expect(within(filaMl).getByText('excluido')).toBeInTheDocument();
    const filaLucia = lucia.closest('label');
    expect(within(filaLucia).getByText(/98 comprobantes/)).toBeInTheDocument();
    expect(within(filaLucia).getByText('$ 84.512.330,40')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Importar 2 vendedores' })).toBeEnabled();
  });

  it('cannot import with no salesperson ticked', async () => {
    const user = userEvent.setup();
    renderModal();
    await hastaPreview(user);
    await user.click(screen.getByRole('checkbox', { name: /Lucía Ferreyra/ }));
    await user.click(screen.getByRole('checkbox', { name: /Tomás Quiroga/ }));
    expect(screen.getByRole('button', { name: /^Importar 0/ })).toBeDisabled();
  });

  it('shows the API error inline and stays on the file step (422)', async () => {
    const user = userEvent.setup();
    renderModal();
    api.post.mockRejectedValueOnce({
      response: { status: 422, data: { detail: { code: 'VALIDATION_ERROR', message: 'No es un Reporte de Ventas Detalladas de GBP' } } },
    });
    await elegirArchivos(user, { resumen: false });
    await user.click(screen.getByRole('button', { name: 'Leer PDF' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('No es un Reporte de Ventas Detalladas de GBP');
    expect(screen.getByRole('button', { name: 'Leer PDF' })).toBeInTheDocument();
  });

  it('reads the app error envelope too and explains a 413 without a body', async () => {
    const user = userEvent.setup();
    renderModal();
    api.post.mockRejectedValueOnce({ response: { status: 422, data: { error: { code: 'X', message: 'Faltan columnas' } } } });
    await elegirArchivos(user, { resumen: false });
    await user.click(screen.getByRole('button', { name: 'Leer PDF' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Faltan columnas');

    api.post.mockRejectedValueOnce({ response: { status: 413, data: '<html>413</html>' } });
    await user.click(screen.getByRole('button', { name: 'Leer PDF' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('supera los 20 MB'));
  });
});

describe('SubirPdfModal: importing the chosen salespeople', () => {
  it('posts the files and the ticked names as `vendedores` to POST /ventas-fuera-pdf/cargas', async () => {
    const user = userEvent.setup();
    const { onCargado } = renderModal();
    await hastaPreview(user);
    await user.click(screen.getByRole('checkbox', { name: /Tomás Quiroga/ }));
    await user.click(screen.getByRole('checkbox', { name: /VENDEDOR ML/ }));
    api.post.mockResolvedValueOnce({ data: CARGA });
    await user.click(screen.getByRole('button', { name: 'Importar 2 vendedores' }));
    await screen.findByText('Resultado de la carga');

    const [url, form] = api.post.mock.calls[1];
    expect(url).toBe('/ventas-fuera-pdf/cargas');
    expect(JSON.parse(form.get('vendedores'))).toEqual(['Lucía Ferreyra', 'VENDEDOR ML']);
    expect(form.get('detallada').name).toBe('reporte detallada octubre.pdf');
    expect(form.get('resumen').name).toBe('reporte ventas octubre.pdf');
    expect(onCargado).toHaveBeenCalledWith(CARGA);
  });

  it('shows the import error inline and keeps the selection', async () => {
    const user = userEvent.setup();
    const { onCargado } = renderModal();
    await hastaPreview(user);
    api.post.mockRejectedValueOnce({
      response: { status: 422, data: { detail: { code: 'VALIDATION_ERROR', message: 'Juan Nadie no está en el PDF' } } },
    });
    await user.click(screen.getByRole('button', { name: 'Importar 2 vendedores' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Juan Nadie no está en el PDF');
    expect(screen.getByRole('checkbox', { name: /Lucía Ferreyra/ })).toBeChecked();
    expect(onCargado).not.toHaveBeenCalled();
  });
});

describe('SubirPdfModal: backend deviations (T1 notes)', () => {
  it('sends the preview names exactly as returned (GBP cuts them to 12 chars; no trim or normalization)', async () => {
    const user = userEvent.setup();
    renderModal();
    api.post.mockResolvedValueOnce({
      data: {
        ...PREVIEW,
        vendedores: [
          { vendedor: 'MARIA JOSE G', documentos: 3, total_lineas: 1000, excluido: false },
          { vendedor: 'Lucía  Ferre ', documentos: 2, total_lineas: 500, excluido: false },
        ],
      },
    });
    await elegirArchivos(user);
    await user.click(screen.getByRole('button', { name: 'Leer PDF' }));
    await screen.findByRole('checkbox', { name: /MARIA JOSE G/ });
    api.post.mockResolvedValueOnce({ data: CARGA });
    await user.click(screen.getByRole('button', { name: 'Importar 2 vendedores' }));
    await screen.findByText('Resultado de la carga');
    expect(JSON.parse(api.post.mock.calls[1][1].get('vendedores'))).toEqual(['MARIA JOSE G', 'Lucía  Ferre ']);
  });

  it('formats the old Decimal-string amounts (total_lineas, recargo_financiero) like numbers', async () => {
    const user = userEvent.setup();
    renderModal();
    await hastaResultado(user, { ...CARGA, total_lineas: '161236.45', recargo_financiero: '500947.07' });
    expect(screen.getByText('Total de líneas (sin IVA)').nextElementSibling).toHaveTextContent('$ 161.236,45');
  });

  it('labels the no-product amount as without VAT (it is the PDF price)', async () => {
    const user = userEvent.setup();
    renderModal();
    await hastaResultado(user);
    expect(screen.getByText(/9 líneas sin producto/).closest('h3')).toHaveTextContent('9 líneas sin producto · $ 5.120.340,20 sin IVA');
  });
});

describe('SubirPdfModal: result (mockup 3)', () => {
  it('shows company, salespeople, range, documents by type, lines and units, and the total', async () => {
    const user = userEvent.setup();
    renderModal();
    await hastaResultado(user);

    const dato = (label) => screen.getByText(label).nextElementSibling;
    expect(dato('Empresa')).toHaveTextContent('EMPRESA NORTE SRL');
    expect(dato('Vendedor')).toHaveTextContent('Lucía Ferreyra, Tomás Quiroga');
    expect(dato('Rango del PDF')).toHaveTextContent('01/10/2026 – 31/10/2026');
    expect(dato('Comprobantes')).toHaveTextContent('139 · 90 Fc A · 44 Fc B · 4 Nc A · 1 Nd A');
    expect(dato('Líneas cargadas')).toHaveTextContent('212 · 1.187 unidades');
    expect(dato('Total de líneas (sin IVA)')).toHaveTextContent('$ 114.632.785,50');
  });

  it('says what it replaced, the lines without product and every warning', async () => {
    const user = userEvent.setup();
    renderModal();
    await hastaResultado(user);

    const reemplazo = screen.getByText('Reemplazado').closest('section');
    expect(reemplazo).toHaveTextContent('Se borraron 120 comprobantes');
    expect(reemplazo).toHaveTextContent('entre 01/10 y 31/10 (carga del 09/11 09:42)');
    expect(reemplazo).toHaveTextContent('quedaron los 139 de este PDF');

    const sinProducto = screen.getByText(/9 líneas sin producto/).closest('section');
    expect(sinProducto).toHaveTextContent('$ 5.120.340,20');
    expect(within(sinProducto).getByText('PC ARMADA OFICINA (Manual)')).toBeInTheDocument();
    expect(sinProducto).toHaveTextContent('3 líneas');
    expect(sinProducto).toHaveTextContent('7790000000017 no está en el catálogo');
    expect(within(sinProducto).getByText('-$ 120.000,00')).toBeInTheDocument();

    expect(screen.getByText(CARGA.avisos[0])).toBeInTheDocument();
  });

  it('C5: counts the new documents and the ones no longer in GBP under the replace sentence', async () => {
    const user = userEvent.setup();
    renderModal();
    await hastaResultado(user);
    const reemplazo = screen.getByText('Reemplazado').closest('section');
    expect(reemplazo).toHaveTextContent('21 nuevos · 2 que ya no están en GBP (anulados)');
  });

  it('C5: omits the zero parts, and the line when both are zero', async () => {
    const user = userEvent.setup();
    renderModal();
    await hastaResultado(user, { ...CARGA, reemplazo: { ...CARGA.reemplazo, nuevos: 0, anulados: 2 } });
    let reemplazo = screen.getByText('Reemplazado').closest('section');
    expect(reemplazo).toHaveTextContent('2 que ya no están en GBP (anulados)');
    expect(reemplazo).not.toHaveTextContent('nuevos');

    await user.click(screen.getByRole('button', { name: 'Subir otro' }));
    await hastaResultado(user, { ...CARGA, reemplazo: { ...CARGA.reemplazo, nuevos: 0, anulados: 0 } });
    reemplazo = screen.getByText('Reemplazado').closest('section');
    expect(reemplazo).not.toHaveTextContent('nuevos');
    expect(reemplazo).not.toHaveTextContent('anulados');
  });

  it('cross-checks the summary and lists the cheque documents on demand', async () => {
    const user = userEvent.setup();
    renderModal();
    await hastaResultado(user);

    const control = screen.getByText('Control con el resumen').closest('section');
    expect(control).toHaveTextContent('Los 139 comprobantes coinciden en los dos PDF.');
    expect(control).toHaveTextContent('Los totales no dan igual.');
    expect(control).toHaveTextContent('Resumen $ 114.945.236,25 · líneas $ 114.632.785,50 · diferencia $ 312.450,75');
    expect(control).toHaveTextContent('3 facturas con cheque (DISTRIBUIDORA ALFA SA ×2, COMERCIAL BETA SRL)');
    expect(within(control).queryByText('Fc A 00008-00018011')).not.toBeInTheDocument();

    await user.click(within(control).getByRole('button', { name: 'Ver comprobantes' }));
    expect(within(control).getByText('Fc A 00008-00018011')).toBeInTheDocument();
    expect(within(control).getByText('$ 150.200,50')).toBeInTheDocument();
  });

  it('says which report is still missing (L8/L11) and for which part', async () => {
    const user = userEvent.setup();
    renderModal();
    await hastaResultado(user, {
      ...CARGA,
      falta_resumen: true,
      faltantes: [{ reporte: 'resumen', vendedor: 'Tomás Quiroga', desde: '2026-10-01', hasta: '2026-10-15' }],
      control: { ...CARGA.control, resumen: false, documentos_coinciden: null, total_resumen: null, diferencia: null, cheques: [] },
    });

    const control = screen.getByText('Control con el resumen').closest('section');
    expect(control).toHaveTextContent('Falta subir el resumen');
    expect(control).toHaveTextContent('Tomás Quiroga, del 01/10 al 15/10/2026');
  });

  it('footer: who uploaded and when, upload another, and open the metrics of the salesperson', async () => {
    const user = userEvent.setup();
    const { onClose } = renderModal();
    await hastaResultado(user, { ...CARGA, vendedores: ['Lucía Ferreyra'] });

    expect(screen.getByText('Subido por Ramiro · 16/11/2026 12:10')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Ver métricas de Lucía' }));

    const url = new URL(screen.getByTestId('location').textContent, 'http://x');
    expect(url.pathname).toBe('/metricas-ml');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      canal: 'fuera',
      vendedores: 'Lucía Ferreyra',
      empresas: 'EMPRESA NORTE SRL',
      periodo: 'custom',
      desde: '2026-10-01',
      hasta: '2026-10-31',
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('"Subir otro" goes back to an empty file step', async () => {
    const user = userEvent.setup();
    renderModal();
    await hastaResultado(user);
    await user.click(screen.getByRole('button', { name: 'Subir otro' }));
    expect(screen.getByRole('button', { name: 'Leer PDF' })).toBeDisabled();
    expect(screen.queryByText('Resultado de la carga')).not.toBeInTheDocument();
  });
});

describe('SubirPdfModal: closing', () => {
  it('closes only with its X or Cancelar, never by clicking outside or Escape', async () => {
    const user = userEvent.setup();
    const { onClose } = renderModal();
    await user.click(document.querySelector('.modal-overlay-tesla'));
    await user.keyboard('{Escape}');
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
