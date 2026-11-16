/**
 * Cargas de PDF — /metricas-ml/cargas (ODD `vpf-metricas-canal-fe` T3, mockup 4-historial-cargas.png).
 *
 * History of GBP PDF loads for "ventas por fuera" (GET /ventas-fuera-pdf/cargas, contract C2) with the detail of the
 * selected load, the parts of each scope still missing a report (GET /alcances, L8/L11) and, only with
 * `ventas_fuera.subir_pdf`, the drop zone and the button that open the upload modal. The PDFs are not stored, so
 * the detail lists file names only.
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { FileText, TriangleAlert, Upload } from 'lucide-react';
import api from '../services/api';
import { usePermisos } from '../contexts/PermisosContext';
import SubirPdfModal from '../components/ventasFueraPdf/SubirPdfModal';
import { diaHora, dinero, entero, rango, rangoCorto } from '../components/ventasFueraPdf/formato';
import styles from './CargasPdf.module.css';

const BASE = '/ventas-fuera-pdf';
const PAGE_SIZE = 50;
const DIAS = [30, 90, 180, 365];

const CONTROL = {
  ok: { texto: () => 'OK', tono: 'ok' },
  avisos: {
    texto: (fila) => {
      const n = fila.avisos?.length || 1;
      return `${n} ${n === 1 ? 'aviso' : 'avisos'}`;
    },
    tono: 'aviso',
  },
  sin_resumen: { texto: () => 'sin resumen', tono: 'neutro' },
  sin_detallada: { texto: () => 'sin detallada', tono: 'neutro' },
};

function ControlPill({ fila }) {
  if (fila.estado === 'reemplazada') return <span className={styles.tag}>reemplazada</span>;
  const control = CONTROL[fila.control];
  if (!control) return '—';
  return (
    <span className={styles.pill} data-tono={control.tono}>
      {control.texto(fila)}
    </span>
  );
}

function VendedorCelda({ fila }) {
  if (fila.vendedor) return fila.vendedor;
  if (fila.vendedores?.length === 1) return fila.vendedores[0];
  return (
    <>
      Todos{fila.vendedores?.length ? <span className={styles.suave}> ({fila.vendedores.length})</span> : null}
    </>
  );
}

const nombreVendedor = (fila) =>
  fila.vendedor ?? (fila.vendedores?.length === 1 ? fila.vendedores[0] : 'Todos');

// An aviso that only restates the totals difference as the cheque surcharge, which the "Totales distintos" box
// already explains. Per-document avisos ("Fc A 00008-00018044: …", e.g. a surcharge away from 4%) say something
// else and always stay.
const POR_DOCUMENTO = /^(Fc|Nc|Nd) [A-Z] \d{5}-\d{8}\b/;
const repiteCheques = (aviso) => !POR_DOCUMENTO.test(aviso) && /totales/i.test(aviso) && /cheque/i.test(aviso);

function Detalle({ fila }) {
  const control = fila.control_detalle;
  const diferencia = Number(control?.diferencia || 0);
  const explicaCheques = Boolean(control?.resumen && diferencia !== 0 && control.cheques?.length);
  const avisos = (fila.avisos || []).filter((aviso) => !(explicaCheques && repiteCheques(aviso)));
  return (
    <aside className={styles.detalle} aria-label="Detalle de la carga">
      <h2 className={styles.detalleTitulo}>Carga del {diaHora(fila.created_at)}</h2>
      <p className={styles.detalleSub}>
        {fila.empresa} · {nombreVendedor(fila)}
      </p>
      <dl className={styles.datos}>
        <dt>Rango</dt>
        <dd className={styles.num}>{rango(fila.desde, fila.hasta)}</dd>
        <dt>Comprobantes</dt>
        <dd>
          <span className={styles.num}>{entero(fila.documentos)}</span>
          {fila.documentos_por_tipo?.length > 0 && (
            <span className={styles.suave}>
              {' · '}
              {fila.documentos_por_tipo.map((t) => `${entero(t.cantidad)} ${t.tipo} ${t.letra}`).join(' · ')}
            </span>
          )}
        </dd>
        <dt>Líneas</dt>
        <dd>
          <span className={styles.num}>{entero(fila.lineas)}</span>
          {fila.unidades !== null && fila.unidades !== undefined && (
            <span className={styles.suave}> · {entero(fila.unidades)} u</span>
          )}
        </dd>
        <dt>Total líneas</dt>
        <dd className={styles.num}>{dinero(fila.total_lineas)}</dd>
      </dl>

      <ul className={styles.archivos} aria-label="Archivos">
        {[
          [fila.archivo_detallado, null],
          [fila.archivo_resumen, 'resumen'],
        ]
          .filter(([nombre]) => nombre)
          .map(([nombre, nota]) => (
            <li key={nombre + (nota || '')}>
              <FileText size={14} aria-hidden="true" />
              <span>{nombre}</span>
              {nota && <span className={styles.suave}> · {nota}</span>}
            </li>
          ))}
      </ul>

      {control && control.resumen && diferencia !== 0 && (
        <div className={`${styles.nota} ${styles.notaAviso}`}>
          <strong>Totales distintos</strong>
          <p>
            Resumen <span className={styles.num}>{dinero(control.total_resumen)}</span> vs líneas{' '}
            <span className={styles.num}>{dinero(control.total_lineas)}</span>
            {control.cheques?.length > 0 ? (
              <>
                : recargo de {control.cheques.length} {control.cheques.length === 1 ? 'factura' : 'facturas'} con cheque (
                <span className={styles.num}>{dinero(fila.recargo_financiero ?? control.diferencia)}</span>), guardado
                aparte.
              </>
            ) : (
              <>
                : diferencia <span className={styles.num}>{dinero(control.diferencia)}</span>.
              </>
            )}
          </p>
        </div>
      )}
      {fila.control === 'sin_resumen' && <div className={styles.nota}>Sin resumen: los totales no se controlaron.</div>}
      {fila.control === 'sin_detallada' && (
        <div className={styles.nota}>Falta la detallada: este resumen todavía no tiene ventas que controlar.</div>
      )}
      {avisos.length > 0 && (
        <ul className={styles.avisos}>
          {avisos.map((aviso) => (
            <li key={aviso}>
              <TriangleAlert size={13} aria-hidden="true" />
              <span>{aviso}</span>
            </li>
          ))}
        </ul>
      )}
      {fila.estado === 'reemplazada' && <div className={styles.nota}>Una carga posterior la reemplazó.</div>}
      {fila.reemplazados > 0 &&
        (fila.carga_anterior_at ? (
          <div className={styles.nota}>
            Reemplazó la carga del <strong>{diaHora(fila.carga_anterior_at)}</strong> ({entero(fila.reemplazados)}{' '}
            comprobantes del mismo vendedor y rango).
          </div>
        ) : (
          <div className={styles.nota}>
            Reemplazó <strong>{entero(fila.reemplazados)} comprobantes</strong> del mismo vendedor y rango.
          </div>
        ))}
      {fila.sin_producto_lineas > 0 && (
        <div className={styles.nota}>
          <strong>{entero(fila.sin_producto_lineas)} líneas sin producto</strong> ·{' '}
          <span className={styles.num}>{dinero(fila.sin_producto_monto)}</span>{' '}
          {/* The PDF price, without VAT. */}
          <span className={styles.suave}>sin IVA</span>
        </div>
      )}
      <p className={styles.detallePie}>Subido por {fila.usuario ?? '—'}</p>
    </aside>
  );
}

function FaltanReportes({ alcances }) {
  const faltantes = alcances.flatMap((a) => (a.faltantes || []).map((f) => ({ ...f, empresa: a.empresa, alcance: a.id })));
  if (faltantes.length === 0) return null;
  return (
    <section className={styles.faltan} aria-label="Faltan reportes">
      <h2 className={styles.faltanTitulo}>
        <TriangleAlert size={14} aria-hidden="true" /> Faltan reportes
      </h2>
      <ul>
        {faltantes.map((f) => (
          <li key={`${f.alcance}-${f.reporte}-${f.vendedor}-${f.desde}`}>
            <strong>{f.reporte === 'resumen' ? 'Falta el resumen' : 'Falta la detallada'}</strong>
            <span className={styles.suave}>
              {' '}
              · {f.empresa} · {f.vendedor ?? 'Todos'} · {rangoCorto(f.desde, f.hasta)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function CargasPdf() {
  const { tienePermiso } = usePermisos();
  const puedeSubir = tienePermiso('ventas_fuera.subir_pdf');
  const puedeAdministrar = tienePermiso('ventas_fuera.ver_dashboard');

  const [empresa, setEmpresa] = useState('');
  const [vendedor, setVendedor] = useState('');
  const [dias, setDias] = useState(90);
  const [filas, setFilas] = useState([]);
  const [hayMas, setHayMas] = useState(false);
  const [pagina, setPagina] = useState(1);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [alcances, setAlcances] = useState([]);
  const [empresas, setEmpresas] = useState([]);
  const [vendedores, setVendedores] = useState([]);
  const [seleccion, setSeleccion] = useState(null);
  const [modal, setModal] = useState(null); // { archivos } while open
  const [recarga, setRecarga] = useState(0);
  const [arrastrando, setArrastrando] = useState(false);

  useEffect(() => {
    let vigente = true;
    const params = { dias, page: pagina, page_size: PAGE_SIZE };
    if (empresa) params.empresa = empresa;
    if (vendedor) params.vendedor = vendedor;
    setCargando(true);
    setError('');
    api
      .get(`${BASE}/cargas`, { params })
      .then(({ data }) => {
        if (!vigente) return;
        setFilas((prev) => (pagina === 1 ? data : [...prev, ...data]));
        setHayMas(data.length === PAGE_SIZE);
        // Filter options grow with what was seen, so a filter never hides its own alternatives.
        setEmpresas((prev) => [...new Set([...prev, ...data.map((f) => f.empresa)])].sort());
        setVendedores((prev) =>
          [...new Set([...prev, ...data.flatMap((f) => [f.vendedor, ...(f.vendedores || [])]).filter(Boolean)])].sort(),
        );
      })
      .catch(() => {
        if (vigente) setError('No se pudo cargar el historial de cargas. Probá de nuevo en un rato.');
      })
      .finally(() => {
        if (vigente) setCargando(false);
      });
    return () => {
      vigente = false;
    };
  }, [empresa, vendedor, dias, pagina, recarga]);

  useEffect(() => {
    let vigente = true;
    api
      .get(`${BASE}/alcances`, { params: empresa ? { empresa } : {} })
      .then(({ data }) => {
        if (vigente) setAlcances(data);
      })
      .catch(() => {
        if (vigente) setAlcances([]);
      });
    return () => {
      vigente = false;
    };
  }, [empresa, recarga]);

  const filtrar = (cambio) => {
    cambio();
    setPagina(1);
    setSeleccion(null);
  };

  const seleccionada = filas.find((f) => f.id === seleccion) || filas[0] || null;

  const alCargar = () => {
    setPagina(1);
    setSeleccion(null);
    setRecarga((n) => n + 1);
  };

  return (
    <div className={styles.container}>
      <nav className={styles.migas} aria-label="Ruta">
        <Link to="/metricas-ml">Métricas</Link>
        <span aria-hidden="true"> › </span>
        <Link to="/metricas-ml?canal=fuera">Ventas por fuera</Link>
      </nav>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <h1>Cargas de PDF</h1>
          <p className={styles.description}>Cada PDF reemplaza lo cargado de su vendedor en su rango de fechas.</p>
        </div>
        <div className={styles.headerActions}>
          {puedeAdministrar && (
            <Link className={styles.quietLink} to="/dashboard-ventas-fuera/vendedores-excluidos">
              Vendedores excluidos
            </Link>
          )}
          {puedeSubir && (
            <button type="button" className="btn-tesla primary" onClick={() => setModal({ archivos: null })}>
              <Upload size={15} aria-hidden="true" /> Subir PDF de ventas
            </button>
          )}
        </div>
      </header>

      {puedeSubir && (
        <div
          className={`${styles.dropZone} ${arrastrando ? styles.dropZoneActiva : ''}`}
          onDragOver={(e) => {
            e.preventDefault();
            setArrastrando(true);
          }}
          onDragLeave={() => setArrastrando(false)}
          onDrop={(e) => {
            e.preventDefault();
            setArrastrando(false);
            setModal({ archivos: [...(e.dataTransfer.files || [])] });
          }}
        >
          <span className={styles.dropIcono} aria-hidden="true">
            <Upload size={18} />
          </span>
          <div>
            <p className={styles.dropTexto}>
              <strong>Arrastrá el Reporte de Ventas Detalladas de GBP</strong>
              <span className={styles.suave}> y, si querés, el Reporte de Ventas para controlar totales · </span>
              <button type="button" className={styles.link} onClick={() => setModal({ archivos: null })}>
                o elegí los archivos
              </button>
            </p>
            <p className={styles.dropAyuda}>
              PDF exportado de GBP con “Con Impuestos: No”. Puede ser de un vendedor o de Todos.
            </p>
          </div>
        </div>
      )}

      <div className={styles.filtros}>
        <div className={styles.filtro} role="group" aria-label="Empresa">
          <span className={styles.filtroLabel}>Empresa:</span>
          {['', ...empresas].map((opcion) => (
            <button
              key={opcion || 'todas'}
              type="button"
              className={styles.chip}
              aria-pressed={empresa === opcion}
              onClick={() => filtrar(() => setEmpresa(opcion))}
            >
              {opcion || 'Todas'}
            </button>
          ))}
        </div>
        <label className={styles.filtro}>
          <span className={styles.filtroLabel}>Vendedor:</span>
          <select
            className={styles.select}
            aria-label="Vendedor"
            value={vendedor}
            onChange={(e) => filtrar(() => setVendedor(e.target.value))}
          >
            <option value="">Todos</option>
            {vendedores.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.filtro}>
          <span className={styles.filtroLabel}>Cargas:</span>
          <select
            className={styles.select}
            aria-label="Cargas"
            value={dias}
            onChange={(e) => filtrar(() => setDias(Number(e.target.value)))}
          >
            {DIAS.map((d) => (
              <option key={d} value={d}>
                Últimos {d} días
              </option>
            ))}
          </select>
        </label>
      </div>

      <FaltanReportes alcances={alcances} />

      <div className={styles.cuerpo}>
        <section className={styles.tablaCard} aria-label="Historial de cargas">
          <h2 className={styles.tablaTitulo}>
            Historial de cargas <span className={styles.suave}>· {filas.length === 1 ? '1 carga' : `${filas.length} cargas`}</span>
          </h2>
          {error && (
            <div className={styles.error} role="alert">
              {error}
            </div>
          )}
          <div className={styles.tablaScroll}>
            <table className={styles.tabla}>
              <thead>
                <tr>
                  <th>Fecha de carga</th>
                  <th>Empresa</th>
                  <th>Vendedor</th>
                  <th>Rango del PDF</th>
                  <th className={styles.derecha}>Comprob.</th>
                  <th className={styles.derecha}>Líneas</th>
                  <th className={styles.derecha}>Total líneas</th>
                  <th className={styles.derecha}>Reemplazó</th>
                  <th className={styles.derecha}>Sin producto</th>
                  <th>Control</th>
                  <th>Subido por</th>
                </tr>
              </thead>
              <tbody>
                {filas.map((fila) => (
                  <tr
                    key={fila.id}
                    data-estado={fila.estado}
                    aria-selected={seleccionada?.id === fila.id}
                    tabIndex={0}
                    onClick={() => setSeleccion(fila.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        setSeleccion(fila.id);
                      }
                    }}
                  >
                    <td className={styles.num}>{diaHora(fila.created_at)}</td>
                    <td>{fila.empresa}</td>
                    <td>
                      <VendedorCelda fila={fila} />
                    </td>
                    <td className={styles.num}>{rangoCorto(fila.desde, fila.hasta)}</td>
                    <td className={`${styles.num} ${styles.derecha}`}>{entero(fila.documentos)}</td>
                    <td className={`${styles.num} ${styles.derecha}`}>{entero(fila.lineas)}</td>
                    <td className={`${styles.num} ${styles.derecha}`}>{dinero(fila.total_lineas)}</td>
                    <td className={`${styles.num} ${styles.derecha}`}>{entero(fila.reemplazados)}</td>
                    <td className={`${styles.num} ${styles.derecha}`}>{entero(fila.sin_producto_lineas)}</td>
                    <td>
                      <ControlPill fila={fila} />
                    </td>
                    <td>{fila.usuario ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!cargando && !error && filas.length === 0 && (
            <p className={styles.vacio}>No hay cargas en este período.</p>
          )}
          {cargando && <p className={styles.vacio}>Cargando…</p>}
          {hayMas && !cargando && (
            <button type="button" className={styles.verMas} onClick={() => setPagina((p) => p + 1)}>
              Ver más cargas
            </button>
          )}
        </section>
        {seleccionada && <Detalle fila={seleccionada} />}
      </div>

      {modal && (
        <SubirPdfModal
          isOpen
          archivosIniciales={modal.archivos}
          onClose={() => setModal(null)}
          onCargado={alCargar}
        />
      )}
    </div>
  );
}
