import { fetchCsvText, METRICAS_EXPORT_URL } from './ventasMlExport';

/*
 * "Exportar a Sheets": the CSV export of a screen, written to a NEW Google Sheet in the operator's own Drive.
 * Browser-only OAuth (Google Identity Services token client) with the `drive.file` scope, which only reaches the
 * files this app creates. The token lives in memory only, never in storage.
 *   GIS:    https://developers.google.com/identity/oauth2/web/reference/js-reference
 *   Sheets: https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/create
 *           https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate
 *           https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/request
 *           https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/other#ExtendedValue
 *           https://developers.google.com/workspace/sheets/api/reference/rest/v4/DateTimeRenderOption
 */

const GIS_SRC = 'https://accounts.google.com/gsi/client';
const SCOPE = 'https://www.googleapis.com/auth/drive.file';
const SHEETS_API = 'https://sheets.googleapis.com/v4/spreadsheets';
const SHEETS_ERROR = 'No se pudo crear la hoja de Google.';
const GOOGLE_ERROR = 'No se pudo conectar con Google. Intente de nuevo.';
const POPUP_BLOCKED = 'El navegador bloqueó la ventana de Google. Permita las ventanas emergentes e intente de nuevo.';
// A token this close to expiring is asked for again: it could expire mid-export.
const TOKEN_MARGIN_MS = 60_000;

export const isSheetsExportEnabled = () => Boolean(import.meta.env.VITE_GOOGLE_CLIENT_ID);

let gisLoading = null;
let token = null; // { value, expiresAt }

/** Loads the Google Identity Services script once. The pages call it on mount, so the click finds it ready. */
export function loadGoogleIdentity() {
  if (window.google?.accounts?.oauth2) return Promise.resolve(true);
  if (!gisLoading) {
    gisLoading = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = GIS_SRC;
      script.async = true;
      script.onload = () => resolve(true);
      script.onerror = () => {
        gisLoading = null;
        script.remove();
        reject(new Error(GOOGLE_ERROR));
      };
      document.head.appendChild(script);
    });
  }
  return gisLoading;
}

const cancelled = () => Object.assign(new Error('Exportación cancelada'), { cancelled: true });

function requestToken() {
  return new Promise((resolve, reject) => {
    const client = window.google.accounts.oauth2.initTokenClient({
      client_id: import.meta.env.VITE_GOOGLE_CLIENT_ID,
      scope: SCOPE,
      callback: (response) => {
        if (response.error) {
          reject(response.error === 'access_denied' ? cancelled() : new Error(GOOGLE_ERROR));
          return;
        }
        token = { value: response.access_token, expiresAt: Date.now() + Number(response.expires_in) * 1000 };
        resolve(token.value);
      },
      error_callback: (error) => {
        if (error?.type === 'popup_closed') reject(cancelled());
        else reject(new Error(error?.type === 'popup_failed_to_open' ? POPUP_BLOCKED : GOOGLE_ERROR));
      },
    });
    client.requestAccessToken();
  });
}

const freshToken = () => (token && token.expiresAt - TOKEN_MARGIN_MS > Date.now() ? token.value : null);

// ── The CSV ─────────────────────────────────────────────────────

const ISO_DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$/;

// The sheet does not read "2026-10-20T01:30:00+00:00" as a date: the operator's own wall clock does.
function localDateTime(cell) {
  if (!ISO_DATE_TIME.test(cell)) return cell;
  const d = new Date(cell);
  if (Number.isNaN(d.getTime())) return cell;
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function parseDelimited(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') (cell += '"'), (i += 1);
      else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ';') row.push(cell), (cell = '');
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i += 1;
      row.push(cell), rows.push(row), (row = []), (cell = '');
    } else cell += ch;
  }
  if (cell || row.length) row.push(cell), rows.push(row);
  return rows;
}

// The exports' trailing lines, written right after the last row with no blank line before:
// `# ERROR: ...` when a page failed (backend/app/routers/ml_metricas.py:923,
// backend/app/services/ml_publications/view/export.py:171) and `# AVISO: ...` (ADS_NOTE, export.py:183).
const NOTE_LINE = /^# (ERROR|AVISO): /;

/**
 * The export file as rows of cells plus its trailing `#` notes (without the mark). A `# ERROR` line means the file is
 * incomplete: it throws with that line, so a partial export never becomes a sheet.
 */
export function parseCsvExport(text) {
  const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/);
  while (lines.length && lines.at(-1) === '') lines.pop();
  const notes = [];
  while (lines.length && NOTE_LINE.test(lines.at(-1))) notes.unshift(lines.pop().slice(2));
  const error = notes.find((note) => note.startsWith('ERROR: '));
  if (error) throw new Error(error);
  const rows = parseDelimited(lines.join('\n')).map((row) => row.map(localDateTime));
  return { rows, notes };
}

// ── The sheet ───────────────────────────────────────────────────

const rgb = (red, green, blue) => ({ rgbColor: { red, green, blue } });
const HEADER_BG = rgb(0.149, 0.196, 0.247); // #26323f, a sober slate
const WHITE = rgb(1, 1, 1);
const BAND = rgb(0.953, 0.961, 0.969); // #f3f5f7
const NOTE_GRAY = rgb(0.42, 0.45, 0.5);
const MAX_WIDTH_PX = 360;
const LONG_TEXT = 50;
// Codes stay as they are: "000123" is not "123" with thousands.
const IDENTIFIER = /^(sku|c[oó]digo|mla|publicaci[oó]n)$/i;
// The CSV writes percentage POINTS ("12,50" = 12.5 %): a literal sign, never PERCENT (which multiplies by 100).
const PERCENT_POINTS = /%|markup|margen|rentabilidad/i;
const INTEGER = /^-?\d+$/;
const DECIMAL = /^-?\d+(,\d+)?$/;
const DATE = /^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}):(\d{2}):(\d{2}))?$/;
// What the export's `csv_text` puts before text that would start a formula. A stringValue is never a formula, so the
// quote would only show.
const DEFUSED_FORMULA = /^'[=+\-@\t\r]/;

function numberFormatOf(header, values) {
  if (IDENTIFIER.test(header.trim()) || !values.length) return null;
  const all = (re) => values.every((v) => re.test(v));
  if (all(DATE)) {
    return values.some((v) => v.includes(' '))
      ? { type: 'DATE_TIME', pattern: 'dd/mm/yyyy hh:mm:ss' }
      : { type: 'DATE', pattern: 'dd/mm/yyyy' };
  }
  if (!all(DECIMAL)) return null;
  if (PERCENT_POINTS.test(header)) return { type: 'NUMBER', pattern: '#,##0.00"%"' };
  return { type: 'NUMBER', pattern: all(INTEGER) ? '#,##0' : '#,##0.00' };
}

// A date (the operator's wall clock, see `localDateTime`) as a Sheets serial: days since 1899-12-30, the time as the
// fraction of the day.
function dateSerial(value) {
  const [, y, m, d, h = 0, mi = 0, sec = 0] = DATE.exec(value);
  return Date.UTC(+y, m - 1, +d, +h, +mi, +sec) / 86_400_000 + 25_569;
}

// A typed value, which Sheets stores as is: a stringValue is never read as a number, a date or a formula, so codes
// keep their leading zeros and a title like "=HYPERLINK(...)" stays text. Numbers only where the column is numeric.
function cellOf(value, numberFormat) {
  if (value === '') return {};
  if (numberFormat?.type === 'NUMBER') return { userEnteredValue: { numberValue: Number(value.replace(',', '.')) } };
  if (numberFormat) return { userEnteredValue: { numberValue: dateSerial(value) } };
  return { userEnteredValue: { stringValue: DEFUSED_FORMULA.test(value) ? value.slice(1) : value } };
}

const textRow = (text) => ({ values: [{ userEnteredValue: { stringValue: text } }] });

// Rows written per `batchUpdate` call: Google advises payloads of about 2 MB, and an export has no row cap.
const CHUNK_ROWS = 2000;

/**
 * The `batchUpdate` calls that write the export to the sheet and make it readable, to send IN ORDER, one call per
 * array: `rows` is the header plus the data, written at A1 as typed values (never pasted text, which Sheets would
 * parse) in chunks of `CHUNK_ROWS` rows, the first call also sizing the grid; the last call formats, filters and fits
 * the columns once every row is written, then adds `notes`, the file's trailing notes.
 * Pure: every request shape follows the Sheets API v4 `Request` reference.
 */
export function buildSheetRequests({ sheetId, rows, notes }) {
  const [header, ...data] = rows;
  const width = header.length;
  const span = (startRowIndex, endRowIndex, startColumnIndex = 0, endColumnIndex = width) => ({
    sheetId,
    startRowIndex,
    endRowIndex,
    startColumnIndex,
    endColumnIndex,
  });
  const columns = (startIndex, endIndex) => ({ sheetId, dimension: 'COLUMNS', startIndex, endIndex });
  const valuesOf = (c) => data.map((row) => row[c] ?? '').filter((v) => v !== '');
  const formats = header.map((name, c) => numberFormatOf(name, valuesOf(c)));
  const noteRow = rows.length + 1;
  // Typed with the formats of the WHOLE column, whatever chunk a row lands in.
  const cellsOf = (start) =>
    rows
      .slice(start, start + CHUNK_ROWS)
      .map((row, i) => ({ values: header.map((_, c) => cellOf(row[c] ?? '', start + i ? formats[c] : null)) }));
  const writes = [];
  for (let start = 0; start < rows.length; start += CHUNK_ROWS) {
    writes.push([{ updateCells: { start: { sheetId, rowIndex: start, columnIndex: 0 }, rows: cellsOf(start), fields: 'userEnteredValue' } }]);
  }
  writes[0].unshift({
    // Exactly the rows written (a new sheet's default grid may be smaller or larger than the export), the header frozen.
    updateSheetProperties: {
      properties: {
        sheetId,
        gridProperties: { rowCount: notes.length ? noteRow + notes.length : rows.length, columnCount: width, frozenRowCount: 1 },
      },
      fields: 'gridProperties(rowCount,columnCount,frozenRowCount)',
    },
  });
  const requests = [
    {
      repeatCell: {
        range: span(0, 1),
        cell: {
          userEnteredFormat: {
            backgroundColorStyle: HEADER_BG,
            horizontalAlignment: 'CENTER',
            wrapStrategy: 'WRAP',
            textFormat: { bold: true, foregroundColorStyle: WHITE },
          },
        },
        fields: 'userEnteredFormat(backgroundColorStyle,horizontalAlignment,wrapStrategy,textFormat)',
      },
    },
    { setBasicFilter: { filter: { range: span(0, rows.length) } } },
  ];
  if (data.length) {
    requests.push({
      addBanding: { bandedRange: { range: span(1, rows.length), rowProperties: { firstBandColorStyle: WHITE, secondBandColorStyle: BAND } } },
    });
  }
  formats.forEach((numberFormat, c) => {
    if (numberFormat) {
      requests.push({
        repeatCell: { range: span(1, rows.length, c, c + 1), cell: { userEnteredFormat: { numberFormat } }, fields: 'userEnteredFormat.numberFormat' },
      });
    }
  });
  requests.push({ autoResizeDimensions: { dimensions: columns(0, width) } });
  header.forEach((_, c) => {
    if (valuesOf(c).some((v) => v.length > LONG_TEXT)) {
      requests.push({ updateDimensionProperties: { range: columns(c, c + 1), properties: { pixelSize: MAX_WIDTH_PX }, fields: 'pixelSize' } });
    }
  });
  if (notes.length) {
    // Written after the fit, so a long note does not widen column A; it overflows into the empty cells instead.
    requests.push(
      { updateCells: { start: { sheetId, rowIndex: noteRow, columnIndex: 0 }, rows: notes.map(textRow), fields: 'userEnteredValue' } },
      {
        repeatCell: {
          range: span(noteRow, noteRow + notes.length, 0, 1),
          cell: { userEnteredFormat: { textFormat: { italic: true, foregroundColorStyle: NOTE_GRAY } } },
          fields: 'userEnteredFormat.textFormat',
        },
      },
    );
  }
  return [...writes, requests];
}

// ── The export ──────────────────────────────────────────────────

async function sheetsRequest(accessToken, url, body) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    if (response.status === 401) token = null;
    throw new Error(SHEETS_ERROR);
  }
  return response.json();
}

/**
 * GETs the CSV export at `url` with `params` (the CSV button's own) and writes it to a new Google Sheet titled like
 * the file, then opens it. Answers `{ url, opened }`; `opened` is false when the browser blocked the new tab.
 * Throws an Error safe to show the operator; one with `cancelled: true` when the operator closed or refused Google.
 *
 * Must be called straight from the click: with a fresh token the new tab opens before any await (popup blockers),
 * and without one the Google popup is what opens, so the tab is opened at the end.
 */
export async function exportarCsvASheets(url, params, { filename, genericError } = {}) {
  let accessToken = freshToken();
  let tab = null;
  if (accessToken) {
    tab = window.open('about:blank', '_blank');
    if (tab) tab.opener = null;
  }
  try {
    if (!accessToken) {
      if (!window.google?.accounts?.oauth2) await loadGoogleIdentity();
      accessToken = await requestToken();
    }
    const csv = await fetchCsvText(url, params, { filename, genericError });
    const { rows, notes } = parseCsvExport(csv.text);
    const created = await sheetsRequest(
      accessToken,
      `${SHEETS_API}?fields=spreadsheetId,spreadsheetUrl,sheets.properties.sheetId`,
      { properties: { title: csv.filename.replace(/\.csv$/i, ''), locale: 'es_AR' } },
    );
    const sheetId = created.sheets?.[0]?.properties?.sheetId ?? 0;
    // One call at a time, in order: the formatting and the fit come after every row is written.
    for (const requests of buildSheetRequests({ sheetId, rows, notes })) {
      await sheetsRequest(accessToken, `${SHEETS_API}/${created.spreadsheetId}:batchUpdate`, { requests });
    }

    if (tab) {
      tab.location.href = created.spreadsheetUrl;
    } else {
      tab = window.open(created.spreadsheetUrl, '_blank');
      if (tab) tab.opener = null;
    }
    return { url: created.spreadsheetUrl, opened: Boolean(tab) };
  } catch (err) {
    tab?.close();
    throw err;
  }
}

/** Métricas ML board, the same request as its "Exportar CSV". */
export const exportMetricasSheets = (params) => exportarCsvASheets(METRICAS_EXPORT_URL, params);
