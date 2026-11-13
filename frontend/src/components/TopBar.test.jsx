/**
 * TopBar logo swap: TP-only users see the TP-Link logo, everyone else keeps the
 * app logo. The TopBar is also where the brand is synced from the permission,
 * because it is the first component inside both ThemeProvider and
 * PermisosProvider on every authenticated page.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import axios from 'axios';
import { renderWithRouter } from '../test/renderWithRouter';
import { ThemeProvider } from '../contexts/ThemeContext';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import api from '../services/api';
import { businessToday } from '../utils/dateRangePresets';
import { toLocalDateString } from '../utils/dateUtils';
import TopBar, { TPLINK_LOGO_SRC } from './TopBar';

const permisosStub = {
  permisos: [],
  rol: null,
  tienePermiso: (permiso) => permisosStub.permisos.includes(permiso),
};
const weatherStub = { weather: null };

vi.mock('../services/api', () => ({ default: { get: vi.fn() } }));

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => permisosStub,
  PermisosProvider: ({ children }) => children,
}));
vi.mock('../hooks/useWeather', () => ({ useWeather: () => weatherStub }));
vi.mock('./NotificationBell', () => ({ default: () => null }));
vi.mock('./FreeShippingBadge', () => ({ default: () => null }));
vi.mock('./MejoresOfertasBadge', () => ({ default: () => null }));
vi.mock('./TicketBadge', () => ({ default: () => null }));
vi.mock('./BirthdayBadge', () => ({ default: () => null }));
vi.mock('./ThemeToggleSimple', () => ({ default: () => null }));

const renderTopBar = () =>
  renderWithRouter(
    <ThemeProvider>
      <TopBar />
    </ThemeProvider>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockResolvedValue({ data: { kpis: { gross: { value: 0 } } } });
  permisosStub.permisos = [];
  weatherStub.weather = null;
  document.documentElement.removeAttribute('data-brand');
});

afterEach(() => {
  document.documentElement.removeAttribute('data-brand');
});

describe('TopBar — brand logo', () => {
  it('shows the TP-Link logo for tplink.solo users and brands the document', () => {
    permisosStub.permisos = ['tplink.solo'];
    renderTopBar();
    const logo = screen.getByRole('img', { name: 'TP-Link' });
    expect(logo.getAttribute('src')).toBe('/brand/tplink-logo-white.png');
    expect(document.documentElement.getAttribute('data-brand')).toBe('tplink');
  });

  it('shows the TP-Link logo for tplink.tema users too', () => {
    permisosStub.permisos = ['tplink.tema'];
    renderTopBar();
    expect(screen.getByRole('img', { name: 'TP-Link' })).toBeTruthy();
  });

  it('keeps the app logo for everyone else', () => {
    permisosStub.permisos = ['ml_metricas.ver'];
    renderTopBar();
    expect(screen.queryByRole('img', { name: 'TP-Link' })).toBeNull();
    const logo = screen.getByRole('img', { name: 'Logo' });
    expect(logo.getAttribute('src')).not.toContain('tplink');
    expect(document.documentElement.hasAttribute('data-brand')).toBe(false);
  });

  it('points the TP-Link logo at an asset that exists in public/', () => {
    const publicDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../public');
    expect(TPLINK_LOGO_SRC).toMatch(/^\//);
    expect(fs.existsSync(path.join(publicDir, TPLINK_LOGO_SRC))).toBe(true);
  });
});

const WEATHER = {
  city: 'Buenos Aires',
  description: 'Despejado',
  icon_url: '/clima.png',
  temp: 22,
  humidity: 40,
  wind_speed: 10,
  rain_probability: 0,
};

describe('TopBar — Facturado hoy', () => {
  it('reads today from the new Métricas ML board and links to it', async () => {
    permisosStub.permisos = ['ml_metricas.ver'];
    api.get.mockResolvedValue({ data: { kpis: { gross: { value: 1234567.4 } } } });
    renderTopBar();
    const chip = await screen.findByRole('link', { name: /Facturado ML Hoy/ });
    expect(chip).toHaveTextContent('$1.234.567');
    expect(chip.getAttribute('href')).toBe('/metricas-ml');
    const today = toLocalDateString(businessToday());
    expect(today).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(api.get).toHaveBeenCalledTimes(1);
    const [url, config] = api.get.mock.calls[0];
    expect(url).toBe('/ml-metricas/board');
    expect(config.params).toMatchObject({
      date_from: today,
      date_to: today,
      comparar_con: 'periodo_anterior',
      group_by: 'product',
      solo_con_ventas: true,
      limit: 1,
      offset: 0,
    });
    // What reaches the API: the backend reads the day as YYYY-MM-DD and answers 422 to a timestamp.
    const query = new URLSearchParams(axios.getUri({ url, params: config.params }).split('?')[1]);
    expect(query.get('date_from')).toBe(today);
    expect(query.get('date_to')).toBe(today);
  });

  it('never asks the old dashboard, and shows the weather without the new screen permission', async () => {
    permisosStub.permisos = ['ventas_ml.ver_dashboard'];
    weatherStub.weather = WEATHER;
    renderTopBar();
    expect(await screen.findByText('22°')).toBeInTheDocument();
    expect(screen.queryByText('Facturado ML Hoy')).not.toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
  });

  it('keeps showing the weather when the new board bills $0 today', async () => {
    permisosStub.permisos = ['ml_metricas.ver'];
    weatherStub.weather = WEATHER;
    renderTopBar();
    expect(await screen.findByText('22°')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Facturado ML Hoy/ })).not.toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/ml-metricas/board', expect.anything());
  });

  it('logs a failed request and keeps the weather', async () => {
    permisosStub.permisos = ['ml_metricas.ver'];
    weatherStub.weather = WEATHER;
    const error = new Error('Request failed with status code 422');
    api.get.mockRejectedValue(error);
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    renderTopBar();
    expect(await screen.findByText('22°')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Facturado ML Hoy/ })).not.toBeInTheDocument();
    await waitFor(() => expect(consoleError).toHaveBeenCalledWith(expect.stringContaining('Facturado ML Hoy'), error));
    consoleError.mockRestore();
  });
});
