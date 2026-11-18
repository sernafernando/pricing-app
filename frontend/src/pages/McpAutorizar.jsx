import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import { oauthAPI } from '../services/api';
import styles from './McpAutorizar.module.css';

const MENSAJE_VENCIDO = 'El pedido de conexión venció o ya se usó. Volvé a conectar desde la aplicación de IA.';
const MENSAJE_SIN_PERMISO = 'No tenés permiso para conectar aplicaciones de IA (mcp.conectar). Pedíselo a un administrador.';
const MENSAJE_SIN_ESCRITURA = 'Solo lectura: no tenés permiso para modificar (mcp.escribir)';
const MENSAJE_ERROR = 'No se pudo completar la conexión. Probá de nuevo en unos minutos.';

const irAUrlExterna = (url) => window.location.assign(url);

/**
 * Consent step of the OAuth flow for MCP clients (ChatGPT, Claude, Cursor, Gemini CLI).
 * The wording says whether the token can also write (scope pricing.write, user
 * holds mcp.escribir) or was downgraded to read-only. The backend's
 * /api/oauth/authorize sends the browser here with `?req=<id>`; the normal
 * login (ProtectedRoute + Login return-to) runs first when there is no session.
 * The decision goes back to the backend, which answers with the URL to send the
 * browser to (the client's callback, built only from the stored request).
 *
 * `irA` exists so tests can observe the external navigation.
 */
export default function McpAutorizar({ irA = irAUrlExterna }) {
  const [searchParams] = useSearchParams();
  const req = searchParams.get('req');
  const user = useAuthStore((state) => state.user);
  const [pedido, setPedido] = useState(null);
  const [cargando, setCargando] = useState(Boolean(req));
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState(req ? null : MENSAJE_VENCIDO);
  const [terminal, setTerminal] = useState(!req);

  useEffect(() => {
    if (!req) return undefined;
    let vigente = true;
    oauthAPI
      .obtenerPedido(req)
      .then(({ data }) => {
        if (vigente) setPedido(data);
      })
      .catch((err) => {
        if (!vigente) return;
        setError(err?.response?.status === 404 ? MENSAJE_VENCIDO : MENSAJE_ERROR);
        setTerminal(true);
      })
      .finally(() => {
        if (vigente) setCargando(false);
      });
    return () => {
      vigente = false;
    };
  }, [req]);

  const decidir = async (approve) => {
    setEnviando(true);
    setError(null);
    try {
      const { data } = await oauthAPI.decidir(req, approve);
      irA(data.redirect_to);
    } catch (err) {
      const status = err?.response?.status;
      if (status === 404) {
        setError(MENSAJE_VENCIDO);
        setTerminal(true);
      } else if (status === 403) {
        setError(MENSAJE_SIN_PERMISO);
      } else {
        setError(MENSAJE_ERROR);
      }
      setEnviando(false);
    }
  };

  const nombreUsuario = user?.nombre || user?.username || 'tu usuario';
  const cliente = pedido?.client_name || 'La aplicación';
  // pricing.write: `escritura` = the token will carry it; asked but not granted = downgraded to read-only.
  const escritura = pedido?.escritura === true;
  const escrituraDenegada = pedido?.escritura_pedida === true && !escritura;

  return (
    <div className={styles.container}>
      <section className={styles.card} aria-labelledby="mcp-autorizar-titulo">
        <h1 id="mcp-autorizar-titulo" className={styles.titulo}>
          Conectar con Pricing
        </h1>

        {cargando && <p className={styles.muted}>Cargando el pedido de conexión...</p>}

        {!cargando && pedido && !terminal && (
          <>
            <p className={styles.texto}>
              <strong>{cliente}</strong> quiere {escritura ? 'consultar y MODIFICAR' : 'consultar'} Pricing como{' '}
              <strong>{nombreUsuario}</strong>.
            </p>
            <p className={styles.texto}>
              La conexión vuelve a <strong>{pedido.redirect_host}</strong>
              {pedido.redirect_local ? ' (en esta computadora)' : ''}.
            </p>
            <ul className={styles.detalles}>
              <li>Permití solo si iniciaste vos esta conexión recién, desde {cliente}.</li>
              {escritura ? (
                <>
                  <li>
                    Puede modificar promociones, precios de lista, precios en cuotas, precios mayoristas y pausar o activar
                    publicaciones.
                  </li>
                  <li>Cada cambio necesita un plan y tu confirmación, y queda en Acciones IA, donde se puede Deshacer.</li>
                </>
              ) : (
                <li>Acceso de solo lectura: puede consultar, no puede modificar nada.</li>
              )}
              <li>Ve lo mismo que vos: trabaja con tus mismos permisos.</li>
              <li>Podés revocar la conexión cuando quieras desde un administrador.</li>
            </ul>
            {escrituraDenegada && <p className={styles.nota}>{MENSAJE_SIN_ESCRITURA}</p>}
          </>
        )}

        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}

        {!cargando && pedido && !terminal && (
          <div className={styles.acciones}>
            <button
              type="button"
              className="btn-tesla ghost sm"
              disabled={enviando}
              onClick={() => decidir(false)}
            >
              Cancelar
            </button>
            <button
              type="button"
              className="btn-tesla outline-subtle-success sm"
              disabled={enviando}
              onClick={() => decidir(true)}
            >
              Permitir
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
