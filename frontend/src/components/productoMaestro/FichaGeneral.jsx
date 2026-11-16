import { useId } from 'react';
import { GENERAL, TEXTOS, original, textoActual, valorGeneral } from './fichaEdits';
import { moneda, numero, pesos } from './formato';
import TnVinculo from './TnVinculo';
import m from './maestro.module.css';
import f from './Ficha.module.css';

const SECCIONES = [...new Set(GENERAL.map((def) => def.seccion))];

const ETIQUETA_FUENTE = { tn: 'Tienda Nube', gbp: 'GBP', nombre: 'Nombre' };

/** The sources of each description, in the approved mock's order. */
const ORDEN_DESCRIPCION = { descripcion_ml: ['ml', 'tn', 'gbp'], descripcion_web: ['tn', 'ml', 'gbp'] };

function notaTexto(clave, fuente, largo) {
  if (fuente === 'propio') return 'Texto propio: queda fijo aunque cambie la publicación o GBP';
  if (fuente === 'gbp') return 'Texto de GBP: se actualiza con la sincronización de GBP';
  if (fuente === 'tn') {
    if (!largo) return 'Nombre en Tienda Nube: sigue al de la tienda';
    return `Descripción de Tienda Nube: sigue a la de la tienda${clave === 'descripcion_ml' ? '; para ML se pasa de HTML a texto plano' : ''}`;
  }
  if (fuente === 'nombre') return 'Usa el nombre del producto';
  return 'Sigue a la publicación mientras no se edite';
}

/** The options of a brand / category / subcategory select: the active ones, plus the current one if inactive. */
function opciones(def, valor, { marcas, categorias, categoriaId }) {
  let lista = [];
  if (def.tipo === 'marca') lista = marcas;
  if (def.tipo === 'categoria') lista = categorias;
  if (def.tipo === 'subcategoria') lista = categorias.find((c) => String(c.id) === String(categoriaId))?.subcategorias ?? [];
  return lista.filter((x) => x.activa || String(x.id) === valor).map((x) => ({ id: String(x.id), nombre: x.nombre }));
}

function Campo({ def, maestro, edits, editable, onChange, onVolver, maestros }) {
  const id = useId();
  const valor = valorGeneral(maestro, edits, def);
  const dirty = def.key in edits.general && valor.trim() !== original(maestro, def);
  const select = ['marca', 'categoria', 'subcategoria'].includes(def.tipo);
  const disabled = def.gestionFull ? !maestro.can_edit_unidades : !editable;

  let tag;
  let tagCls;
  let gbp = null;
  if (def.gestionFull) {
    tag = valor ? 'Gestión Full' : 'Sin dato';
    tagCls = valor ? m.oTn : m.oNone;
  } else {
    const campo = maestro.campos[def.key] ?? {};
    const gbpValor = campo.gbp === null || campo.gbp === undefined ? '' : String(campo.gbp);
    const overrideado = dirty ? valor.trim() !== '' && valor.trim() !== gbpValor : campo.overrideado;
    tag = overrideado ? 'Overrideado' : gbpValor ? 'GBP' : 'Sin dato';
    tagCls = overrideado ? m.oOv : gbpValor ? m.oGbp : m.oNone;
    if (overrideado) gbp = (select ? campo.gbp_nombre : gbpValor) || 'sin dato';
  }

  const inpCls = [m.inp, def.unidad && m.inpUnit, dirty ? m.inpDirty : gbp !== null && m.inpOv, valor === '' && m.inpEmpty].filter(Boolean).join(' ');
  const opts = select ? opciones(def, valor, maestros) : [];

  return (
    <div className={def.ancho ? f.ancho : undefined}>
      <div className={f.campo}>
        <span className={f.campoHead}>
          <label htmlFor={id}>{def.etiqueta}</label>
          <span className={`${m.tag} ${tagCls}`}>{tag}</span>
        </span>
        <span className={m.inpWrap}>
          {select ? (
            <select id={id} className={inpCls} value={valor} disabled={disabled} onChange={(e) => onChange(def, e.target.value)}>
              {valor === '' && <option value="">Sin dato</option>}
              {!opts.some((o) => o.id === valor) && valor !== '' && (
                <option value={valor}>{maestro.campos[def.key]?.nombre ?? `#${valor}`}</option>
              )}
              {opts.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.nombre}
                </option>
              ))}
            </select>
          ) : (
            <input
              id={id}
              className={inpCls}
              value={valor}
              placeholder="Sin dato"
              inputMode={def.tipo === 'entero' ? 'numeric' : def.tipo ? 'decimal' : undefined}
              disabled={disabled}
              onChange={(e) => onChange(def, def.tipo === 'entero' ? e.target.value.replace(/[^0-9]/g, '') : e.target.value)}
            />
          )}
          {def.unidad && <span className={m.unit}>{def.unidad}</span>}
        </span>
      </div>
      {def.gestionFull && <p className={f.nota}>Mismo dato que Gestión Full · editar requiere Depósitos</p>}
      {gbp !== null && (
        <p className={f.gbp}>
          <span className={`${m.mono} ${f.gbpValor}`}>{`GBP: ${gbp}`}</span>
          {editable && (
            <button className={m.lnk} type="button" onClick={() => onVolver(def)}>
              Volver al valor de GBP
            </button>
          )}
        </p>
      )}
    </div>
  );
}

function Texto({ def, maestro, edits, editable, onTexto }) {
  const server = maestro.textos[def.clave] ?? { fuentes: {} };
  const { fuente, valor } = textoActual(maestro, edits, def.clave);
  const dirty = def.clave in edits.textos;
  // A source without text is not offered, except Tienda Nube on the descriptions: as in the mock it is always there,
  // in its fixed place, and empty until the TN sync brings the store's description.
  const orden = ORDEN_DESCRIPCION[def.clave] ?? Object.keys(server.fuentes ?? {});
  const fuentes = orden.filter((clave) => server.fuentes?.[clave] || (clave === 'tn' && def.clave in ORDEN_DESCRIPCION));
  const etiqueta = (clave) => (clave === 'ml' ? `Publicación ${maestro.mla_ganadora}` : ETIQUETA_FUENTE[clave]);
  const chips = [...fuentes, 'propio'];
  const inpCls = [m.inp, dirty && m.inpDirty, valor === '' && m.inpEmpty].filter(Boolean).join(' ');
  const props = {
    className: inpCls,
    'aria-label': def.etiqueta,
    placeholder: fuente === 'tn' && def.largo ? 'Sin descripción en Tienda Nube: llega con la sincronización de TN' : 'Sin texto',
    value: valor,
    disabled: !editable,
    onChange: (e) => onTexto(def.clave, { fuente: 'propio', texto: e.target.value }),
  };

  return (
    <div className={f.texto} data-texto={def.clave}>
      <div className={f.textoHead}>
        <span className={f.label}>{def.etiqueta}</span>
        <div className={f.chips}>
          <span className={f.tomar}>Tomar de</span>
          {chips.map((clave) => (
            <button
              key={clave}
              type="button"
              className={clave === fuente ? `${m.chip} ${m.chipOn}` : m.chip}
              aria-pressed={clave === fuente}
              disabled={!editable}
              onClick={() => onTexto(def.clave, clave === 'propio' ? { fuente: 'propio', texto: valor } : { fuente: clave })}
            >
              {clave === 'propio' ? 'Texto propio' : etiqueta(clave)}
            </button>
          ))}
        </div>
      </div>
      {def.largo ? <textarea {...props} /> : <input {...props} />}
      <p className={f.nota}>{notaTexto(def.clave, fuente, def.largo)}</p>
    </div>
  );
}

function Lectura({ lectura, tn }) {
  const filas = [
    ['Costo', moneda(lectura.moneda_costo, lectura.costo)],
    ['IVA', lectura.iva != null ? `${numero(lectura.iva)} %` : '—'],
    ['Stock', numero(lectura.stock)],
    ['Precio lista ML', pesos(lectura.precio_lista_ml)],
    ['Proveedor', lectura.proveedor || '—'],
    ['Publicaciones ML', `${numero(lectura.publicaciones_ml ?? 0)} vinculadas`],
    ['Tienda Nube', tn?.published ? 'Publicado' : 'No publicado'],
  ];
  return (
    <fieldset className={f.seccion} aria-label="Precio, stock y canales · solo lectura">
      <legend className={f.legend}>
        Precio, stock y canales <span className={f.legendNota}>· solo lectura</span>
      </legend>
      <dl className={f.lectura}>
        {filas.map(([etiqueta, valor]) => (
          <div key={etiqueta} className={f.lecturaItem}>
            <dt>{etiqueta}</dt>
            <dd className={m.mono}>{valor}</dd>
          </div>
        ))}
      </dl>
    </fieldset>
  );
}

/**
 * The ficha's General tab (the approved mock): Identidad and Logística y garantía over GBP, the Tienda Nube link,
 * titles and descriptions with their sources, and the read-only prices, stock and channels.
 */
export default function FichaGeneral({ maestro, edits, maestros, vinculo, onCampo, onVolver, onTexto, onVinculo }) {
  const editable = maestro.can_edit;
  const categoriaId = valorGeneral(maestro, edits, GENERAL.find((d) => d.key === 'categoria_id'));
  return (
    <div className={f.cuerpo}>
      {SECCIONES.map((seccion) => (
        <fieldset key={seccion} className={f.seccion}>
          <legend className={f.legend}>{seccion}</legend>
          <div className={f.grilla}>
            {GENERAL.filter((def) => def.seccion === seccion).map((def) => (
              <Campo
                key={def.key}
                def={def}
                maestro={maestro}
                edits={edits}
                editable={editable}
                onChange={onCampo}
                onVolver={onVolver}
                maestros={{ ...maestros, categoriaId }}
              />
            ))}
          </div>
        </fieldset>
      ))}

      <fieldset className={f.seccion}>
        <legend className={f.legend}>Tienda Nube</legend>
        <TnVinculo itemId={maestro.item_id} vinculo={vinculo} onVinculo={onVinculo} />
      </fieldset>

      <fieldset className={`${f.seccion} ${f.seccionTextos}`}>
        <legend className={f.legend}>Títulos y descripciones</legend>
        {TEXTOS.map((def) => (
          <Texto key={def.clave} def={def} maestro={maestro} edits={edits} editable={editable} onTexto={onTexto} />
        ))}
      </fieldset>

      <Lectura lectura={maestro.lectura} tn={vinculo?.tn} />
    </div>
  );
}
