import { Field, Fields } from './PanelParts';
import styles from './panel.module.css';

/**
 * A publication's data, read-only: title, description, pictures and attributes. Shared by the product's copied data
 * (`ProductData`) and a publication's original and applied data (`DatosTab`).
 *
 * @param {object} props
 * @param {{ titulo: ?string, descripcion: ?string, fotos: object[], atributos: object[] }} props.datos
 */
export default function DataFields({ datos }) {
  return (
    <>
      <Fields>
        <Field label="Título">{datos.titulo}</Field>
      </Fields>
      <h4 className={styles.subTitle}>Descripción</h4>
      {datos.descripcion ? <p className={styles.description}>{datos.descripcion}</p> : <p className={styles.note}>Sin descripción.</p>}
      <h4 className={styles.subTitle}>Fotos</h4>
      {datos.fotos.length > 0 ? (
        <ul className={styles.pictures}>
          {datos.fotos.map((foto, index) => (
            <li key={foto.id ?? foto.url}>
              <img src={foto.url} alt={`Foto ${index + 1}`} className={styles.picture} loading="lazy" />
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.note}>Sin fotos.</p>
      )}
      <h4 className={styles.subTitle}>Atributos</h4>
      {datos.atributos.length > 0 ? (
        <Fields>
          {datos.atributos.map((atributo) => (
            <Field key={atributo.id} label={atributo.name ?? atributo.id}>
              {atributo.value_name}
            </Field>
          ))}
        </Fields>
      ) : (
        <p className={styles.note}>Sin atributos.</p>
      )}
    </>
  );
}
