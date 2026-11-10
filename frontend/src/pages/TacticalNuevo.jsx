/**
 * TacticalNuevo — the "Nuevo tactical" screen (tactical T2), built from the owner-approved OpenDesign screens
 * handoffs/diseno-tactical/nuevo-tactical-aprobado.html (sell out) and nuevo-tactical-sell-in-aprobado.html (sell in).
 *
 * The tactical's data (type, name, brand, validity, currency, conditions) and all its lines are created in one step
 * with `POST /tacticals`. `?tipo=sell_in|sell_out` picks the type it opens on; a type the user cannot manage is off.
 * `?renovar=<id>` (Renovar, tacticals F1) opens it prefilled from that tactical (`renovacionDe`), dates empty: saving
 * creates a NEW tactical and leaves the old one as it is.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { usePermisos } from '../contexts/PermisosContext';
import { productosAPI } from '../services/api';
import { tacticalsAPI } from '../services/tacticalsAPI';
import { apiErrorMessage } from '../utils/apiErrorMessage';
import TacticalDatos from '../components/tactical/TacticalDatos';
import TacticalDescartar from '../components/tactical/TacticalDescartar';
import TacticalLinea from '../components/tactical/TacticalLinea';
import {
  conLineaDeLaPantalla,
  copiarLinea,
  cuerpoDe,
  dinero,
  lineasPara,
  maximoTotal,
  nuevaLinea,
  numeroDe,
  problemaDe,
  unidadesDelTope,
} from '../components/tactical/tacticalLineas';
import { ALCANCE_INICIAL, ALCANCE_POR_TIENDA, contadoresDelTope } from '../components/tactical/tacticalTiendas';
import { renovacionDe } from '../components/tactical/tacticalRenovar';
import { useTiendasOficiales } from '../hooks/useTiendasOficiales';
import styles from './TacticalNuevo.module.css';

const TIPOS = {
  sell_in: {
    label: 'Sell in',
    permiso: 'sell_in.gestionar',
    moneda: 'ARS',
    subtitulo: 'Baja el costo de lo que vendés en el rango. Cargá el tactical y sus líneas en un solo paso.',
    hint: 'Cada línea es un producto, varios productos, una marca, una categoría o una factura, con su monto y sus topes. Los topes cortan en lo que pase primero.',
    volver: '/sell-in?tab=tacticals',
  },
  sell_out: {
    label: 'Sell out',
    permiso: 'sell_out.gestionar',
    moneda: 'USD',
    subtitulo: 'La marca te paga por cada unidad vendida en el rango. Cargá el tactical y sus líneas en un solo paso.',
    hint: 'Cada línea es un producto, varios productos, una marca o una categoría, con su monto y sus topes. Los topes cortan en lo que pase primero.',
    volver: '/sell-in?tab=tacticals',
  },
};

const ddmm = (iso) => (iso ? iso.split('-').reverse().slice(0, 2).join('/') : '—');
const plural = (n, uno, varios) => (n === 1 ? uno : varios);

function tipoInicial(pedido, puede) {
  if (puede(pedido)) return pedido;
  return ['sell_in', 'sell_out'].find(puede) ?? pedido;
}

/** Products a line names, as the sell out summary counts them: a shared line counts its products once each too. */
const productosDe = (linea) => (linea.alcance === 'productos' ? linea.productos.length : 0);

function Resumen({ tipo, form, lineas, contadores = 1 }) {
  const n = lineas.length;
  if (tipo === 'sell_in') {
    return (
      <>
        <span>
          <b>{n}</b> {plural(n, 'línea', 'líneas')}
        </span>
        <span className={styles.dot}>·</span>
        <span>
          Marca <b>{form.marca || '—'}</b>
        </span>
        <span className={styles.dot}>·</span>
        <span className={styles.big}>
          <b>{ddmm(form.fechaDesde)}</b> al <b>{ddmm(form.fechaHasta)}</b>
        </span>
      </>
    );
  }
  const productos = lineas.reduce((a, l) => a + productosDe(l), 0);
  const unidades = lineas.reduce((a, l) => a + unidadesDelTope(l), 0) * contadores;
  const maximo = maximoTotal(lineas, contadores);
  return (
    <>
      <span>
        <b>{n}</b> {plural(n, 'línea', 'líneas')}
      </span>
      <span className={styles.dot}>·</span>
      <span>
        <b>{productos}</b> {plural(productos, 'producto', 'productos')}
      </span>
      <span className={styles.dot}>·</span>
      <span>
        Tope total <b>{unidades.toLocaleString('es-AR')}</b> unidades
      </span>
      <span className={styles.dot}>·</span>
      <span className={styles.big}>
        Máximo a cobrar <b>{dinero(form.moneda, maximo)}</b>
        {contadores > 1 && ` (${contadores} topes, uno por tienda o canal)`}
      </span>
    </>
  );
}

export default function TacticalNuevo() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { tienePermiso } = usePermisos();
  const puede = (tipo) => tienePermiso(TIPOS[tipo].permiso);
  const pedido = params.get('tipo') === 'sell_in' ? 'sell_in' : 'sell_out';

  const [form, setForm] = useState(() => {
    const tipo = tipoInicial(pedido, puede);
    return {
      tipo,
      nombre: '',
      marca: '',
      referencia: '',
      fechaDesde: '',
      fechaHasta: '',
      moneda: TIPOS[tipo].moneda,
      tcModo: 'al_cobro',
      tipoCambio: '',
      incluyeIva: false,
      acumulable: true,
      ...ALCANCE_INICIAL,
      nota: '',
    };
  });
  const [lineas, setLineas] = useState(() => [nuevaLinea()]);
  const [abierta, setAbierta] = useState(null);
  const [marcas, setMarcas] = useState([]);
  const [categorias, setCategorias] = useState([]);
  const [error, setError] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const [descartar, setDescartar] = useState(false);
  const { grupos: gruposTiendas, activas: tiendasOficialesActivas, loaded: tiendasCargadas } = useTiendasOficiales();
  const ejemploTope = lineas.map((l) => numeroDe(l.topeUnidades)).find((n) => n != null && n > 0) ?? null;
  // Stores apply only to sell out (owner, 2026-11-10): a sell in tactical lowers the cost of every sale.
  const alcancePorTienda = ALCANCE_POR_TIENDA && form.tipo === 'sell_out';
  const contadores = contadoresDelTope({
    alcancePorTienda,
    todasTiendas: form.todasTiendas !== false,
    seleccionKeys: form.tiendaKeys ?? [],
    grupos: gruposTiendas,
    tiendasActivas: tiendasOficialesActivas.length,
    topeCompartido: Boolean(form.topeCompartido),
  });

  const renovar = params.get('renovar');
  // Renovar draws no form until the tactical arrives: what the user typed meanwhile would be overwritten.
  const [cargando, setCargando] = useState(Boolean(renovar));
  const [aRenovar, setARenovar] = useState(null);
  // The tactical is read once; its stores map to the picker's groups once those arrive too.
  useEffect(() => {
    if (!renovar) return undefined;
    let activo = true;
    tacticalsAPI
      .detalle(renovar)
      .then(({ data }) => activo && setARenovar(data))
      .catch(() => {
        if (!activo) return;
        setError('No se pudo cargar el tactical a renovar.');
        setCargando(false);
      });
    return () => {
      activo = false;
    };
  }, [renovar]);
  useEffect(() => {
    if (!aRenovar || !tiendasCargadas) return;
    const renovado = renovacionDe(aRenovar, gruposTiendas);
    setForm(renovado.form);
    setLineas(renovado.lineas.length ? renovado.lineas : [nuevaLinea(renovado.form.marca)]);
    setARenovar(null);
    setCargando(false);
  }, [aRenovar, tiendasCargadas, gruposTiendas]);
  useEffect(() => {
    let activo = true;
    productosAPI
      .marcas()
      .then(({ data }) => activo && setMarcas(data?.marcas ?? []))
      .catch(() => activo && setMarcas([]));
    productosAPI
      .categorias()
      .then(({ data }) => activo && setCategorias(data?.categorias ?? []))
      .catch(() => activo && setCategorias([]));
    return () => {
      activo = false;
    };
  }, []);

  const tipo = TIPOS[form.tipo];
  const marcasDelSelect = useMemo(() => marcas.map((m) => (typeof m === 'string' ? m : m.marca ?? m.nombre)), [marcas]);

  const cambiarTipo = (nuevo) => {
    setAbierta(null);
    setForm((f) => ({ ...f, tipo: nuevo, moneda: TIPOS[nuevo].moneda }));
    setLineas((ls) => lineasPara(nuevo, ls));
  };

  const cambiarLinea = (linea) => setLineas((ls) => ls.map((l) => (l.id === linea.id ? linea : l)));
  const duplicar = (index) =>
    setLineas((ls) => [...ls.slice(0, index + 1), copiarLinea(ls[index]), ...ls.slice(index + 1)]);
  const eliminar = (id) => {
    if (abierta === id) setAbierta(null);
    setLineas((ls) => ls.filter((l) => l.id !== id));
  };
  const agregarLinea = () => {
    const linea = nuevaLinea(form.marca);
    setLineas((ls) => [...ls, linea]);
    setAbierta(linea.id);
  };

  const crear = async () => {
    const problema = problemaDe(form, lineas);
    if (problema) {
      setError(problema);
      return;
    }
    const { body, origen } = cuerpoDe(form, lineas, gruposTiendas, alcancePorTienda);
    setError(null);
    setEnviando(true);
    try {
      await tacticalsAPI.crear(body);
      const aviso =
        form.tipo === 'sell_in'
          ? `Tactical creado: ${body.nombre} · ${lineas.length} ${plural(lineas.length, 'línea', 'líneas')} · baja el costo del ${ddmm(form.fechaDesde)} al ${ddmm(form.fechaHasta)}.`
          : `Tactical creado: ${body.nombre} · ${lineas.length} ${plural(lineas.length, 'línea', 'líneas')} · máximo a cobrar ${dinero(form.moneda, maximoTotal(lineas, contadores))}.`;
      navigate(tipo.volver, { state: { aviso } });
    } catch (err) {
      setError(conLineaDeLaPantalla(apiErrorMessage(err, 'No se pudo crear el tactical.'), origen));
      setEnviando(false);
    }
  };

  if (!puede('sell_in') && !puede('sell_out')) {
    return (
      <div className={styles.shell}>
        <header className={styles.pageHead}>
          <h1>Nuevo tactical</h1>
        </header>
        <div className={styles.error} role="alert">
          No tenés permiso para crear tacticals.
        </div>
      </div>
    );
  }

  const botonCrear = (
    <button type="button" className={styles.primary} onClick={crear} disabled={enviando || cargando}>
      {enviando ? 'Creando…' : 'Crear tactical'}
    </button>
  );

  return (
    <div className={styles.shell}>
      <header className={styles.pageHead}>
        <div>
          <h1>Nuevo tactical</h1>
          <p>{tipo.subtitulo}</p>
        </div>
        <div className={styles.headActions}>
          <button type="button" className={styles.ghost} onClick={() => setDescartar(true)}>
            Cancelar
          </button>
          {botonCrear}
        </div>
      </header>

      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}

      {cargando ? (
        <div className={styles.cargando} role="status">
          Cargando el tactical a renovar…
        </div>
      ) : (
        <>
          <TacticalDatos
            form={form}
            onChange={(cambios) => setForm((f) => ({ ...f, ...cambios }))}
            onTipo={cambiarTipo}
            tiposNoDisponibles={Object.keys(TIPOS).filter((t) => !puede(t))}
            marcas={marcasDelSelect}
            gruposTiendas={gruposTiendas}
            tiendasActivas={tiendasOficialesActivas.length}
            ejemploTope={ejemploTope}
            alcancePorTienda={alcancePorTienda}
          />

          <section className={styles.card} aria-labelledby="tactical-lineas">
            <div className={styles.cardHead}>
              <h2 id="tactical-lineas">Líneas</h2>
              <p className={styles.hint}>{tipo.hint}</p>
            </div>
            <div className={styles.linesScroll}>
              <div className={`${styles.tbl} ${form.tipo === 'sell_in' ? styles.tblSellin : ''}`}>
                <div className={styles.tblHead} aria-hidden="true">
                  <div>#</div>
                  <div>Alcance</div>
                  <div>Qué incluye</div>
                  <div className={styles.num}>Monto</div>
                  <div className={styles.num}>Tope unidades</div>
                  <div className={styles.num}>{`Tope monto (${form.moneda})`}</div>
                  <div>Tope</div>
                  <div className={styles.num}>Máximo a cobrar</div>
                  <div />
                </div>
                {lineas.map((linea, index) => (
                  <TacticalLinea
                    key={linea.id}
                    linea={linea}
                    n={index + 1}
                    tipo={form.tipo}
                    moneda={form.moneda}
                    tcModo={form.tcModo}
                    marcas={marcasDelSelect}
                    categorias={categorias}
                    abierto={abierta === linea.id}
                    onAbrir={() => setAbierta(linea.id)}
                    onCerrar={() => setAbierta(null)}
                    onCambiar={cambiarLinea}
                    onDuplicar={() => duplicar(index)}
                    onEliminar={() => eliminar(linea.id)}
                    contadores={contadores}
                  />
                ))}
                <div className={styles.tblFoot}>
                  <button type="button" className={styles.addLine} onClick={agregarLinea}>
                    + Agregar línea
                  </button>
                </div>
              </div>
            </div>
          </section>

          <div className={styles.stickybar} data-testid="tactical-stickybar">
            <div className={styles.stickybarIn}>
              <div className={styles.summary} aria-live="polite">
                <Resumen tipo={form.tipo} form={form} lineas={lineas} contadores={contadores} />
              </div>
              {botonCrear}
            </div>
          </div>
        </>
      )}

      {descartar && <TacticalDescartar onSeguir={() => setDescartar(false)} onDescartar={() => navigate(tipo.volver)} />}
    </div>
  );
}
