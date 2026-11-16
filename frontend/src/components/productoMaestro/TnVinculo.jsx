import { useEffect, useState } from 'react';
import { Search } from 'lucide-react';
import { productoTnVinculosAPI } from '../../services/api';
import { useDebounce } from '../../hooks/useDebounce';
import { apiErrorMessage } from '../../utils/apiErrorMessage';
import { pesos } from './formato';
import m from './maestro.module.css';
import f from './Ficha.module.css';

const MOTIVO = { ean: 'Mismo EAN', nombre: 'Nombre parecido' };

const sku = (tn) => tn.skus?.[0] ?? 'sin SKU';

function Buscador({ itemId, onElegir, onCerrar }) {
  const [q, setQ] = useState('');
  const [estado, setEstado] = useState({ items: [], loading: true, error: null });
  const qDebounced = useDebounce(q.trim(), 300);

  useEffect(() => {
    let vigente = true;
    setEstado((prev) => ({ ...prev, loading: true, error: null }));
    productoTnVinculosAPI
      .candidatos(itemId, qDebounced || undefined)
      .then(({ data }) => vigente && setEstado({ items: data, loading: false, error: null }))
      .catch(() => vigente && setEstado({ items: [], loading: false, error: 'No se pudo buscar en Tienda Nube' }));
    return () => {
      vigente = false;
    };
  }, [itemId, qDebounced]);

  const titulo = qDebounced ? 'Resultados' : estado.items.length ? 'Sugeridos por EAN o nombre' : 'Sin sugerencias: buscá por nombre o SKU';

  return (
    <div className={f.tnBuscar}>
      <label className={m.inpWrap}>
        <span className={m.searchIcon} aria-hidden="true">
          <Search size={16} strokeWidth={1.5} />
        </span>
        <input
          className={`${m.inp} ${m.inpSearch}`}
          type="search"
          placeholder="Buscar en Tienda Nube por nombre o SKU"
          aria-label="Buscar producto de Tienda Nube"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </label>
      <p className={f.tnTitulo}>{estado.loading ? 'Buscando…' : titulo}</p>
      {estado.error && (
        <p className={m.feedback} role="alert">
          {estado.error}
        </p>
      )}
      {estado.items.map((tn) => (
        <div key={tn.tn_product_id} className={f.tnResultado}>
          <span className={f.tnTextos}>
            <span className={f.tnNombre}>{tn.nombre ?? `Producto ${tn.tn_product_id}`}</span>
            <span className={`${m.mono} ${f.tnMeta}`}>
              {`producto ${tn.tn_product_id} · SKU ${sku(tn)} · ${tn.item_id ? `vinculado a item ${tn.item_id}` : 'sin vincular'}`}
            </span>
          </span>
          {MOTIVO[tn.motivo] ? <span className={`${m.tag} ${m.oTn}`}>{MOTIVO[tn.motivo]}</span> : <span />}
          <button className={`${m.btn} ${m.btnSecondary} ${m.btnSmall}`} type="button" onClick={() => onElegir(tn.tn_product_id)}>
            Vincular
          </button>
        </div>
      ))}
      <div>
        <button className={m.lnk} type="button" onClick={onCerrar}>
          Cancelar
        </button>
      </div>
    </div>
  );
}

/**
 * The product's Tienda Nube product (S12): the link the sync made by SKU or the one set by hand, "Cambiar" (search
 * with suggestions by EAN and name) and "Desvincular". A link changes at once: it is not part of "Guardar".
 *
 * @param {object} props
 * @param {number} props.itemId
 * @param {object | null} props.vinculo The read of `GET /producto-tn-vinculos/{item_id}`; `sinLectura` when it failed.
 * @param {(vinculo: object) => void} props.onVinculo Receives the link as the server answered the change.
 */
export default function TnVinculo({ itemId, vinculo, onVinculo }) {
  const [buscando, setBuscando] = useState(false);
  const [error, setError] = useState(null);

  if (!vinculo) return <p className={f.nota}>Cargando el vínculo con Tienda Nube…</p>;
  if (vinculo.sinLectura) return <p className={f.nota}>No se pudo leer el vínculo con Tienda Nube</p>;

  const editable = vinculo.can_edit;
  const tn = vinculo.tn;

  const guardar = async (tnProductId) => {
    setError(null);
    try {
      const { data } = await productoTnVinculosAPI.vincular(itemId, tnProductId);
      setBuscando(false);
      onVinculo(data);
    } catch (err) {
      setError(apiErrorMessage(err, 'No se pudo cambiar el vínculo. Probá de nuevo.'));
    }
  };

  return (
    <>
      {buscando ? (
        <Buscador itemId={itemId} onElegir={guardar} onCerrar={() => setBuscando(false)} />
      ) : tn ? (
        <div className={f.tnCaja}>
          <div className={f.tnTextos}>
            <span className={f.tnNombreFuerte}>{tn.nombre ?? `Producto ${tn.tn_product_id}`}</span>
            <span className={`${m.mono} ${f.tnMeta}`}>
              {`producto ${tn.tn_product_id} · SKU ${sku(tn)} · ${pesos(tn.precio)} · ${tn.published ? 'publicado' : 'oculto'}`}
            </span>
          </div>
          <div className={f.tnAcciones}>
            <span className={`${m.tag} ${vinculo.origen === 'manual' ? m.oManual : m.oGbp}`}>
              {vinculo.origen === 'manual' ? 'Manual' : 'Automático por SKU'}
            </span>
            {editable && (
              <>
                <button className={m.lnk} type="button" onClick={() => setBuscando(true)}>
                  Cambiar
                </button>
                <button className={m.lnk} type="button" onClick={() => guardar(null)}>
                  Desvincular
                </button>
              </>
            )}
          </div>
        </div>
      ) : (
        <div className={f.tnCaja}>
          <span className={f.tnVacio}>Sin producto de Tienda Nube vinculado</span>
          {editable && (
            <button className={m.lnk} type="button" onClick={() => setBuscando(true)}>
              Vincular
            </button>
          )}
        </div>
      )}
      {error && (
        <p className={m.feedback} role="alert">
          {error}
        </p>
      )}
      <p className={f.nota}>Un vínculo manual no lo cambia la sincronización de TN</p>
    </>
  );
}
