import styles from './cells.module.css';

/** The official store's name; an id the backend has no label for still shows as `Tienda <id>`. */
export default function StoreCell({ item }) {
  if (item.store_label) return <span>{item.store_label}</span>;
  if (item.official_store_id != null) return <span>{`Tienda ${item.official_store_id}`}</span>;
  return <span className={styles.empty}>—</span>;
}
