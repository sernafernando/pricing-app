import { useEffect, useState } from 'react';
import { ApiReferenceReact } from '@scalar/api-reference-react';
// The wrapper's JS does not import its own stylesheet (only its .d.ts claims to).
import '@scalar/api-reference-react/style.css';
import api from '../services/api';
import { useTheme } from '../contexts/ThemeContext';
import styles from './ApiDocs.module.css';

// The schema's paths already carry the `/api` prefix, so the server is the API's origin.
const API_ORIGIN = new URL(import.meta.env.VITE_API_URL || '/', window.location.origin).origin;

/**
 * In-app API reference (Scalar). FastAPI's own `/api/docs` is disabled outside development and a plain
 * navigation carries no Bearer token, so the schema comes from `GET /dev/openapi.json`, which the backend
 * gates with `admin.ver_api_docs`. The token is prefilled for Scalar's request client but never persisted
 * by it. Everything that talks to Scalar's servers is off: telemetry, CDN fonts, the
 * "Ask AI" agent, MCP and the Share/Deploy toolbar.
 */
export default function ApiDocs() {
  const { theme } = useTheme();
  const [schema, setSchema] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .get('/dev/openapi.json')
      .then(({ data }) => {
        if (!cancelled) setSchema(data);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <p role="alert" className={styles.error}>
        No se pudo cargar la documentación de la API.
      </p>
    );
  }

  if (!schema) {
    return <p className={styles.status}>Cargando documentación…</p>;
  }

  return (
    <div className={styles.page}>
      <ApiReferenceReact
        configuration={{
          content: schema,
          servers: [{ url: API_ORIGIN }],
          authentication: {
            preferredSecurityScheme: 'HTTPBearer',
            securitySchemes: { HTTPBearer: { token: localStorage.getItem('token') ?? '' } },
          },
          persistAuth: false,
          telemetry: false,
          withDefaultFonts: false,
          agent: { disabled: true },
          mcp: { disabled: true },
          // The toolbar's Share and Deploy upload the schema to Scalar's cloud.
          showToolbar: 'never',
          showDeveloperTools: 'never',
          hideDarkModeToggle: true,
          forceDarkModeState: theme === 'dark' ? 'dark' : 'light',
        }}
      />
    </div>
  );
}
