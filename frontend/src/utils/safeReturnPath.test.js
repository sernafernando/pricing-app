import { describe, it, expect } from 'vitest';
import { safeReturnPath } from './safeReturnPath';

describe('safeReturnPath', () => {
  it('accepts a relative app path with its query string', () => {
    expect(safeReturnPath('/mcp/autorizar?req=x')).toBe('/mcp/autorizar?req=x');
  });

  it('accepts a router location and keeps its pathname, search and hash', () => {
    expect(safeReturnPath({ pathname: '/mcp/autorizar', search: '?req=x', hash: '' })).toBe('/mcp/autorizar?req=x');
    expect(safeReturnPath({ pathname: '/ayuda', search: '', hash: '#conectar-chatgpt' })).toBe('/ayuda#conectar-chatgpt');
  });

  it.each([
    ['//evil.com'],
    ['https://evil.com'],
    ['/\\evil'],
    ['/a\\b'],
    ['javascript:alert(1)'],
    ['mcp/autorizar'],
    ['/mcp\n/autorizar'],
    ['/mcp\u0000'],
    [''],
    [undefined],
    [null],
    [42],
    [{ pathname: '//evil.com', search: '' }],
    [{ pathname: undefined }],
  ])('rejects %j', (valor) => {
    expect(safeReturnPath(valor)).toBeNull();
  });
});
