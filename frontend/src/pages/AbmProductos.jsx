import { useState } from 'react';
import { registrarPagina } from '../registry/tabRegistry';
import MaestroLista from '../components/productoMaestro/MaestroLista';
import FichaProducto from '../components/productoMaestro/FichaProducto';
import m from '../components/productoMaestro/maestro.module.css';
import styles from './AbmProductos.module.css';

registrarPagina({
  pagePath: '/abm-productos',
  pageLabel: 'Productos - ABM de productos',
  tabs: [],
});

/**
 * "ABM de productos" (abm-productos T8, the approved mock): the product master. On the left every ERP product
 * ordered by stock, on the right the ficha of the selected one. What is edited here stays in our own master; GBP is
 * never written.
 */
export default function AbmProductos() {
  const [seleccion, setSeleccion] = useState(null);
  const [recarga, setRecarga] = useState(0);

  return (
    <div className={styles.page}>
      <div className={styles.contenido}>
        <header className={styles.header}>
          <div className={styles.titulos}>
            <p className={styles.eyebrow}>Productos</p>
            <h1 className={styles.h1}>ABM de productos</h1>
          </div>
          <div className={styles.headerDerecha}>
            <p className={styles.headerNota}>
              Lo que se edita acá queda en el maestro propio. GBP no se modifica: cada override muestra al lado el valor de GBP
            </p>
          </div>
        </header>

        <div className={styles.columnas}>
          <MaestroLista
            selectedId={seleccion}
            onSelect={setSeleccion}
            onFirst={(id) => setSeleccion((actual) => actual ?? id)}
            reloadKey={recarga}
          />
          <section aria-label="Ficha" className={`${m.card} ${styles.ficha}`}>
            {seleccion != null ? (
              <FichaProducto key={seleccion} itemId={seleccion} onSaved={() => setRecarga((n) => n + 1)} />
            ) : (
              <p className={styles.vacio}>Elegí un producto de la lista</p>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
