import { describe, it, expect, vi, afterEach } from 'vitest';
import { buildMlSaleUrl, isMlPanelAvailable, openInMlPanel } from './mlSidePanel';

afterEach(() => {
  delete document.documentElement.dataset.mlPanel;
  vi.restoreAllMocks();
});

describe('buildMlSaleUrl', () => {
  it('uses the pack id when the sale belongs to a pack', () => {
    expect(buildMlSaleUrl(2000014816536209, 2000018230951686)).toBe(
      'https://vendedores.mercadolibre.com.ar/ventas/2000014816536209/detalle',
    );
  });

  it('falls back to the order id when there is no pack', () => {
    expect(buildMlSaleUrl(null, 1001)).toBe('https://vendedores.mercadolibre.com.ar/ventas/1001/detalle');
    expect(buildMlSaleUrl(undefined, 1001)).toBe('https://vendedores.mercadolibre.com.ar/ventas/1001/detalle');
  });

  it('returns null when both ids are missing', () => {
    expect(buildMlSaleUrl(null, null)).toBeNull();
    expect(buildMlSaleUrl(undefined, undefined)).toBeNull();
  });
});

describe('isMlPanelAvailable', () => {
  it('is false without the extension attribute', () => {
    expect(isMlPanelAvailable()).toBe(false);
  });

  it('is true when the extension sets data-ml-panel="1"', () => {
    document.documentElement.dataset.mlPanel = '1';
    expect(isMlPanelAvailable()).toBe(true);
  });
});

describe('openInMlPanel', () => {
  const URL_ = 'https://vendedores.mercadolibre.com.ar/ventas/1001/detalle';

  it('posts an ml-open message when the extension is present', () => {
    document.documentElement.dataset.mlPanel = '1';
    const post = vi.spyOn(window, 'postMessage').mockImplementation(() => {});
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    openInMlPanel(URL_);
    expect(post).toHaveBeenCalledWith({ type: 'ml-open', url: URL_ }, window.location.origin);
    expect(open).not.toHaveBeenCalled();
  });

  it('opens a new tab when the extension is absent', () => {
    const post = vi.spyOn(window, 'postMessage').mockImplementation(() => {});
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    openInMlPanel(URL_);
    expect(open).toHaveBeenCalledWith(URL_, '_blank', 'noopener,noreferrer');
    expect(post).not.toHaveBeenCalled();
  });

  it('does nothing for a falsy url', () => {
    const post = vi.spyOn(window, 'postMessage').mockImplementation(() => {});
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    openInMlPanel(null);
    expect(post).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
  });
});
