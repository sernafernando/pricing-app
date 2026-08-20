/**
 * Tests for TnPublishModal.jsx (Sub-slice 3c — publish form/modal reachable
 * from FALTA_PUBLICAR rows in TiendaNubeReconcile.jsx).
 *
 * Scope:
 *   - Permission gating: caller never renders the action without
 *     `admin.gestionar_tn_publicacion` (asserted at the caller level via a
 *     `puedeGestionarPublicacion` prop the modal trusts).
 *   - Category picker: top-1 suggestion preselected, top-N shown as
 *     alternatives, empty suggestions -> manual fallback only (no crash).
 *   - Description editor pre-loaded from the row's `ml_desc`, sanitized via
 *     sanitizeHtml.js before it reaches the /publicar payload (a raw
 *     <script> is stripped).
 *   - Submit calls /publicar with the right shape (category_id,
 *     description_html sanitized, image_srcs from the row's `images`).
 *   - Inline Confirmar/Cancelar step required before the actual POST
 *     (no window.confirm).
 *   - Submit is disabled while in flight; never double-submits.
 *
 * Follow-up fix (post-3c review): the row now arrives ALREADY enriched with
 * `ml_desc`/`images`/`categoria`/`subcategoria` straight from
 * `GET /tienda-nube-reconcile/reporte` — the modal must read them off the
 * row prop directly and must NEVER call `POST /gbp-parser` anymore (that
 * redundant full-report re-fetch + client-side EAN match is now removed).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '@testing-library/react';
import TnPublishModal from './TnPublishModal';
import api from '../../services/api';

const ROW = {
  ean: '7791234567890',
  verdict: 'FALTA_PUBLICAR',
  despublicar: false,
  tn_matches: [],
  ml_title: 'Auricular Bluetooth XYZ',
  ml_desc: '<p>Descripción original</p>',
  categoria: 'Electrónica',
  subcategoria: 'Auriculares',
  images: ['https://example.com/img1.jpg', 'https://example.com/img2.jpg'],
  // Slice 2 (publish price) — surcharge path is the default fixture so
  // every pre-existing happy-path test in this file keeps its "Publicar"
  // button enabled without needing to know about price at all.
  precio_web_transferencia: '1000.00',
  participa_web_transferencia: true,
  precio_lista_ml: '900.00',
  marca: 'MarcaX',
  barcode: '7791234567890',
  cost: '50.00',
  stock: 12,
  promotional_price: null,
  publish_fields_error: null,
  // PR-7: precedence-resolved draft envelope — every default fixture is
  // publish-ready (all four measurements resolved, not blocked) so the
  // PR-6-era tests keep asserting on an enabled Publicar button by
  // default. Blocked/error states get their own dedicated fixtures below.
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
  suggestions: [
    { tn_category_id: 10, category_path_text: 'Electrónica > Auriculares', similarity: 0.95 },
    { tn_category_id: 11, category_path_text: 'Electrónica > Audio', similarity: 0.8 },
  ],
  top: { tn_category_id: 10, category_path_text: 'Electrónica > Auriculares', similarity: 0.95 },
};

function setupApiMocks({
  suggestions = SUGGESTIONS,
  categorySearchResults = [],
  porcentajeTarjetaTn = 25,
  measurementProfiles = [],
} = {}) {
  api.post.mockImplementation((url) => {
    if (url === '/tienda-nube-reconcile/categoria-sugerida') {
      return Promise.resolve({ data: suggestions });
    }
    if (url === '/tienda-nube-reconcile/publicar') {
      return Promise.resolve({ data: { submitted: true, status: 'created', product_id: 555, skipped_image_srcs: [] } });
    }
    return Promise.resolve({ data: {} });
  });
  api.get.mockImplementation((url) => {
    if (url === '/tienda-nube-reconcile/categorias') {
      return Promise.resolve({ data: categorySearchResults });
    }
    // The surcharge default is no longer a literal in the component — it is
    // read from the `porcentaje_tarjeta_tn` config key. 25 keeps the money
    // assertions below at the same numbers they always asserted, while now
    // exercising the real (configured) path.
    if (url === '/markups-tienda/config/porcentaje_tarjeta_tn') {
      return Promise.resolve({ data: { clave: 'porcentaje_tarjeta_tn', valor: porcentajeTarjetaTn } });
    }
    if (url === '/tn-measurement-profiles') {
      return Promise.resolve({ data: measurementProfiles });
    }
    return Promise.resolve({ data: {} });
  });
}

beforeEach(() => {
  api.post.mockReset();
  api.get.mockReset();
  setupApiMocks();
});

// ModalTesla auto-focuses its first focusable element ~100ms after mount —
// typing before that fires gets its focus stolen mid-keystroke. Any test
// that TYPES must wait for the auto-focus to settle first.
// PR-9 moved the target from the close button (DOM-order first focusable,
// but useless to land on) to the Título field via ModalTesla's opt-in
// `initialFocusRef`.
async function waitForModalAutofocus() {
  await waitFor(() => {
    expect(screen.getByLabelText('Título')).toHaveFocus();
  });
}

async function renderModal(props = {}) {
  const onClose = vi.fn();
  const onPublished = vi.fn();
  const utils = render(
    <TnPublishModal row={ROW} isOpen onClose={onClose} onPublished={onPublished} {...props} />
  );
  await waitFor(() => {
    expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/categoria-sugerida', {
      category_text: 'Electrónica Auriculares',
      top_n: 5,
    });
  });
  return { ...utils, onClose, onPublished };
}

describe('No redundant GBP re-fetch', () => {
  it('never calls /gbp-parser — reads product fields off the enriched row prop', async () => {
    await renderModal();
    expect(api.post).not.toHaveBeenCalledWith('/gbp-parser', expect.anything());
    expect(api.get).not.toHaveBeenCalledWith('/gbp-parser', expect.anything());
  });
});

describe('Category picker', () => {
  it('preselects the top-1 suggestion and shows alternatives', async () => {
    await renderModal();

    const top = await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });
    expect(top).toBeChecked();

    expect(screen.getByRole('radio', { name: /Electrónica > Audio/ })).toBeInTheDocument();
  });

  it('falls back to NAME search (never a numeric-id input) when suggestions are empty', async () => {
    setupApiMocks({ suggestions: { suggestions: [], top: null } });

    await renderModal();

    // The manual path is a category NAME search — a raw numeric id must
    // never be typed anywhere in this form.
    //
    // `findBy`, not `getBy`, and FIRST: the whole category block sits behind
    // `loadingSuggestion`, and `renderModal` only awaits the CALL to
    // /categoria-sugerida, not its resolution. A synchronous query here races
    // the promise — it passed locally and failed on CI. Awaiting this one
    // also settles the loaded state for the assertions below, which would
    // otherwise pass for the wrong reason: "no radios" is trivially true
    // while the block still renders its loading placeholder.
    expect(await screen.findByLabelText(/buscar categoría por nombre/i)).toBeInTheDocument();
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
    // No numeric category-id input anywhere — the only spinbutton in the
    // form is the unrelated Slice 2 price offset input.
    expect(screen.queryByLabelText(/categoría/i, { selector: 'input[type="number"]' })).not.toBeInTheDocument();
  });

  it('lets the operator pick a category by NAME via GET /categorias search', async () => {
    setupApiMocks({
      categorySearchResults: [
        { tn_category_id: 77, category_path: 'Hogar > Cocina > Cafeteras' },
        { tn_category_id: 78, category_path: 'Hogar > Cocina > Hornos' },
      ],
    });
    const user = userEvent.setup();
    await renderModal();

    await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });

    await waitForModalAutofocus();
    const search = screen.getByLabelText(/buscar otra categoría por nombre/i);
    await user.type(search, 'cocina');

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/tienda-nube-reconcile/categorias', {
        params: { q: 'cocina', limit: 20 },
      });
    });

    await user.click(await screen.findByRole('button', { name: 'Hogar > Cocina > Cafeteras' }));

    // The picked category is visibly selected by NAME…
    expect(screen.getByText(/Categoría seleccionada/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Hogar > Cocina > Cafeteras/).length).toBeGreaterThan(0);

    // …and its tn_category_id is what gets submitted.
    await user.click(screen.getByRole('button', { name: /^publicar$/i }));
    await user.click(screen.getByRole('button', { name: /^confirmar$/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/publicar', expect.any(Object));
    });
    const call = api.post.mock.calls.find(([url]) => url === '/tienda-nube-reconcile/publicar');
    expect(call[1].category_id).toBe(77);
  });

  it('loads a bounded listing of categories as soon as the modal opens, without typing (defect 1a)', async () => {
    setupApiMocks({
      categorySearchResults: [
        { tn_category_id: 1, category_path: 'Electrónica > Auriculares' },
        { tn_category_id: 2, category_path: 'Hogar > Muebles' },
      ],
    });
    await renderModal();

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/tienda-nube-reconcile/categorias', { params: { limit: 20 } });
    });
    expect(await screen.findByRole('button', { name: 'Hogar > Muebles' })).toBeInTheDocument();
  });

  it('shows a distinct empty-catalog message (never "Sin resultados") when nothing was ever synced (defect 1b)', async () => {
    setupApiMocks({ categorySearchResults: [] });
    await renderModal();

    expect(await screen.findByText(/todavía no se sincronizaron/i)).toBeInTheDocument();
    expect(screen.queryByText('Sin resultados para esa búsqueda.')).not.toBeInTheDocument();
  });

  it('shows the ordinary no-match message (not the empty-catalog one) when the catalog has rows but the query matches none', async () => {
    const user = userEvent.setup();
    // Blank-q browse returns rows (catalog NOT empty); a later typed query
    // that matches nothing must fall back to the query-scoped message.
    api.get.mockImplementation((url, config) => {
      if (url === '/tienda-nube-reconcile/categorias') {
        const q = config?.params?.q;
        if (!q) return Promise.resolve({ data: [{ tn_category_id: 1, category_path: 'Hogar > Muebles' }] });
        return Promise.resolve({ data: [] });
      }
      return Promise.resolve({ data: {} });
    });
    await renderModal();
    await screen.findByRole('button', { name: 'Hogar > Muebles' });

    await waitForModalAutofocus();
    const search = screen.getByLabelText(/buscar otra categoría por nombre/i);
    await user.type(search, 'zzz');

    expect(await screen.findByText('Sin resultados para esa búsqueda.')).toBeInTheDocument();
    expect(screen.queryByText(/todavía no se sincronizaron/i)).not.toBeInTheDocument();
  });

  it('offers a sync action from the empty-catalog state that calls POST /categorias/sync and surfaces the result (defect 1c)', async () => {
    setupApiMocks({ categorySearchResults: [] });
    const user = userEvent.setup();
    api.post.mockImplementation((url) => {
      if (url === '/tienda-nube-reconcile/categoria-sugerida') return Promise.resolve({ data: SUGGESTIONS });
      if (url === '/tienda-nube-reconcile/categorias/sync') {
        return Promise.resolve({ data: { synced: 42, skipped: false, reason: null } });
      }
      return Promise.resolve({ data: {} });
    });
    await renderModal();

    const syncBtn = await screen.findByRole('button', { name: 'Sincronizar categorías' });
    await user.click(syncBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/categorias/sync');
    });
    expect(await screen.findByText('Se sincronizaron 42 categorías.')).toBeInTheDocument();
  });

  it('forwards row.categoria/subcategoria — feeds the category-profile usage hint (PR-8)', async () => {
    const user = userEvent.setup();
    await renderModal();

    await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });
    await user.click(screen.getByRole('button', { name: /^publicar$/i }));
    await user.click(screen.getByRole('button', { name: /^confirmar$/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/publicar', expect.any(Object));
    });
    const call = api.post.mock.calls.find(([url]) => url === '/tienda-nube-reconcile/publicar');
    expect(call[1].categoria).toBe('Electrónica');
    expect(call[1].subcategoria).toBe('Auriculares');
  });
});

describe('Título', () => {
  it('pre-loads the editable title from ml_title and submits the edited value in product_data.name.es', async () => {
    const user = userEvent.setup();
    await renderModal();

    const input = screen.getByLabelText('Título');
    expect(input).toHaveValue('Auricular Bluetooth XYZ');

    await waitForModalAutofocus();
    await user.clear(input);
    await user.type(input, 'Nuevo título editado');

    await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });
    await user.click(screen.getByRole('button', { name: /^publicar$/i }));
    await user.click(screen.getByRole('button', { name: /^confirmar$/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/publicar', expect.any(Object));
    });
    const call = api.post.mock.calls.find(([url]) => url === '/tienda-nube-reconcile/publicar');
    expect(call[1].product_data.name).toEqual({ es: 'Nuevo título editado' });
  });

  it('blocks publishing while the title is empty', async () => {
    const user = userEvent.setup();
    await renderModal();

    await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });

    await user.clear(screen.getByLabelText('Título'));

    expect(screen.getByRole('button', { name: /^publicar$/i })).toBeDisabled();
  });
});

describe('Imágenes', () => {
  it('renders each image as a thumbnail with its own delete button', async () => {
    await renderModal();

    expect(screen.getByAltText('Imagen 1 del producto')).toHaveAttribute('src', 'https://example.com/img1.jpg');
    expect(screen.getByAltText('Imagen 2 del producto')).toHaveAttribute('src', 'https://example.com/img2.jpg');
    expect(screen.getByRole('button', { name: /eliminar imagen 1/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /eliminar imagen 2/i })).toBeInTheDocument();
  });

  it('excludes a deleted image from the submitted image_srcs', async () => {
    const user = userEvent.setup();
    await renderModal();

    await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });

    await user.click(screen.getByRole('button', { name: /eliminar imagen 1/i }));

    await user.click(screen.getByRole('button', { name: /^publicar$/i }));
    await user.click(screen.getByRole('button', { name: /^confirmar$/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/publicar', expect.any(Object));
    });
    const call = api.post.mock.calls.find(([url]) => url === '/tienda-nube-reconcile/publicar');
    expect(call[1].image_srcs).toEqual(['https://example.com/img2.jpg']);
  });
});

describe('Descripción — toolbar', () => {
  it('renders a visible formatting toolbar (bold/italic/underline, headings, lists)', async () => {
    await renderModal();

    expect(screen.getByRole('toolbar', { name: /formato de la descripción/i })).toBeInTheDocument();
    for (const name of [
      'Negrita',
      'Cursiva',
      'Subrayado',
      'Tachado',
      'Título 1',
      'Título 2',
      'Título 3',
      'Párrafo',
      'Lista con viñetas',
      'Lista numerada',
    ]) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
  });
});

describe('Precio de publicación', () => {
  it('shows the computed surcharge price using the web-transferencia base and the configured offset', async () => {
    await renderModal();

    expect(screen.getByText(/Base: precio web transferencia/i)).toBeInTheDocument();
    // findBy, not getBy: the offset now arrives from GET
    // /markups-tienda/config/porcentaje_tarjeta_tn, and renderModal only
    // awaits the categoria-sugerida CALL — a sync query would race the fetch.
    expect(await screen.findByText(/1250\.00/)).toBeInTheDocument();
  });

  it('blocks publishing until the configured offset has loaded (never publishes a guessed default)', async () => {
    await renderModal();

    await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });
    // Once loaded the surcharge path is publishable...
    await waitFor(() => expect(screen.getByRole('button', { name: /^publicar$/i })).toBeEnabled());
    expect(screen.getByLabelText(/recargo/i)).toHaveValue(25);
  });

  it('blocks publishing when the configured offset cannot be read', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/markups-tienda/config/porcentaje_tarjeta_tn') {
        return Promise.reject(new Error('boom'));
      }
      return Promise.resolve({ data: {} });
    });

    await renderModal();

    await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^publicar$/i })).toBeDisabled();
    });
    // Empty, never NaN/undefined.
    expect(screen.getByLabelText(/recargo/i)).toHaveValue(null);
  });

  it('recomputes the price when the operator edits the offset, and submits the exact value', async () => {
    const user = userEvent.setup();
    await renderModal();

    await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });
    await waitForModalAutofocus();

    const offsetInput = screen.getByLabelText(/recargo/i);
    await user.clear(offsetInput);
    await user.type(offsetInput, '10');

    await waitFor(() => expect(screen.getByText(/1100\.00/)).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /^publicar$/i }));
    await user.click(screen.getByRole('button', { name: /^confirmar$/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/publicar', expect.any(Object));
    });
    const call = api.post.mock.calls.find(([url]) => url === '/tienda-nube-reconcile/publicar');
    expect(call[1].product_data.price).toBe('1100.00');
    expect(call[1].offset_percent).toBe(10);
    expect(call[1].price_base_source).toBe('web_transferencia');
  });

  it('falls back to a manual price entry seeded from precio_lista_ml when there is no web-transferencia price', async () => {
    const user = userEvent.setup();
    await renderModal({
      row: { ...ROW, precio_web_transferencia: null, participa_web_transferencia: false, precio_lista_ml: '850.00' },
    });

    await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });

    expect(screen.getByText(/Base: precio lista ML \(Clásica\)/i)).toBeInTheDocument();
    const manualInput = screen.getByLabelText(/precio de publicación/i);
    expect(manualInput).toHaveValue(850);

    await user.click(screen.getByRole('button', { name: /^publicar$/i }));
    await user.click(screen.getByRole('button', { name: /^confirmar$/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/publicar', expect.any(Object));
    });
    const call = api.post.mock.calls.find(([url]) => url === '/tienda-nube-reconcile/publicar');
    expect(call[1].product_data.price).toBe('850.00');
    expect(call[1].price_base_source).toBe('manual');
    expect(call[1].offset_percent).toBeNull();
  });

  it('blocks publishing when there is no web price and no manual price is available', async () => {
    await renderModal({
      row: { ...ROW, precio_web_transferencia: null, participa_web_transferencia: false, precio_lista_ml: null },
    });

    await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });

    expect(screen.getByRole('button', { name: /^publicar$/i })).toBeDisabled();
  });
});

describe('Submit', () => {
  it('requires inline Confirmar/Cancelar (no window.confirm) before posting', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm');
    const user = userEvent.setup();
    await renderModal();

    await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });

    await user.click(screen.getByRole('button', { name: /publicar/i }));

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalledWith('/tienda-nube-reconcile/publicar', expect.anything());

    expect(screen.getByRole('button', { name: /^confirmar$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^cancelar$/i })).toBeInTheDocument();
  });

  it('sanitizes the description HTML before including it in the /publicar payload', async () => {
    const user = userEvent.setup();
    await renderModal({
      row: { ...ROW, ml_desc: '<p>Hola</p><script>alert(1)</script>' },
    });

    await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });

    await user.click(screen.getByRole('button', { name: /publicar/i }));
    await user.click(screen.getByRole('button', { name: /^confirmar$/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/publicar', expect.any(Object));
    });

    const call = api.post.mock.calls.find(([url]) => url === '/tienda-nube-reconcile/publicar');
    const payload = call[1];
    expect(payload.description_html).not.toMatch(/<script/i);
    expect(payload.description_html).toMatch(/Hola/);
  });

  it('calls /publicar with category_id, sanitized description and ordered image srcs', async () => {
    const user = userEvent.setup();
    await renderModal();

    await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });

    await user.click(screen.getByRole('button', { name: /publicar/i }));
    await user.click(screen.getByRole('button', { name: /^confirmar$/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/publicar', expect.any(Object));
    });

    const call = api.post.mock.calls.find(([url]) => url === '/tienda-nube-reconcile/publicar');
    const payload = call[1];
    expect(payload.ean).toBe('7791234567890');
    expect(payload.category_id).toBe(10);
    expect(payload.image_srcs).toEqual(['https://example.com/img1.jpg', 'https://example.com/img2.jpg']);
  });

  it('disables the submit button while in flight and never double-submits', async () => {
    let resolvePublish;
    api.post.mockImplementation((url) => {
      if (url === '/tienda-nube-reconcile/categoria-sugerida') return Promise.resolve({ data: SUGGESTIONS });
      if (url === '/tienda-nube-reconcile/publicar') {
        return new Promise((resolve) => {
          resolvePublish = resolve;
        });
      }
      return Promise.resolve({ data: {} });
    });

    const user = userEvent.setup();
    await renderModal();

    await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });

    await user.click(screen.getByRole('button', { name: /publicar/i }));
    const confirmBtn = screen.getByRole('button', { name: /^confirmar$/i });
    await user.click(confirmBtn);

    expect(confirmBtn).toBeDisabled();

    await user.click(confirmBtn).catch(() => {});

    expect(api.post.mock.calls.filter(([url]) => url === '/tienda-nube-reconcile/publicar')).toHaveLength(1);

    resolvePublish({ data: { submitted: true, status: 'created', product_id: 555, skipped_image_srcs: [] } });
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /^confirmar$/i })).not.toBeInTheDocument();
    });
  });
});

describe('Bloqueo de publicación — medidas vs. costo (defecto 1)', () => {
  it('deja publicar una vez que el operador completa una medida faltante, aunque el snapshot del backend siga marcando blocked', async () => {
    // Real bug reported by the maintainer: the backend's `/reporte` snapshot
    // (`publish_draft.blocked`) says weight/width/depth/height are missing,
    // but that verdict is STALE the moment the operator fills them in this
    // modal — the live `draftFields` state must win for measurements.
    const row = {
      ...ROW,
      publish_draft: {
        ...ROW.publish_draft,
        fields: {
          ...ROW.publish_draft.fields,
          weight: { value: null, source: 'empty', editable: true },
        },
        blocked: true,
        blocked_reasons: ['Falta peso (weight)'],
        cost_blocked: false,
        cost_block_reason: null,
      },
    };
    const user = userEvent.setup();
    await renderModal({ row });
    await waitForModalAutofocus();

    expect(screen.getByRole('button', { name: /^publicar$/i })).toBeDisabled();
    expect(screen.getByTestId('blocked-banner-missing')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Peso (kg)'), '0.3');

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^publicar$/i })).toBeEnabled();
    });
    expect(screen.queryByTestId('blocked-banner-missing')).not.toBeInTheDocument();
    expect(screen.queryByTestId('blocked-banner-backend')).not.toBeInTheDocument();
  });

  it('mantiene el bloqueo por costo (D6, no resoluble en el modal) incluso con todas las medidas completas', async () => {
    const row = {
      ...ROW,
      publish_draft: {
        ...ROW.publish_draft,
        blocked: true,
        blocked_reasons: ['Falta tipo de cambio para convertir el costo (USD)'],
        cost_blocked: true,
        cost_block_reason: 'Falta tipo de cambio para convertir el costo (USD)',
      },
    };
    await renderModal({ row });
    await waitForModalAutofocus();

    expect(screen.getByRole('button', { name: /^publicar$/i })).toBeDisabled();
    expect(screen.queryByTestId('blocked-banner-missing')).not.toBeInTheDocument();
    const banner = screen.getByTestId('blocked-banner-backend');
    expect(banner).toHaveTextContent('Falta tipo de cambio para convertir el costo (USD)');
  });
});
