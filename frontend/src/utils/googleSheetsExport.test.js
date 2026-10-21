/**
 * ODD `exportar-a-google-sheets` G1: the CSV export, sent to a new Google Sheet in the operator's own Drive.
 * Google Identity Services (`window.google`) and the Sheets API (`fetch`) are mocked at the network boundary; the
 * CSV comes through the app's own `api` (mocked in `src/test/setup.js`). The module keeps the token in memory, so
 * every test imports a fresh copy.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const BOM = '﻿';
const CREATED = { spreadsheetId: 'sid', spreadsheetUrl: 'https://docs.google.com/spreadsheets/d/sid', sheets: [{ properties: { sheetId: 7 } }] };

let mod;
let api;
let tokenClientConfigs;
let grant;
let popup;

const csvResponse = (text, filename = 'metricas-ml-2026-10-01-2026-10-21.csv') =>
  api.get.mockResolvedValue({ data: new Blob([text]), headers: { 'content-disposition': `attachment; filename="${filename}"` } });

const sheetsCalls = () => fetch.mock.calls.map(([url, init]) => ({ url, init, body: JSON.parse(init.body) }));
const batchBodies = () => sheetsCalls().filter((c) => c.url.endsWith(':batchUpdate')).map((c) => c.body);

beforeEach(async () => {
  vi.resetModules();
  vi.stubEnv('VITE_GOOGLE_CLIENT_ID', 'client-123');
  ({ default: api } = await import('../services/api'));
  api.get.mockReset();
  mod = await import('./googleSheetsExport');

  tokenClientConfigs = [];
  // What the Google popup answers: a token by default; a test swaps it for a refusal or a closed popup.
  grant = (config) => config.callback({ access_token: 'tok-1', expires_in: 3599 });
  window.google = {
    accounts: {
      oauth2: {
        initTokenClient: vi.fn((config) => {
          tokenClientConfigs.push(config);
          return { requestAccessToken: vi.fn(() => grant(config)) };
        }),
      },
    },
  };
  globalThis.fetch = vi.fn((url) =>
    Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(url.endsWith(':batchUpdate') ? {} : CREATED) }),
  );
  popup = { location: { href: 'about:blank' }, close: vi.fn(), opener: 'x' };
  window.open = vi.fn(() => popup);
});

afterEach(() => {
  vi.unstubAllEnvs();
  delete window.google;
});

describe('isSheetsExportEnabled', () => {
  it('is on only when the Google client id is configured', () => {
    expect(mod.isSheetsExportEnabled()).toBe(true);
    vi.stubEnv('VITE_GOOGLE_CLIENT_ID', '');
    expect(mod.isSheetsExportEnabled()).toBe(false);
  });
});

describe('loadGoogleIdentity', () => {
  it('adds the Google Identity Services script once, however many times it is asked', async () => {
    delete window.google;
    const first = mod.loadGoogleIdentity();
    const second = mod.loadGoogleIdentity();
    const scripts = document.querySelectorAll('script[src="https://accounts.google.com/gsi/client"]');
    expect(scripts).toHaveLength(1);
    scripts[0].dispatchEvent(new Event('load'));
    await expect(Promise.all([first, second])).resolves.toBeDefined();
    scripts[0].remove();
  });
});

describe('parseCsvExport', () => {
  it('drops the BOM and parses quoted cells with the ";" delimiter', () => {
    const { rows, notes } = mod.parseCsvExport(`${BOM}Producto;SKU\r\n"Router; AX55";"a ""b"""\r\n`);
    expect(rows).toEqual([
      ['Producto', 'SKU'],
      ['Router; AX55', 'a "b"'],
    ]);
    expect(notes).toEqual([]);
  });

  it('moves the trailing notes out of the data, without their "# " mark', () => {
    const { rows, notes } = mod.parseCsvExport(`${BOM}A;B\n1;2\n# AVISO: el markup no descuenta la publicidad.\n`);
    expect(rows).toEqual([
      ['A', 'B'],
      ['1', '2'],
    ]);
    expect(notes).toEqual(['AVISO: el markup no descuenta la publicidad.']);
  });

  it('a last data row whose first cell starts with "#" stays a data row', () => {
    const { rows, notes } = mod.parseCsvExport(`${BOM}Producto;Stock\n#1 Router;3\n# AVISO: sin publicidad.\n`);
    expect(rows).toEqual([
      ['Producto', 'Stock'],
      ['#1 Router', '3'],
    ]);
    expect(notes).toEqual(['AVISO: sin publicidad.']);
    expect(mod.parseCsvExport(`${BOM}Producto\n# ERRORES varios\n`).rows).toEqual([['Producto'], ['# ERRORES varios']]);
  });

  it('refuses a file that says it is incomplete, with the line itself as the message', () => {
    expect(() => mod.parseCsvExport(`${BOM}A\n1\n# ERROR: exportación incompleta — 5 de 10 filas exportadas.\n`)).toThrow(
      'ERROR: exportación incompleta — 5 de 10 filas exportadas.',
    );
  });

  it('writes an ISO date-time as the operator\'s local wall clock, which the sheet reads as a date', () => {
    const { rows } = mod.parseCsvExport('Última venta;Id\n2026-10-20T01:30:00+00:00;2026-10-20\n');
    // 01:30 UTC is still the 19th in Buenos Aires (the test TZ).
    expect(rows[1]).toEqual(['2026-10-19 22:30:00', '2026-10-20']);
  });
});

// A Sheets date-time serial: days since 1899-12-30, the time as the fraction of the day (DateTimeRenderOption).
const serial = (y, m, d, h = 0, mi = 0, sec = 0) => Date.UTC(y, m - 1, d, h, mi, sec) / 86_400_000 + 25_569;

describe('buildSheetRequests', () => {
  const header = ['Producto', 'SKU', 'Unidades', 'Facturado', 'Markup %', 'Última venta', 'Variación pp'];
  const rows = [
    header,
    ['Router', '000123', '3', '1234,50', '12,50', '2026-10-19 22:30:00', '-1,25'],
    ['Switch', '000124', '', '99,00', '', '', '0,00'],
  ];
  const ofKind = (kind) => mod.buildSheetRequests({ sheetId: 7, rows, notes: [] }).filter((r) => r[kind]).map((r) => r[kind]);
  const numberFormatOf = (column) =>
    ofKind('repeatCell').find((r) => r.range.startColumnIndex === column && r.fields === 'userEnteredFormat.numberFormat')
      ?.cell.userEnteredFormat.numberFormat;

  it('makes the header bold, white on a dark background, centered and wrapped', () => {
    const head = ofKind('repeatCell').find((r) => r.range.startRowIndex === 0);
    expect(head.range).toEqual({ sheetId: 7, startRowIndex: 0, endRowIndex: 1, startColumnIndex: 0, endColumnIndex: 7 });
    expect(head.cell.userEnteredFormat).toMatchObject({
      horizontalAlignment: 'CENTER',
      wrapStrategy: 'WRAP',
      textFormat: { bold: true, foregroundColorStyle: { rgbColor: { red: 1, green: 1, blue: 1 } } },
    });
    expect(head.cell.userEnteredFormat.backgroundColorStyle.rgbColor.red).toBeLessThan(0.3);
    expect(head.fields).toBe('userEnteredFormat(backgroundColorStyle,horizontalAlignment,wrapStrategy,textFormat)');
  });

  it('first sizes the grid to the data and freezes the header row, then filters the data range', () => {
    const [first] = mod.buildSheetRequests({ sheetId: 7, rows, notes: [] });
    expect(first).toEqual({
      updateSheetProperties: {
        properties: { sheetId: 7, gridProperties: { rowCount: 3, columnCount: 7, frozenRowCount: 1 } },
        fields: 'gridProperties(rowCount,columnCount,frozenRowCount)',
      },
    });
    const [withNotes] = mod.buildSheetRequests({ sheetId: 7, rows, notes: ['a', 'b'] });
    expect(withNotes.updateSheetProperties.properties.gridProperties.rowCount).toBe(6); // a blank row, then the notes
    expect(ofKind('setBasicFilter')).toEqual([
      { filter: { range: { sheetId: 7, startRowIndex: 0, endRowIndex: 3, startColumnIndex: 0, endColumnIndex: 7 } } },
    ]);
  });

  it('bands the data rows (not the header) with two light colors', () => {
    const [banding] = ofKind('addBanding');
    expect(banding.bandedRange.range).toEqual({ sheetId: 7, startRowIndex: 1, endRowIndex: 3, startColumnIndex: 0, endColumnIndex: 7 });
    const { firstBandColorStyle, secondBandColorStyle } = banding.bandedRange.rowProperties;
    for (const style of [firstBandColorStyle, secondBandColorStyle]) {
      expect(Math.min(...Object.values(style.rgbColor))).toBeGreaterThan(0.9);
    }
    expect(firstBandColorStyle).not.toEqual(secondBandColorStyle);
  });

  it('formats each column by what its values are', () => {
    expect(numberFormatOf(0)).toBeUndefined(); // text
    expect(numberFormatOf(1)).toBeUndefined(); // a code stays as it is, never "123" with thousands
    expect(numberFormatOf(2)).toEqual({ type: 'NUMBER', pattern: '#,##0' });
    expect(numberFormatOf(3)).toEqual({ type: 'NUMBER', pattern: '#,##0.00' });
    // The CSV writes percentage POINTS ("12,50" is 12.5 %): a literal sign, never PERCENT (which multiplies by 100).
    expect(numberFormatOf(4)).toEqual({ type: 'NUMBER', pattern: '#,##0.00"%"' });
    // A date-time keeps its time on screen.
    expect(numberFormatOf(5)).toEqual({ type: 'DATE_TIME', pattern: 'dd/mm/yyyy hh:mm:ss' });
    expect(numberFormatOf(6)).toEqual({ type: 'NUMBER', pattern: '#,##0.00' });
    const facturado = ofKind('repeatCell').find((r) => r.range.startColumnIndex === 3);
    expect(facturado.range).toEqual({ sheetId: 7, startRowIndex: 1, endRowIndex: 3, startColumnIndex: 3, endColumnIndex: 4 });
  });

  it('a column of dates without time is a DATE', () => {
    const dated = mod.buildSheetRequests({ sheetId: 7, rows: [['Desde'], ['2026-10-20']], notes: [] });
    const format = dated.find((r) => r.repeatCell?.fields === 'userEnteredFormat.numberFormat').repeatCell;
    expect(format.cell.userEnteredFormat.numberFormat).toEqual({ type: 'DATE', pattern: 'dd/mm/yyyy' });
    expect(dated.find((r) => r.updateCells).updateCells.rows[1].values[0]).toEqual({ userEnteredValue: { numberValue: serial(2026, 10, 20) } });
  });

  it('a column with one non-number value gets no number format', () => {
    const mixed = mod.buildSheetRequests({ sheetId: 0, rows: [['Stock'], ['3'], ['n/d']], notes: [] });
    expect(mixed.some((r) => r.repeatCell?.fields === 'userEnteredFormat.numberFormat')).toBe(false);
  });

  it('fits every column to its content, capping the ones with long text', () => {
    const long = 'x'.repeat(80);
    const fitted = mod.buildSheetRequests({ sheetId: 7, rows: [['Título', 'Stock'], [long, '1']], notes: [] });
    const resizeAt = fitted.findIndex((r) => r.autoResizeDimensions);
    expect(fitted[resizeAt].autoResizeDimensions).toEqual({ dimensions: { sheetId: 7, dimension: 'COLUMNS', startIndex: 0, endIndex: 2 } });
    const caps = fitted.filter((r) => r.updateDimensionProperties);
    expect(caps).toEqual([
      {
        updateDimensionProperties: {
          range: { sheetId: 7, dimension: 'COLUMNS', startIndex: 0, endIndex: 1 },
          properties: { pixelSize: 360 },
          fields: 'pixelSize',
        },
      },
    ]);
    expect(fitted.indexOf(caps[0])).toBeGreaterThan(resizeAt);
  });

  it('writes the notes two rows below the data, AFTER the fit, as text in gray italics', () => {
    const withNotes = mod.buildSheetRequests({ sheetId: 7, rows, notes: ['AVISO: sin publicidad; reintente.', '=1+1'] });
    const writes = withNotes.filter((r) => r.updateCells);
    const noteAt = withNotes.indexOf(writes.at(-1));
    expect(noteAt).toBeGreaterThan(withNotes.findIndex((r) => r.autoResizeDimensions));
    expect(writes.at(-1).updateCells).toEqual({
      start: { sheetId: 7, rowIndex: 4, columnIndex: 0 },
      rows: [
        { values: [{ userEnteredValue: { stringValue: 'AVISO: sin publicidad; reintente.' } }] },
        { values: [{ userEnteredValue: { stringValue: '=1+1' } }] },
      ],
      fields: 'userEnteredValue',
    });
    const style = withNotes.at(-1).repeatCell;
    expect(style.range).toEqual({ sheetId: 7, startRowIndex: 4, endRowIndex: 6, startColumnIndex: 0, endColumnIndex: 1 });
    expect(style.cell.userEnteredFormat.textFormat).toMatchObject({ italic: true });
    expect(style.fields).toBe('userEnteredFormat.textFormat');
  });

  describe('the cells, as typed values (never parsed by Sheets)', () => {
    const cellsOf = (data) => mod.buildSheetRequests({ sheetId: 7, rows: data, notes: [] }).find((r) => r.updateCells).updateCells;

    it('writes every row from A1, right after sizing the grid', () => {
      const requests = mod.buildSheetRequests({ sheetId: 7, rows, notes: [] });
      expect(requests[1].updateCells.start).toEqual({ sheetId: 7, rowIndex: 0, columnIndex: 0 });
      expect(requests[1].updateCells.fields).toBe('userEnteredValue');
      expect(requests[1].updateCells.rows).toHaveLength(3);
      expect(requests.some((r) => r.pasteData)).toBe(false);
    });

    it('numbers of numeric columns are numberValue; codes, text and the header are stringValue', () => {
      const [head, first, second] = cellsOf(rows).rows.map((row) => row.values);
      expect(head[1]).toEqual({ userEnteredValue: { stringValue: 'SKU' } });
      expect(first).toEqual([
        { userEnteredValue: { stringValue: 'Router' } },
        { userEnteredValue: { stringValue: '000123' } }, // the leading zeros stay
        { userEnteredValue: { numberValue: 3 } },
        { userEnteredValue: { numberValue: 1234.5 } },
        { userEnteredValue: { numberValue: 12.5 } },
        { userEnteredValue: { numberValue: serial(2026, 10, 19, 22, 30) } },
        { userEnteredValue: { numberValue: -1.25 } },
      ]);
      expect(second[2]).toEqual({}); // an empty cell stays empty
    });

    it('a number in a column that is not all numbers stays the text it was', () => {
      const [, three] = cellsOf([['Stock'], ['3'], ['n/d']]).rows;
      expect(three.values[0]).toEqual({ userEnteredValue: { stringValue: '3' } });
    });

    it('text that looks like a formula is a string, never a formula', () => {
      const [, row] = cellsOf([['Título', 'Marca'], ['=HYPERLINK("http://x","y")', '@SUM(A1)']]).rows;
      expect(row.values).toEqual([
        { userEnteredValue: { stringValue: '=HYPERLINK("http://x","y")' } },
        { userEnteredValue: { stringValue: '@SUM(A1)' } },
      ]);
    });

    it('drops the quote the CSV adds to defuse a formula: a string needs none', () => {
      const [, row] = cellsOf([['Título', 'Nota'], ["'=IMPORTXML(A1)", "'hola"]]).rows;
      expect(row.values).toEqual([
        { userEnteredValue: { stringValue: '=IMPORTXML(A1)' } },
        { userEnteredValue: { stringValue: "'hola" } }, // only a defused formula loses its quote
      ]);
    });
  });

  it('a file with only the header gets no banding and no number formats', () => {
    const empty = mod.buildSheetRequests({ sheetId: 7, rows: [['A', 'B']], notes: [] });
    expect(empty.some((r) => r.addBanding)).toBe(false);
    expect(empty.some((r) => r.repeatCell?.fields === 'userEnteredFormat.numberFormat')).toBe(false);
  });
});

describe('exportarCsvASheets', () => {
  const CSV = `${BOM}Producto;Unidades\nRouter;3\n# AVISO: sin publicidad.\n`;
  const run = () => mod.exportarCsvASheets('/ml-metricas/board/export', { sort: 'gross' });

  it('asks Google for a drive.file token with the configured client id', async () => {
    csvResponse(CSV);
    await run();
    expect(tokenClientConfigs).toHaveLength(1);
    expect(tokenClientConfigs[0]).toMatchObject({ client_id: 'client-123', scope: 'https://www.googleapis.com/auth/drive.file' });
  });

  it('fetches the CSV with the same params, creates the sheet titled as the file, writes and formats it, and opens it', async () => {
    csvResponse(CSV);
    const result = await run();

    expect(api.get).toHaveBeenCalledWith('/ml-metricas/board/export', { params: { sort: 'gross' }, responseType: 'blob' });
    const [create, batch] = sheetsCalls();
    expect(create.url).toBe('https://sheets.googleapis.com/v4/spreadsheets?fields=spreadsheetId,spreadsheetUrl,sheets.properties.sheetId');
    expect(create.init).toMatchObject({ method: 'POST', headers: { Authorization: 'Bearer tok-1', 'Content-Type': 'application/json' } });
    expect(create.body).toEqual({ properties: { title: 'metricas-ml-2026-10-01-2026-10-21', locale: 'es_AR' } });
    expect(batch.url).toBe('https://sheets.googleapis.com/v4/spreadsheets/sid:batchUpdate');
    expect(batch.body).toEqual({
      requests: mod.buildSheetRequests({ sheetId: 7, rows: [['Producto', 'Unidades'], ['Router', '3']], notes: ['AVISO: sin publicidad.'] }),
    });
    expect(sheetsCalls()).toHaveLength(2);
    // No token yet: the Google popup took the click, so the sheet opens in a tab of its own at the end.
    expect(window.open).toHaveBeenCalledWith(CREATED.spreadsheetUrl, '_blank');
    expect(result).toEqual({ url: CREATED.spreadsheetUrl, opened: true });
  });

  it('reuses an unexpired token instead of asking Google again', async () => {
    csvResponse(CSV);
    await run();
    await run();
    expect(tokenClientConfigs).toHaveLength(1);
    expect(batchBodies()).toHaveLength(2);
  });

  it('asks again once the token is about to expire', async () => {
    grant = (config) => config.callback({ access_token: 'short', expires_in: 30 });
    csvResponse(CSV);
    await run();
    await run();
    expect(tokenClientConfigs).toHaveLength(2);
  });

  it('with a fresh token, opens the tab right on the click and points it at the sheet', async () => {
    csvResponse(CSV);
    await run(); // gets the token
    window.open.mockClear();
    popup.opener = 'x';
    await run();
    expect(window.open).toHaveBeenCalledTimes(1);
    expect(window.open).toHaveBeenCalledWith('about:blank', '_blank');
    expect(popup.opener).toBeNull();
    expect(popup.location.href).toBe(CREATED.spreadsheetUrl);
  });

  it('an incomplete file creates nothing and closes the tab it opened', async () => {
    csvResponse(CSV);
    await run();
    fetch.mockClear();
    csvResponse(`${BOM}Producto\nRouter\n# ERROR: exportación incompleta — 1 de 2 filas exportadas.\n`);
    await expect(run()).rejects.toThrow('ERROR: exportación incompleta — 1 de 2 filas exportadas.');
    expect(fetch).not.toHaveBeenCalled();
    expect(popup.close).toHaveBeenCalled();
  });

  it('a refused export surfaces the backend message and creates nothing', async () => {
    const body = JSON.stringify({ error: { message: 'Son más de 10000 filas.' } });
    api.get.mockRejectedValue({ response: { status: 422, data: new Blob([body]) } });
    await expect(run()).rejects.toThrow('Son más de 10000 filas.');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('closing the Google popup is a cancellation, not an error', async () => {
    grant = (config) => config.error_callback({ type: 'popup_closed' });
    csvResponse(CSV);
    const error = await run().catch((e) => e);
    expect(error.message).toBe('Exportación cancelada');
    expect(error.cancelled).toBe(true);
    expect(api.get).not.toHaveBeenCalled();
  });

  it('denying the permission is a cancellation too', async () => {
    grant = (config) => config.callback({ error: 'access_denied' });
    const error = await run().catch((e) => e);
    expect(error.cancelled).toBe(true);
  });

  it('a Sheets API failure is reported, forgets the token and closes the tab', async () => {
    csvResponse(CSV);
    await run();
    fetch.mockImplementation(() => Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) }));
    await expect(run()).rejects.toThrow('No se pudo crear la hoja de Google.');
    expect(popup.close).toHaveBeenCalled();
    await run().catch(() => {});
    expect(tokenClientConfigs).toHaveLength(2);
  });

  it('when the browser blocks the new tab, still answers with the sheet link', async () => {
    window.open = vi.fn(() => null);
    csvResponse(CSV);
    await expect(run()).resolves.toEqual({ url: CREATED.spreadsheetUrl, opened: false });
  });
});

describe('page wrappers', () => {
  beforeEach(() => {
    csvResponse('A\n1\n', 'ignored.csv');
  });

  it('exportMetricasSheets reads the Métricas ML export with the given params', async () => {
    await mod.exportMetricasSheets({ group_by: 'product' });
    expect(api.get).toHaveBeenCalledWith('/ml-metricas/board/export', { params: { group_by: 'product' }, responseType: 'blob' });
  });

  it('exportPublicacionesSheets reads the view export and titles the sheet like the CSV file', async () => {
    const { exportPublicacionesSheets, exportFilename } = await import('./publicacionesMlExport');
    await exportPublicacionesSheets('producto', { estado: 'active' });
    expect(api.get).toHaveBeenCalledWith('/ml-publications/view/products/export', { params: { estado: 'active' }, responseType: 'blob' });
    expect(sheetsCalls()[0].body.properties.title).toBe(exportFilename('producto').replace(/\.csv$/, ''));
    await expect(exportPublicacionesSheets('agrupado', {})).rejects.toThrow('Esta vista no se puede exportar.');
  });
});
