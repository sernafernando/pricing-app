import { mlItemOverridesAPI } from '../../../services/api';
import DataForm from './DataForm';

const fotoIds = (fotos) => fotos.map((foto) => foto.id);
const atributoValues = (atributos) => atributos.map((atributo) => ({ id: atributo.id, value_name: atributo.value_name ?? '' }));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** Whether the form's pictures or attributes differ from ML's: only then does the save carry them. */
function changed(field, form, original) {
  return field === 'fotos'
    ? !same(fotoIds(form.fotos), fotoIds(original.fotos))
    : !same(atributoValues(form.atributos), atributoValues(original.atributos));
}

/**
 * The override body for `form` (`PUT /ml-item-overrides/{mla}`): each field the same as ML's `original` is null (it
 * follows ML), any other is overridden whole. A cleared description overrides with none; every field back to ML's
 * drops the override.
 */
function overrideBody(form, original) {
  return {
    titulo: form.titulo === (original.titulo ?? '') ? null : form.titulo,
    descripcion: form.descripcion.trim() === (original.descripcion ?? '').trim() ? null : form.descripcion.trim() ? form.descripcion : '',
    fotos: changed('fotos', form, original) ? fotoIds(form.fotos) : null,
    atributos: changed('atributos', form, original) ? atributoValues(form.atributos) : null,
  };
}

/**
 * Edit a publication's data as a local override, never on Mercado Libre (T8b). Starts from the data that applies;
 * only what differs from ML's original is kept, and "Volver al original" takes ML's data back. Pictures and
 * attributes can be removed, reordered and (attributes) changed, not added: the server only takes the publication's own.
 *
 * @param {object} props
 * @param {string} props.itemId The MLA.
 * @param {object} props.aplicado The data that applies now (the override, else ML's).
 * @param {object} props.original ML's data.
 * @param {(read: object) => void} props.onSaved Receives the publication's data as the server answered the save.
 * @param {() => void} props.onCancel
 */
export default function PublicationDataForm({ itemId, aplicado, original, onSaved, onCancel }) {
  return (
    <DataForm
      datos={aplicado}
      original={original}
      submit={(form) => mlItemOverridesAPI.save(itemId, overrideBody(form, original))}
      forbidden="No tenés permiso para editar los datos de la publicación."
      sends={(field, form) => changed(field, form, original)}
      onSaved={onSaved}
      onCancel={onCancel}
    />
  );
}
