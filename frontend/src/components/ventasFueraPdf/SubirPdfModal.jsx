/**
 * Upload of GBP's sales reports for "ventas por fuera" (ODD `vpf-metricas-canal-fe` T3, mockup 3, contract C1).
 *
 * Three steps in one modal:
 *   1. archivos: the detailed report (the operations) and, optional, the summary (the control);
 *   2. vendedores: POST /cargas/preview reads them without storing anything and lists the salespeople found; the
 *      user ticks which ones to import (L22). Salespeople of the excluded list come unticked;
 *   3. resultado: POST /cargas with `vendedores` stores the chosen ones and the modal shows what was loaded.
 *
 * It closes only with its X, Cancelar or "Ver métricas" (no overlay click, no Escape).
 */
import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, FileText, Package, RefreshCw, TriangleAlert } from 'lucide-react';
import api from '../../services/api';
import ModalTesla from '../ModalTesla';
import {
  comprobante,
  diaHora,
  diaMes,
  dinero,
  entero,
  enumerar,
  fecha,
  fechaHora,
  mensajeError,
  rango,
} from './formato';
import styles from './SubirPdfModal.module.css';

const BASE = '/ventas-fuera-pdf';

const tamanio = (bytes) =>
  bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1).replace('.', ',')} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;

/** Which dropped file is which report: the one named "detallad…" is the detailed one, else the first. */
function repartirArchivos(archivos) {
  const pdfs = [...(archivos || [])].slice(0, 2);
  if (pdfs.length === 0) return { detallada: null, resumen: null };
  const i = pdfs.findIndex((f) => /detallad/i.test(f.name));
  const detallada = pdfs[i >= 0 ? i : 0];
  return { detallada, resumen: pdfs.find((f) => f !== detallada) || null };
}

function SlotArchivo({ titulo, nota, archivo, onElegir, compacto }) {
  const inputRef = useRef(null);
  const [arrastrando, setArrastrando] = useState(false);

  return (
    <div
      className={`${styles.slot} ${archivo ? styles.slotListo : ''} ${arrastrando ? styles.slotArrastrando : ''}`}
      onDragOver={(e) => {
        e.preventDefault();
        if (!compacto) setArrastrando(true);
      }}
      onDragLeave={() => setArrastrando(false)}
      onDrop={(e) => {
        e.preventDefault();
        setArrastrando(false);
        if (!compacto && e.dataTransfer.files?.[0]) onElegir(e.dataTransfer.files[0]);
      }}
    >
      <span className={styles.slotIcono} aria-hidden="true">
        <FileText size={16} />
      </span>
      <div className={styles.slotTexto}>
        <div className={styles.slotTitulo}>
          <strong>{titulo}</strong> <span className={styles.slotNota}>{nota}</span>
        </div>
        {archivo ? (
          <div className={styles.slotArchivo}>
            {archivo.name} · {tamanio(archivo.size)}
          </div>
        ) : (
          <div className={styles.slotArchivo}>Arrastrá el PDF acá</div>
        )}
        {!compacto && (
          <button type="button" className={styles.link} onClick={() => inputRef.current?.click()}>
            {archivo ? 'Cambiar archivo' : 'o elegilo'}
          </button>
        )}
      </div>
      {archivo && <Check size={16} className={styles.slotCheck} aria-label="Listo" />}
      <input
        ref={inputRef}
        type="file"
        hidden
        accept="application/pdf,.pdf"
        aria-label={`${titulo} (PDF)`}
        onChange={(e) => {
          if (e.target.files?.[0]) onElegir(e.target.files[0]);
          e.target.value = '';
        }}
      />
    </div>
  );
}

function Dato({ label, children }) {
  return (
    <>
      <dt className={styles.datoLabel}>{label}</dt>
      <dd className={styles.datoValor}>{children}</dd>
    </>
  );
}

const faltanteTexto = (f) =>
  `${f.vendedor ?? 'Todos los vendedores'}, del ${diaMes(f.desde)} al ${fecha(f.hasta)}`;

/** `DISTRIBUIDORA ALFA SA ×2, COMERCIAL BETA SRL`. */
const clientesDeCheques = (cheques) => {
  const cuenta = new Map();
  for (const c of cheques) cuenta.set(c.cliente, (cuenta.get(c.cliente) || 0) + 1);
  return [...cuenta].map(([cliente, n]) => (n > 1 ? `${cliente} ×${n}` : cliente)).join(', ');
};

function ControlResumen({ carga }) {
  const [verCheques, setVerCheques] = useState(false);
  const control = carga.control || {};
  const cheques = control.cheques || [];
  const diferencia = Number(control.diferencia || 0);
  const faltantes = carga.faltantes || [];
  const avisa =
    (control.resumen && (control.documentos_coinciden === false || diferencia !== 0)) ||
    carga.falta_resumen ||
    carga.falta_detallada;

  return (
    <section className={`${styles.card} ${avisa ? styles.cardAviso : ''}`}>
      <h3 className={styles.cardTitulo}>Control con el resumen</h3>
      <ul className={styles.controlLista}>
        {control.resumen && control.documentos_coinciden === true && (
          <li className={styles.ok}>
            <Check size={14} aria-hidden="true" />
            <span>Los {entero(carga.documentos)} comprobantes coinciden en los dos PDF.</span>
          </li>
        )}
        {control.resumen && control.documentos_coinciden === false && (
          <li className={styles.aviso}>
            <TriangleAlert size={14} aria-hidden="true" />
            <span>Los comprobantes no coinciden en los dos PDF.</span>
          </li>
        )}
        {control.resumen && diferencia !== 0 && (
          <li className={styles.aviso}>
            <TriangleAlert size={14} aria-hidden="true" />
            <div>
              <span>
                <strong>Los totales no dan igual.</strong> Resumen{' '}
                <span className={styles.num}>{dinero(control.total_resumen)}</span> · líneas{' '}
                <span className={styles.num}>{dinero(control.total_lineas)}</span> · diferencia{' '}
                <span className={styles.num}>{dinero(control.diferencia)}</span>
              </span>
              {cheques.length > 0 && (
                <p className={styles.controlNota}>
                  Es el recargo de {cheques.length} {cheques.length === 1 ? 'factura' : 'facturas'} con cheque (
                  {clientesDeCheques(cheques)}). Queda guardado aparte por comprobante y no entra en ventas ni en
                  markup.{' '}
                  <button type="button" className={styles.link} onClick={() => setVerCheques((v) => !v)} aria-expanded={verCheques}>
                    {verCheques ? 'Ocultar comprobantes' : 'Ver comprobantes'}
                  </button>
                </p>
              )}
              {verCheques && (
                <ul className={styles.cheques}>
                  {cheques.map((c) => (
                    <li key={comprobante(c)}>
                      <span className={styles.num}>{comprobante(c)}</span>
                      <span className={styles.chequeCliente}>{c.cliente}</span>
                      <span className={styles.num}>{dinero(c.recargo)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </li>
        )}
        {control.resumen && diferencia === 0 && control.total_resumen !== null && control.total_resumen !== undefined && (
          <li className={styles.ok}>
            <Check size={14} aria-hidden="true" />
            <span>
              Los totales coinciden: <span className={styles.num}>{dinero(control.total_resumen)}</span>.
            </span>
          </li>
        )}
        {!control.resumen && !carga.falta_resumen && (
          <li className={styles.neutro}>
            <span>Sin resumen: los totales no se controlaron.</span>
          </li>
        )}
        {[
          ['resumen', carga.falta_resumen, 'Falta subir el resumen'],
          ['detallada', carga.falta_detallada, 'Falta subir la detallada'],
        ]
          .filter(([, falta]) => falta)
          .map(([reporte, , titulo]) => {
            const partes = faltantes.filter((f) => f.reporte === reporte);
            return (
              <li key={reporte} className={styles.aviso}>
                <TriangleAlert size={14} aria-hidden="true" />
                <div>
                  <strong>{titulo}</strong>
                  {partes.length > 0 && (
                    <span>
                      {' '}
                      de {partes.map(faltanteTexto).join('; ')}.
                    </span>
                  )}
                </div>
              </li>
            );
          })}
      </ul>
    </section>
  );
}

function Resultado({ carga }) {
  const vendedores = carga.vendedores?.length ? carga.vendedores : [carga.vendedor ?? 'Todos'];
  const porTipo = (carga.documentos_por_tipo || []).map((t) => `${entero(t.cantidad)} ${t.tipo} ${t.letra}`);
  const reemplazo = carga.reemplazo || { documentos: carga.reemplazados || 0, carga_anterior_at: null };
  const sinProducto = carga.sin_producto || { lineas: 0, monto: 0, articulos: [] };
  // C5: what changed against the replaced load; a zero part is left out.
  const cambios = [
    reemplazo.nuevos > 0 && `${entero(reemplazo.nuevos)} ${reemplazo.nuevos === 1 ? 'nuevo' : 'nuevos'}`,
    reemplazo.anulados > 0 && `${entero(reemplazo.anulados)} que ya no están en GBP (anulados)`,
  ].filter(Boolean);

  return (
    <div className={styles.resultado}>
      <h3 className={styles.seccion}>Resultado de la carga</h3>
      <dl className={styles.datos}>
        <Dato label="Empresa">{carga.empresa}</Dato>
        <Dato label="Vendedor">{vendedores.join(', ')}</Dato>
        <Dato label="Rango del PDF">
          <span className={styles.num}>{rango(carga.desde, carga.hasta)}</span>
        </Dato>
        <Dato label="Comprobantes">
          <span className={styles.num}>{entero(carga.documentos)}</span>
          {porTipo.length > 0 && <span className={styles.suave}> · {porTipo.join(' · ')}</span>}
        </Dato>
        <Dato label="Líneas cargadas">
          <span className={styles.num}>{entero(carga.lineas)}</span>
          {carga.unidades !== null && carga.unidades !== undefined && (
            <span className={styles.suave}> · {entero(carga.unidades)} unidades</span>
          )}
        </Dato>
        <Dato label="Total de líneas (sin IVA)">
          <strong className={styles.num}>{dinero(carga.total_lineas)}</strong>
        </Dato>
      </dl>

      {reemplazo.documentos > 0 && (
        <section className={styles.card}>
          <h3 className={styles.cardTitulo}>
            <RefreshCw size={14} aria-hidden="true" /> Reemplazado
          </h3>
          <p className={styles.cardTexto}>
            Se borraron <strong>{entero(reemplazo.documentos)} comprobantes</strong> de {enumerar(vendedores)} entre{' '}
            {diaMes(carga.desde)} y {diaMes(carga.hasta)}
            {reemplazo.carga_anterior_at && <> (carga del {diaHora(reemplazo.carga_anterior_at)})</>} y quedaron
            los {entero(carga.documentos)} de este PDF.{' '}
            {cambios.length > 0 && <span className={styles.suave}>{cambios.join(' · ')}.</span>}
          </p>
        </section>
      )}

      {sinProducto.lineas > 0 && (
        <section className={styles.card}>
          <h3 className={styles.cardTitulo}>
            <Package size={14} aria-hidden="true" /> {entero(sinProducto.lineas)} líneas sin producto ·{' '}
            <span className={styles.num}>{dinero(sinProducto.monto)}</span>{' '}
            {/* The PDF price, without VAT (the board shows the with-VAT figure). */}
            <span className={styles.suave}>sin IVA</span>
          </h3>
          <ul className={styles.articulos}>
            {(sinProducto.articulos || []).map((a) => (
              <li key={`${a.articulo}-${a.codigo ?? ''}`}>
                <span className={styles.articulo}>
                  <span>{a.articulo}</span>
                  {a.codigo && <span className={styles.suave}> · EAN {a.codigo} no está en el catálogo</span>}
                  {a.lineas > 1 && <span className={styles.suave}> · {entero(a.lineas)} líneas</span>}
                </span>
                <span className={`${styles.num} ${Number(a.monto) < 0 ? styles.negativo : ''}`}>{dinero(a.monto)}</span>
              </li>
            ))}
          </ul>
          <p className={styles.cardPie}>Se guardan y suman a la venta, sin marca, PM ni markup.</p>
        </section>
      )}

      <ControlResumen carga={carga} />

      {carga.avisos?.length > 0 && (
        <ul className={styles.avisos} aria-label="Avisos de la carga">
          {carga.avisos.map((aviso) => (
            <li key={aviso}>
              <TriangleAlert size={14} aria-hidden="true" />
              <span>{aviso}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** `/metricas-ml?canal=fuera&vendedores=…&empresas=…&periodo=custom&desde=…&hasta=…` for a load. */
function urlMetricas(carga) {
  const params = new URLSearchParams({ canal: 'fuera' });
  const vendedores = carga.vendedores?.length ? carga.vendedores : carga.vendedor ? [carga.vendedor] : [];
  if (vendedores.length) params.set('vendedores', vendedores.join(','));
  params.set('empresas', carga.empresa);
  params.set('periodo', 'custom');
  params.set('desde', carga.desde);
  params.set('hasta', carga.hasta);
  return `/metricas-ml?${params.toString()}`;
}

export default function SubirPdfModal({ isOpen, onClose, onCargado, archivosIniciales }) {
  const navigate = useNavigate();
  const [archivos, setArchivos] = useState(() => repartirArchivos(archivosIniciales));
  const [paso, setPaso] = useState('archivos');
  const [preview, setPreview] = useState(null);
  const [elegidos, setElegidos] = useState(() => new Set());
  const [carga, setCarga] = useState(null);
  const [error, setError] = useState('');
  const [enviando, setEnviando] = useState(false);

  const reiniciar = () => {
    setArchivos({ detallada: null, resumen: null });
    setPaso('archivos');
    setPreview(null);
    setElegidos(new Set());
    setCarga(null);
    setError('');
  };

  const cerrar = () => {
    reiniciar();
    onClose();
  };

  const formulario = () => {
    const form = new FormData();
    if (archivos.detallada) form.append('detallada', archivos.detallada);
    if (archivos.resumen) form.append('resumen', archivos.resumen);
    return form;
  };

  const leer = async () => {
    setEnviando(true);
    setError('');
    try {
      const { data } = await api.post(`${BASE}/cargas/preview`, formulario());
      setPreview(data);
      setElegidos(new Set(data.vendedores.filter((v) => !v.excluido).map((v) => v.vendedor)));
      setPaso('vendedores');
    } catch (err) {
      setError(mensajeError(err, 'No se pudo leer el PDF. Probá de nuevo.'));
    } finally {
      setEnviando(false);
    }
  };

  const importar = async () => {
    setEnviando(true);
    setError('');
    try {
      const form = formulario();
      if (preview.vendedores.length > 0) {
        // In the PDF's order, which is the order the user saw.
        const nombres = preview.vendedores.map((v) => v.vendedor).filter((n) => elegidos.has(n));
        form.append('vendedores', JSON.stringify(nombres));
      }
      const { data } = await api.post(`${BASE}/cargas`, form);
      setCarga(data);
      setPaso('resultado');
      onCargado?.(data);
    } catch (err) {
      setError(mensajeError(err, 'No se pudo importar. Probá de nuevo.'));
    } finally {
      setEnviando(false);
    }
  };

  const alternar = (nombre) => {
    setElegidos((prev) => {
      const next = new Set(prev);
      if (next.has(nombre)) next.delete(nombre);
      else next.add(nombre);
      return next;
    });
  };

  const verMetricas = () => {
    const url = urlMetricas(carga);
    cerrar();
    navigate(url);
  };

  const elegir = (clave) => (archivo) => {
    setArchivos((prev) => ({ ...prev, [clave]: archivo }));
    setError('');
  };

  const slots = (compacto) => (
    <div className={styles.slots}>
      <SlotArchivo
        titulo="Reporte de Ventas Detalladas"
        nota="obligatorio"
        archivo={archivos.detallada}
        onElegir={elegir('detallada')}
        compacto={compacto}
      />
      <SlotArchivo
        titulo="Reporte de Ventas (resumen)"
        nota="opcional, para controlar"
        archivo={archivos.resumen}
        onElegir={elegir('resumen')}
        compacto={compacto}
      />
    </div>
  );

  const errorBox = error && (
    <div className={styles.error} role="alert">
      <TriangleAlert size={14} aria-hidden="true" />
      <span>{error}</span>
    </div>
  );

  const nElegidos = elegidos.size;
  const soloVendedor = carga?.vendedores?.length === 1 ? carga.vendedores[0] : carga?.vendedor;

  let cuerpo;
  let pie;
  if (paso === 'archivos') {
    cuerpo = (
      <>
        {slots(false)}
        <p className={styles.ayuda}>
          PDF exportado de GBP con “Con Impuestos: No”. Puede ser de un vendedor o de Todos: en el paso siguiente
          elegís qué vendedores importar.
        </p>
        {errorBox}
      </>
    );
    pie = (
      <div className={styles.pie}>
        <span />
        <div className={styles.acciones}>
          <button type="button" className="btn-tesla secondary" onClick={cerrar}>
            Cancelar
          </button>
          <button
            type="button"
            className="btn-tesla primary"
            onClick={leer}
            disabled={enviando || (!archivos.detallada && !archivos.resumen)}
          >
            {enviando ? 'Leyendo…' : 'Leer PDF'}
          </button>
        </div>
      </div>
    );
  } else if (paso === 'vendedores') {
    const sinVentas = preview.vendedores.length === 0;
    cuerpo = (
      <>
        {slots(true)}
        <h3 className={styles.seccion}>Vendedores en el PDF</h3>
        <p className={styles.meta}>
          {preview.empresa} · <span className={styles.num}>{rango(preview.desde, preview.hasta)}</span> ·{' '}
          {preview.vendedor_filtro ? `PDF de ${preview.vendedor_filtro}` : 'PDF de todos los vendedores'}
        </p>
        {sinVentas ? (
          <p className={styles.card}>El resumen queda como control: no trae ventas para importar.</p>
        ) : (
          <div className={styles.lista}>
            {preview.vendedores.map((v) => (
              <label key={v.vendedor} className={`${styles.fila} ${v.excluido ? styles.filaExcluida : ''}`}>
                <input type="checkbox" checked={elegidos.has(v.vendedor)} onChange={() => alternar(v.vendedor)} />
                <span className={styles.filaNombre}>
                  {v.vendedor}
                  {v.excluido && <span className={styles.tag}>excluido</span>}
                </span>
                <span className={styles.filaDocs}>
                  {entero(v.documentos)} {v.documentos === 1 ? 'comprobante' : 'comprobantes'}
                </span>
                <span className={`${styles.num} ${styles.filaMonto}`}>{dinero(v.total_lineas)}</span>
              </label>
            ))}
          </div>
        )}
        {!sinVentas && (
          <p className={styles.ayuda}>
            Solo se guardan los vendedores marcados: cada uno reemplaza lo cargado de él en este rango. Los de la lista
            de excluidos vienen sin marcar.
          </p>
        )}
        {errorBox}
      </>
    );
    pie = (
      <div className={styles.pie}>
        <span />
        <div className={styles.acciones}>
          <button
            type="button"
            className="btn-tesla secondary"
            onClick={() => {
              setPaso('archivos');
              setError('');
            }}
            disabled={enviando}
          >
            Volver
          </button>
          <button
            type="button"
            className="btn-tesla primary"
            onClick={importar}
            disabled={enviando || (!sinVentas && nElegidos === 0)}
          >
            {enviando
              ? 'Importando…'
              : sinVentas
                ? 'Guardar resumen'
                : `Importar ${nElegidos} ${nElegidos === 1 ? 'vendedor' : 'vendedores'}`}
          </button>
        </div>
      </div>
    );
  } else {
    cuerpo = (
      <>
        {slots(true)}
        <Resultado carga={carga} />
      </>
    );
    pie = (
      <div className={styles.pie}>
        <span className={styles.subidoPor}>
          {`Subido por ${carga.usuario ?? '—'} · ${fechaHora(carga.created_at)}`}
        </span>
        <div className={styles.acciones}>
          <button type="button" className="btn-tesla secondary" onClick={reiniciar}>
            Subir otro
          </button>
          <button type="button" className="btn-tesla primary" onClick={verMetricas}>
            {soloVendedor ? `Ver métricas de ${soloVendedor.split(' ')[0]}` : 'Ver métricas'}
          </button>
        </div>
      </div>
    );
  }

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={cerrar}
      title="Subir PDF de ventas por fuera"
      subtitle="Reporte de GBP. El último PDF manda: reemplaza lo cargado de ese vendedor en su rango de fechas."
      size="lg"
      closeOnOverlay={false}
      closeOnEsc={false}
      className={styles.modal}
      bodyClassName={styles.cuerpo}
      footer={pie}
    >
      {cuerpo}
    </ModalTesla>
  );
}
