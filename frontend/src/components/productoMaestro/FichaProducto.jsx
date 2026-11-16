import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import {
  productoCategoriasAPI,
  productoMaestroAPI,
  productoMarcasAPI,
  productoSpecsAPI,
  productoTnVinculosAPI,
} from '../../services/api';
import { apiErrorMessage } from '../../utils/apiErrorMessage';
import { EDITS_VACIOS, bodySpecs, completos, contarCambios, patchMaestro } from './fichaEdits';
import FichaGeneral from './FichaGeneral';
import FichaSpecs from './FichaSpecs';
import m from './maestro.module.css';
import f from './Ficha.module.css';

function Leyenda({ items }) {
  return (
    <div className={f.leyenda}>
      {items.map(([tag, cls, texto]) => (
        <span key={tag} className={f.leyendaItem}>
          <span className={`${m.tag} ${cls}`}>{tag}</span>
          {texto}
        </span>
      ))}
    </div>
  );
}

const LEYENDA_GENERAL = [
  ['GBP', m.oGbp, 'viene de GBP'],
  ['Overrideado', m.oOv, 'distinto de GBP'],
];

const LEYENDA_SPECS = [
  ['ML', m.oMl, 'publicación ganadora'],
  ['ERP', m.oGbp, 'nombre'],
  ['Combo', m.oTn, 'componentes'],
  ['Manual', m.oManual, 'a mano'],
];

function meta(maestro, vinculo) {
  const { campos, lectura } = maestro;
  const cat = campos.categoria_id?.nombre;
  const sub = campos.subcategoria_id?.nombre;
  const partes = [`item ${maestro.item_id}`];
  if (cat) partes.push(sub ? `${cat} / ${sub}` : cat);
  if (campos.marca_id?.nombre) partes.push(campos.marca_id.nombre);
  partes.push(`${lectura.publicaciones_ml ?? 0} MLA`);
  if (vinculo?.tn) partes.push('Tienda Nube');
  return partes.join(' · ');
}

/**
 * One product of the master (abm-productos S9-S13, the approved mock's right card): the General tab (GBP data with
 * overrides, units per box, Tienda Nube link, texts, read-only data) and, for notebooks and PCs, "Specs técnicas".
 * One "Guardar" sends the general changes (`PATCH .../maestro`) and the specs changes (`PUT /producto-specs`), only
 * what changed. Used by the "ABM de productos" page and by the Publicaciones ML product panel. Mount with
 * `key={itemId}`.
 *
 * @param {object} props
 * @param {number} props.itemId
 * @param {() => void} [props.onSaved] Called after a save, so a list can show the new name or completeness.
 */
export default function FichaProducto({ itemId, onSaved }) {
  const [maestro, setMaestro] = useState(null);
  const [specs, setSpecs] = useState(null);
  const [info, setInfo] = useState({});
  const [vinculo, setVinculo] = useState(null);
  const [maestros, setMaestros] = useState({ marcas: [], categorias: [] });
  const [error, setError] = useState(null);
  const [cargaError, setCargaError] = useState(null);
  const [edits, setEdits] = useState(EDITS_VACIOS);
  const [vista, setVista] = useState('general');
  const [enviando, setEnviando] = useState(false);

  useEffect(() => {
    let vigente = true;
    productoMaestroAPI
      .leer(itemId)
      .then(({ data }) => {
        if (!vigente) return;
        setMaestro(data);
        if (!data.tipo_specs) return;
        productoSpecsAPI
          .leer(itemId)
          .then((r) => vigente && setSpecs(r.data))
          .catch(() => vigente && setError('No se pudieron cargar las specs'));
        productoSpecsAPI
          .campos()
          .then((r) => vigente && setInfo(Object.fromEntries(r.data.map((c) => [c.nombre, c]))))
          .catch(() => {});
      })
      .catch((err) => vigente && setCargaError(err?.response?.status === 404 ? 'El producto no existe en el ERP' : 'No se pudo cargar el producto. Probá de nuevo.'));
    productoTnVinculosAPI
      .leer(itemId)
      .then(({ data }) => vigente && setVinculo(data))
      .catch(() => vigente && setVinculo({ item_id: itemId, origen: null, tn: null, can_edit: false }));
    Promise.all([productoMarcasAPI.listar(), productoCategoriasAPI.listar()])
      .then(([marcas, categorias]) => vigente && setMaestros({ marcas: marcas.data, categorias: categorias.data }))
      .catch(() => {});
    return () => {
      vigente = false;
    };
  }, [itemId]);

  if (cargaError) {
    return (
      <p className={m.feedback} role="alert">
        {cargaError}
      </p>
    );
  }
  if (!maestro) return <p className={f.cargando}>Cargando el producto…</p>;

  const enSpecs = vista === 'specs' && specs != null;
  const cambios = contarCambios(maestro, specs, edits);
  const editable = maestro.can_edit || maestro.can_edit_unidades || specs?.can_edit;
  const nombre = edits.general.nombre?.trim() || maestro.campos.nombre?.valor || `Producto ${itemId}`;
  const sinSpecsEdits = !Object.keys(edits.specs).length && !Object.keys(edits.noAplica).length;
  const specsListos = specs ? (sinSpecsEdits ? specs.completos : completos(specs.campos, edits)) : null;

  const setGeneral = (def, value) => {
    const general = { ...edits.general, [def.key]: value };
    // A subcategory belongs to one category: a new category starts on its first active subcategory.
    if (def.key === 'categoria_id') {
      const subs = maestros.categorias.find((c) => String(c.id) === value)?.subcategorias?.filter((s) => s.activa) ?? [];
      const subActual = general.subcategoria_id ?? String(maestro.campos.subcategoria_id?.valor ?? '');
      if (!subs.some((s) => String(s.id) === subActual)) general.subcategoria_id = subs[0] ? String(subs[0].id) : '';
    }
    setEdits({ ...edits, general });
  };

  const volver = async (def) => {
    const general = { ...edits.general };
    delete general[def.key];
    setEdits({ ...edits, general });
    if (!maestro.campos[def.key]?.overrideado) return;
    setError(null);
    try {
      const { data } = await productoMaestroAPI.guardar(itemId, { [def.key]: null });
      setMaestro(data);
      onSaved?.();
    } catch (err) {
      setError(apiErrorMessage(err, 'No se pudo volver al valor de GBP. Probá de nuevo.'));
    }
  };

  const guardar = async () => {
    if (enviando) return;
    setEnviando(true);
    setError(null);
    try {
      const patch = patchMaestro(maestro, edits);
      const body = specs ? bodySpecs(specs.campos, edits) : null;
      if (patch) setMaestro((await productoMaestroAPI.guardar(itemId, patch)).data);
      if (body) setSpecs((await productoSpecsAPI.guardar(itemId, body)).data);
      setEdits(EDITS_VACIOS);
      onSaved?.();
    } catch (err) {
      setError(apiErrorMessage(err, 'No se pudo guardar. Probá de nuevo.'));
    } finally {
      setEnviando(false);
    }
  };

  const precargar = async () => {
    setError(null);
    try {
      setSpecs((await productoSpecsAPI.precargar(itemId)).data);
      onSaved?.();
    } catch (err) {
      setError(apiErrorMessage(err, 'No se pudo precargar. Probá de nuevo.'));
    }
  };

  return (
    <>
      <div className={f.cabecera}>
        <div className={f.cabeceraFila}>
          <div className={f.titulo}>
            <h2 className={f.nombre}>{nombre}</h2>
            <p className={`${m.mono} ${f.meta}`}>{meta(maestro, vinculo)}</p>
          </div>
          <div className={f.acciones}>
            {enSpecs && specs.can_edit && (
              <button className={`${m.btn} ${m.btnSecondary}`} type="button" onClick={precargar}>
                <RefreshCw size={16} strokeWidth={1.5} aria-hidden="true" />
                Precargar de nuevo
              </button>
            )}
            {editable && (
              <button className={`${m.btn} ${m.btnPrimary}`} type="button" disabled={cambios === 0 || enviando} onClick={guardar}>
                {cambios === 0 ? 'Guardar' : `Guardar ${cambios} ${cambios === 1 ? 'cambio' : 'cambios'}`}
              </button>
            )}
          </div>
        </div>
        <div className={f.cabeceraFila}>
          <div role="tablist" aria-label="Secciones de la ficha" className={m.tablist}>
            <button type="button" role="tab" aria-selected={!enSpecs} className={!enSpecs ? `${m.tab} ${m.tabOn}` : m.tab} onClick={() => setVista('general')}>
              General
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={enSpecs}
              disabled={!maestro.tipo_specs || !specs}
              className={enSpecs ? `${m.tab} ${m.tabOn}` : m.tab}
              onClick={() => setVista('specs')}
            >
              Specs técnicas {specs && <span className={m.tabCount}>{`${specsListos} / ${specs.total}`}</span>}
            </button>
          </div>
          <Leyenda items={enSpecs ? LEYENDA_SPECS : LEYENDA_GENERAL} />
        </div>
        {error && (
          <p className={m.feedback} role="alert">
            {error}
          </p>
        )}
      </div>

      {enSpecs ? (
        <FichaSpecs
          specs={specs}
          info={info}
          edits={edits}
          onValor={(campo, value) => setEdits({ ...edits, specs: { ...edits.specs, [campo]: value } })}
          onNoAplica={(campo, value) => setEdits({ ...edits, noAplica: { ...edits.noAplica, [campo]: value } })}
        />
      ) : (
        <FichaGeneral
          maestro={maestro}
          edits={edits}
          maestros={maestros}
          vinculo={vinculo}
          onCampo={setGeneral}
          onVolver={volver}
          onTexto={(clave, edit) => setEdits({ ...edits, textos: { ...edits.textos, [clave]: edit } })}
          onVinculo={setVinculo}
        />
      )}
    </>
  );
}
