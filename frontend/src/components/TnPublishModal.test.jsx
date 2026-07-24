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
import api from '../services/api';

const ROW = {
  ean: '7791234567890',
  verdict: 'FALTA_PUBLICAR',
  despublicar: false,
  tn_matches: [],
  ml_desc: '<p>Descripción original</p>',
  categoria: 'Electrónica',
  subcategoria: 'Auriculares',
  images: ['https://example.com/img1.jpg', 'https://example.com/img2.jpg'],
};

const SUGGESTIONS = {
  suggestions: [
    { tn_category_id: 10, category_path_text: 'Electrónica > Auriculares', similarity: 0.95 },
    { tn_category_id: 11, category_path_text: 'Electrónica > Audio', similarity: 0.8 },
  ],
  top: { tn_category_id: 10, category_path_text: 'Electrónica > Auriculares', similarity: 0.95 },
};

function setupApiMocks({ suggestions = SUGGESTIONS } = {}) {
  api.post.mockImplementation((url) => {
    if (url === '/tienda-nube-reconcile/categoria-sugerida') {
      return Promise.resolve({ data: suggestions });
    }
    if (url === '/tienda-nube-reconcile/publicar') {
      return Promise.resolve({ data: { submitted: true, status: 'created', product_id: 555, skipped_image_srcs: [] } });
    }
    return Promise.resolve({ data: {} });
  });
}

beforeEach(() => {
  api.post.mockReset();
  api.get.mockReset();
  setupApiMocks();
});

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

  it('falls back to manual entry with no crash when suggestions are empty', async () => {
    setupApiMocks({ suggestions: { suggestions: [], top: null } });

    await renderModal();

    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
    expect(screen.getByLabelText(/categoría TN.*manual|ID de categoría/i)).toBeInTheDocument();
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
