/**
 * PR-9 tests — two-pane shell (item a), left-pane cards (item b), image
 * delete relocation (item c), and the right summary pane (item d/e).
 * Reuses the same fixture shape as `PublisherFields.test.jsx`.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { screen, render } from '@testing-library/react';
import TnPublishModal from './TnPublishModal';
import api from '../../services/api';

const BASE_ROW = {
  ean: '7791234567890',
  verdict: 'FALTA_PUBLICAR',
  despublicar: false,
  tn_matches: [],
  ml_title: 'Auricular Bluetooth XYZ',
  ml_desc: '<p>Descripción original del producto</p>',
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

function setupApiMocks() {
  api.post.mockImplementation((url) => {
    if (url === '/tienda-nube-reconcile/categoria-sugerida') return Promise.resolve({ data: SUGGESTIONS });
    return Promise.resolve({ data: {} });
  });
  api.get.mockImplementation((url) => {
    if (url === '/tn-measurement-profiles') return Promise.resolve({ data: [] });
    if (url === '/markups-tienda/config/porcentaje_tarjeta_tn') {
      return Promise.resolve({ data: { clave: 'porcentaje_tarjeta_tn', valor: 25 } });
    }
    return Promise.resolve({ data: {} });
  });
}

beforeEach(() => {
  api.post.mockReset();
  api.get.mockReset();
  setupApiMocks();
});

async function renderModal(row = BASE_ROW) {
  const utils = render(<TnPublishModal row={row} isOpen onClose={() => {}} onPublished={() => {}} />);
  await screen.findByRole('radio', { name: /Electrónica > Auriculares/ });
  return utils;
}

describe('Two-pane shell (design item a)', () => {
  it('renders the sticky header with the EAN and the two panes', async () => {
    await renderModal();
    expect(screen.getByText('7791234567890')).toBeInTheDocument();
    expect(screen.getByTestId('tn-publish-field-name')).toBeInTheDocument();
    expect(screen.getByText('Qué se va a publicar')).toBeInTheDocument();
  });
});

describe('Left-pane cards (design item b)', () => {
  it('groups Identidad, Medidas, Precio y stock, Categoría, Imágenes and Descripción y SEO as separate cards', async () => {
    await renderModal();
    for (const cardTitle of ['Identidad', 'Medidas', 'Precio y stock', 'Categoría', 'Imágenes', 'Descripción y SEO']) {
      expect(screen.getAllByText(cardTitle).length).toBeGreaterThan(0);
    }
  });
});

describe('Right summary pane (design item d)', () => {
  it('shows the summary card, the Precio final row and the publish button', async () => {
    await renderModal();
    expect(screen.getByText('Qué se va a publicar')).toBeInTheDocument();
    expect(screen.getByText('Precio final')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^publicar$/i })).toBeInTheDocument();
    expect(screen.getByText('Vas a poder revisar antes de confirmar.')).toBeInTheDocument();
  });
});

describe('Blocked-state redesign (design item e)', () => {
  it('renders the amber block with the two resolve options when measurements are missing', async () => {
    const row = {
      ...BASE_ROW,
      publish_draft: {
        fields: {
          weight: { value: null, source: 'empty', editable: true },
          width: { value: 10, source: 'gbp', editable: true },
          height: { value: 5, source: 'gbp', editable: true },
          depth: { value: 15, source: 'gbp', editable: true },
          cost: { value: 50, source: 'gbp', editable: true },
        },
        blocked: true,
        blocked_reasons: ['weight'],
        suggested_profile_id: null,
        exchange_rate: null,
      },
    };
    await renderModal(row);
    const banner = screen.getByTestId('blocked-banner-missing');
    expect(banner.textContent).toMatch(/dos formas de resolverlo/i);
    expect(banner.textContent).toMatch(/aplicar el perfil sugerido/i);
    expect(screen.getByRole('button', { name: /ir al campo/i })).toBeInTheDocument();
  });
});
