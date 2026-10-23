/**
 * ApiDocs: the in-app API reference. It fetches the schema from `GET /dev/openapi.json` (gated by
 * `admin.ver_api_docs` in the backend) with the user's token and hands it to Scalar, so the docs work in
 * production where FastAPI's own `/api/docs` is disabled and a plain navigation carries no token.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import ApiDocs from './ApiDocs';
import api from '../services/api';

vi.mock('../services/api', () => ({ default: { get: vi.fn() } }));

vi.mock('../contexts/ThemeContext', () => ({ useTheme: () => ({ theme: 'dark' }) }));

const scalarProps = vi.fn();
vi.mock('@scalar/api-reference-react', () => ({
  ApiReferenceReact: (props) => {
    scalarProps(props);
    return <div data-testid="scalar" />;
  },
}));

const SCHEMA = { openapi: '3.1.0', info: { title: 'Pricing API', version: '1.0.0' }, paths: {} };

describe('ApiDocs', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.setItem('token', 'jwt-123');
  });

  it('fetches the schema from the permission-gated endpoint and renders it with Scalar', async () => {
    api.get.mockResolvedValue({ data: SCHEMA });

    render(<ApiDocs />);

    expect(await screen.findByTestId('scalar')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/dev/openapi.json');
    const { configuration } = scalarProps.mock.calls.at(-1)[0];
    expect(configuration.content).toEqual(SCHEMA);
  });

  it('prefills the Bearer token and keeps Scalar from calling home', async () => {
    api.get.mockResolvedValue({ data: SCHEMA });

    render(<ApiDocs />);

    await screen.findByTestId('scalar');
    const { configuration } = scalarProps.mock.calls.at(-1)[0];
    expect(configuration.authentication).toEqual({
      preferredSecurityScheme: 'HTTPBearer',
      securitySchemes: { HTTPBearer: { token: 'jwt-123' } },
    });
    expect(configuration.persistAuth).toBe(false);
    expect(configuration.telemetry).toBe(false);
    expect(configuration.withDefaultFonts).toBe(false);
    expect(configuration.agent).toEqual({ disabled: true });
    expect(configuration.mcp).toEqual({ disabled: true });
    expect(configuration.showToolbar).toBe('never');
    expect(configuration.showDeveloperTools).toBe('never');
    expect(configuration.forceDarkModeState).toBe('dark');
  });

  it('sends the current session token on Test Request after a refresh rotated it', async () => {
    api.get.mockResolvedValue({ data: SCHEMA });
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'));

    render(<ApiDocs />);

    await screen.findByTestId('scalar');
    const { configuration } = scalarProps.mock.calls.at(-1)[0];
    localStorage.setItem('token', 'jwt-rotated');
    const origin = window.location.origin;

    await configuration.customFetch(`${origin}/api/auth/me`, { headers: { Authorization: 'Bearer jwt-123' } });
    await configuration.customFetch(`${origin}/api/auth/me`, { headers: { Authorization: 'Bearer typed-by-hand' } });
    await configuration.customFetch('https://example.com/x', { headers: { Authorization: 'Bearer jwt-123' } });

    const sent = fetchSpy.mock.calls.map(([, init]) => new Headers(init.headers).get('Authorization'));
    expect(sent).toEqual(['Bearer jwt-rotated', 'Bearer typed-by-hand', 'Bearer jwt-123']);
    fetchSpy.mockRestore();
  });

  it('swaps the token on a Request object too, and leaves the request alone once logged out', async () => {
    api.get.mockResolvedValue({ data: SCHEMA });
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'));

    render(<ApiDocs />);

    await screen.findByTestId('scalar');
    const { configuration } = scalarProps.mock.calls.at(-1)[0];
    const url = `${window.location.origin}/api/auth/me`;
    const request = () => new Request(url, { headers: { Authorization: 'Bearer jwt-123' } });

    localStorage.setItem('token', 'jwt-rotated');
    await configuration.customFetch(request());
    localStorage.removeItem('token');
    await configuration.customFetch(request());

    const sent = fetchSpy.mock.calls.map(([, init]) => new Headers(init.headers).get('Authorization'));
    expect(sent).toEqual(['Bearer jwt-rotated', 'Bearer jwt-123']);
    fetchSpy.mockRestore();
  });

  it('shows the error instead of the reference when the schema cannot be loaded', async () => {
    api.get.mockRejectedValue(new Error('403'));

    render(<ApiDocs />);

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('No se pudo cargar la documentación de la API'));
    expect(screen.queryByTestId('scalar')).not.toBeInTheDocument();
  });
});
