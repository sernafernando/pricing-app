/**
 * PR-7 tests — editable controls (UI1/D2), stored-override prefill
 * (UI2/D8), profile confirm flow (UI3/D11), SEO/tags seeding (D12), and
 * blocked-publication UX (UI4/D3/D13). See `TnPublishModal.test.jsx` for
 * the PR-3c/PR-6 baseline this file is additive to (tasks 7.1–7.14).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '@testing-library/react';
import TnPublishModal from './TnPublishModal';
import api from '../../services/api';
import { seedSeoTags } from './seedSeoTags';

const BASE_ROW = {
  ean: '7791234567890',
  verdict: 'FALTA_PUBLICAR',
  despublicar: false,
  tn_matches: [],
  ml_title: 'Auricular Bluetooth XYZ',
  ml_desc: '<p>Descripción <strong>original</strong> del producto</p>',
  categoria: 'Electrónica',
  subcategoria: 'Auriculares',
  images: ['https://example.com/img1.jpg'],
  precio_web_transferencia: '1000.00',
  participa_web_transferencia: true,
  precio_lista_ml: '900.00',
  marca: 'MarcaX',
  barcode: '7791234567890',
  cost: '50.00',
  stock: 12,
  promotional_price: null,
  publish_fields_error: null,
  publish_draft: {
    fields: {
      weight: { value: 1.2, source: 'gbp', editable: true },
      width: { value: 10, source: 'gbp', editable: true },
      height: { value: 5, source: 'gbp', editable: true },
      depth: { value: 15, source: 'gbp', editable: true },
      cost: { value: 50, source: 'gbp', editable: true },
    },
    blocked: false,
    blocked_reasons: [],
    suggested_profile_id: null,
    exchange_rate: null,
  },
};

const SUGGESTIONS = {
  suggestions: [{ tn_category_id: 10, category_path_text: 'Electrónica > Auriculares', similarity: 0.95 }],
  top: { tn_category_id: 10, category_path_text: 'Electrónica > Auriculares', similarity: 0.95 },
};

const PROFILES = [
  { id: 1, name: 'Perfil chico', weight: 0.5, width: 8, height: 4, depth: 8 },
  { id: 2, name: 'Perfil grande', weight: 3, width: 30, height: 20, depth: 30 },
];

function setupApiMocks({ measurementProfiles = [], porcentajeTarjetaTn = 25 } = {}) {
  api.post.mockImplementation((url) => {
    if (url === '/tienda-nube-reconcile/categoria-sugerida') return Promise.resolve({ data: SUGGESTIONS });
    if (url === '/tienda-nube-reconcile/publicar') {
      return Promise.resolve({ data: { submitted: true, status: 'created', product_id: 1, skipped_image_srcs: [] } });
    }
    return Promise.resolve({ data: {} });
  });
  api.get.mockImplementation((url) => {
    if (url === '/tn-measurement-profiles') return Promise.resolve({ data: measurementProfiles });
    if (url === '/markups-tienda/config/porcentaje_tarjeta_tn') {
      return Promise.resolve({ data: { clave: 'porcentaje_tarjeta_tn', valor: porcentajeTarjetaTn } });
    }
    return Promise.resolve({ data: {} });
  });
}

beforeEach(() => {
  api.post.mockReset();
  api.get.mockReset();
  setupApiMocks();
});

async function waitForModalAutofocus() {
  await waitFor(() => {
    expect(screen.getByRole('button', { name: /cerrar modal/i })).toHaveFocus();
  });
}

async function renderModal(row = BASE_ROW, opts = {}) {
  setupApiMocks(opts);
  const utils = render(<TnPublishModal row={row} isOpen onClose={vi.fn()} onPublished={vi.fn()} />);
  await waitFor(() => {
    expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/categoria-sugerida', expect.any(Object));
  });
  await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });
  return utils;
}

// task 7.1 — D2 audit: every transmitted field renders a visible control.
describe('D2 field-to-control audit (UI1)', () => {
  const FIELD_SET = [
    'name',
    'description',
    'categories',
    'images',
    'brand',
    'visibility',
    'free_shipping',
    'seo_title',
    'seo_description',
    'tags',
    'price',
    'promotional_price',
    'sku',
    'barcode',
    'cost',
    'weight',
    'width',
    'height',
    'depth',
    'stock',
  ];

  it.each(FIELD_SET)('renders a control for %s', async (fieldName) => {
    await renderModal();
    expect(screen.getByTestId(`tn-publish-field-${fieldName}`)).toBeInTheDocument();
  });
});

// task 7.3/7.4 — SEO length limits.
describe('SEO length limits (UI1)', () => {
  it('blocks further input past 70 chars in seo_title', async () => {
    const user = userEvent.setup();
    await renderModal();
    await waitForModalAutofocus();

    const input = screen.getByLabelText('SEO — Título');
    await user.clear(input);
    await user.type(input, 'x'.repeat(90));

    expect(input.value.length).toBe(70);
  });

  it('blocks further input past 320 chars in seo_description', async () => {
    const user = userEvent.setup();
    await renderModal();
    await waitForModalAutofocus();

    const textarea = screen.getByLabelText('SEO — Descripción');
    await user.clear(textarea);
    await user.type(textarea, 'y'.repeat(360));

    expect(textarea.value.length).toBe(320);
  });
});

// task 7.5 — D8 stored-override prefill.
describe('Stored override prefill (UI2/D8)', () => {
  it('shows the stored weight override value, editable', async () => {
    const rowWithOverride = {
      ...BASE_ROW,
      publish_draft: {
        ...BASE_ROW.publish_draft,
        fields: {
          ...BASE_ROW.publish_draft.fields,
          weight: { value: 5.5, source: 'override', editable: true },
        },
      },
    };
    await renderModal(rowWithOverride);

    const weightInput = screen.getByLabelText('Peso (kg)');
    expect(weightInput).toHaveValue(5.5);
    expect(weightInput).not.toBeDisabled();
  });
});

// task 7.6/7.7/7.8 — D11 profile preselected-but-not-applied confirm flow.
describe('Profile confirm flow (UI3/D11)', () => {
  const ROW_WITH_SUGGESTION = {
    ...BASE_ROW,
    publish_draft: { ...BASE_ROW.publish_draft, suggested_profile_id: 2 },
  };

  it('preselects the suggested profile but leaves measurements at their prior source until confirmed', async () => {
    await renderModal(ROW_WITH_SUGGESTION, { measurementProfiles: PROFILES });

    expect(await screen.findByLabelText(/perfil de medidas sugerido/i)).toHaveValue('2');
    // Prior source (gbp) values remain untouched — profile not yet applied.
    expect(screen.getByLabelText('Peso (kg)')).toHaveValue(1.2);
    expect(screen.getByLabelText('Ancho (cm)')).toHaveValue(10);
  });

  it('adopts the profile values only after the explicit Aplicar perfil confirm, and stays editable', async () => {
    const user = userEvent.setup();
    await renderModal(ROW_WITH_SUGGESTION, { measurementProfiles: PROFILES });

    await screen.findByLabelText(/perfil de medidas sugerido/i);
    await user.click(screen.getByRole('button', { name: /aplicar perfil/i }));

    expect(screen.getByLabelText('Peso (kg)')).toHaveValue(3);
    expect(screen.getByLabelText('Ancho (cm)')).toHaveValue(30);

    const weightInput = screen.getByLabelText('Peso (kg)');
    await user.clear(weightInput);
    await user.type(weightInput, '4.5');
    expect(weightInput).toHaveValue(4.5);
  });

  it('lets the operator pick a different profile or clear the selection at any time', async () => {
    const user = userEvent.setup();
    await renderModal(ROW_WITH_SUGGESTION, { measurementProfiles: PROFILES });

    const select = await screen.findByLabelText(/perfil de medidas sugerido/i);
    await user.selectOptions(select, '1');
    expect(select).toHaveValue('1');

    await user.click(screen.getByRole('button', { name: /limpiar selección/i }));
    expect(select).toHaveValue('');
  });
});

// task 7.9/7.10 — D12 SEO/tags seeding.
describe('SEO/tags seeding (D12)', () => {
  it('seedSeoTags truncates name/description and joins marca+categoria, source empty', () => {
    const longName = 'A'.repeat(100);
    const longDescription = `<p>${'B'.repeat(400)}</p>`;
    const result = seedSeoTags({
      name: longName,
      descriptionHtml: longDescription,
      marca: 'MarcaX',
      categoria: 'Electrónica',
    });
    expect(result.seoTitle).toHaveLength(70);
    expect(result.seoDescription).toHaveLength(320);
    expect(result.seoDescription).not.toMatch(/<p>|<\/p>/);
    expect(result.tags).toBe('MarcaX, Electrónica');
  });

  it('seeds seo_title/seo_description/tags into the form on draft load', async () => {
    await renderModal();

    expect(screen.getByLabelText('SEO — Título')).toHaveValue('Auricular Bluetooth XYZ');
    expect(screen.getByLabelText('SEO — Descripción')).toHaveValue('Descripción original del producto');
    expect(screen.getByLabelText('Tags')).toHaveValue('MarcaX, Electrónica');
  });

  it('never re-applies the seed over an operator edit', async () => {
    const user = userEvent.setup();
    await renderModal();
    await waitForModalAutofocus();

    const tagsInput = screen.getByLabelText('Tags');
    await user.clear(tagsInput);
    await user.type(tagsInput, 'tag-manual');

    // Any unrelated re-render (title edit) must not clobber the tags edit.
    const titleInput = screen.getByLabelText('Título');
    await user.type(titleInput, '!');

    expect(screen.getByLabelText('Tags')).toHaveValue('tag-manual');
  });
});

// task 7.11/7.12 — UI4/D3 blocked-publish when measurements unresolvable.
describe('Blocked publication — missing measurements (UI4/D3)', () => {
  it('disables publish and names the missing fields with a path to resolve', async () => {
    const rowMissingMeasurements = {
      ...BASE_ROW,
      publish_draft: {
        fields: {
          weight: { value: null, source: 'empty', editable: true },
          width: { value: null, source: 'empty', editable: true },
          height: { value: 5, source: 'gbp', editable: true },
          depth: { value: 15, source: 'gbp', editable: true },
          cost: { value: 50, source: 'gbp', editable: true },
        },
        blocked: true,
        blocked_reasons: ['weight', 'width'],
        suggested_profile_id: null,
        exchange_rate: null,
      },
    };
    await renderModal(rowMissingMeasurements);

    expect(screen.getByRole('button', { name: /^publicar$/i })).toBeDisabled();
    const banner = screen.getByTestId('blocked-banner-missing');
    expect(within(banner).getByText(/peso/i)).toBeInTheDocument();
    expect(within(banner).getByText(/ancho/i)).toBeInTheDocument();
    expect(banner.textContent).toMatch(/perfil de medidas|completá los valores/i);
  });
});

// task 7.13 — D13 schema/extraction error reads distinct from genuine absence.
describe('D13 — schema/extraction error vs. genuinely-absent measurements', () => {
  it('renders the administrator-contact copy, not the "load the measurements" copy', async () => {
    const rowWithSchemaError = {
      ...BASE_ROW,
      publish_fields_error: "Falta la clave 'Peso' en el reporte 78",
      publish_draft: {
        fields: {
          weight: { value: null, source: 'empty', editable: true },
          width: { value: null, source: 'empty', editable: true },
          height: { value: null, source: 'empty', editable: true },
          depth: { value: null, source: 'empty', editable: true },
          cost: { value: null, source: 'empty', editable: true },
        },
        blocked: true,
        blocked_reasons: [],
        suggested_profile_id: null,
        exchange_rate: null,
      },
    };
    await renderModal(rowWithSchemaError);

    const errorBanner = screen.getByTestId('blocked-banner-error');
    expect(errorBanner.textContent).toMatch(/error de esquema\/extracción/i);
    expect(errorBanner.textContent).toMatch(/contactá a un administrador/i);
    expect(errorBanner.textContent).not.toMatch(/cargar las medidas/i);
    expect(screen.queryByTestId('blocked-banner-missing')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^publicar$/i })).toBeDisabled();
  });
});

// Pre-push review finding: `overrides` must match the backend's
// `Dict[str, str]` — Pydantic v2 does NOT coerce number -> str, so a float
// here is a guaranteed 422 in production. The pre-existing backend test
// passed a hand-written `{"weight": "1.200"}` string fixture, so it stayed
// green while the frontend shipped numbers: this test asserts the shape the
// frontend ACTUALLY sends, which is the only shape that matters.
describe('Wire contract — overrides value types', () => {
  it('sends every override value as a string, never a number', async () => {
    const user = userEvent.setup();
    await renderModal();

    const weightInput = screen.getByLabelText('Peso (kg)');
    await user.clear(weightInput);
    await user.type(weightInput, '1.2');

    await user.click(screen.getByRole('button', { name: /^publicar$/i }));
    await user.click(screen.getByRole('button', { name: /^confirmar$/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/publicar', expect.any(Object));
    });
    const call = api.post.mock.calls.find(([url]) => url === '/tienda-nube-reconcile/publicar');
    const overrides = call[1].overrides;
    expect(Object.keys(overrides).length).toBeGreaterThan(0);
    Object.entries(overrides).forEach(([campo, valor]) => {
      expect(typeof valor, `overrides.${campo} must be a string`).toBe('string');
    });
    expect(overrides.weight).toBe('1.2');
  });

  it('sends visibility as the TN string enum, never a boolean', async () => {
    const user = userEvent.setup();
    await renderModal();

    // D4/PC7: TN v1 accepts visible|unlisted|hidden. `false` is not a value
    // TN understands, and a checkbox could not express `unlisted`.
    await user.selectOptions(screen.getByLabelText('Visibilidad'), 'unlisted');

    await user.click(screen.getByRole('button', { name: /^publicar$/i }));
    await user.click(screen.getByRole('button', { name: /^confirmar$/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/publicar', expect.any(Object));
    });
    const call = api.post.mock.calls.find(([url]) => url === '/tienda-nube-reconcile/publicar');
    expect(call[1].product_data.visibility).toBe('unlisted');
  });

  it('sends tags as an array of trimmed strings, never one comma string', async () => {
    const user = userEvent.setup();
    await renderModal();

    await user.click(screen.getByRole('button', { name: /^publicar$/i }));
    await user.click(screen.getByRole('button', { name: /^confirmar$/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/publicar', expect.any(Object));
    });
    const call = api.post.mock.calls.find(([url]) => url === '/tienda-nube-reconcile/publicar');
    const tags = call[1].product_data.tags;
    expect(Array.isArray(tags)).toBe(true);
    tags.forEach((t) => expect(t).toBe(t.trim()));
  });
});
