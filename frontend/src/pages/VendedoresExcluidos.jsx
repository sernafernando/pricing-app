/**
 * Vendedores excluidos — /dashboard-ventas-fuera/vendedores-excluidos (ODD `vpf-metricas-canal-fe` S4).
 *
 * The excluded-salespeople admin that was the Admin tab of the old Ventas por fuera dashboard, kept on its own
 * route when that dashboard became /metricas-ml?canal=fuera. Same access as the tab: the route asks for
 * `ventas_fuera.ver_dashboard` and this page for the ADMIN or SUPERADMIN role, as the backend does. The PDF upload
 * reads this list to leave those salespeople unticked (L22).
 */
import { Link } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import TabAdminVentasFuera from '../components/TabAdminVentasFuera';
import styles from './CargasPdf.module.css';

const ROLES_ADMIN = ['ADMIN', 'SUPERADMIN'];

export default function VendedoresExcluidos() {
  const user = useAuthStore((state) => state.user);
  const esAdmin = ROLES_ADMIN.includes(user?.rol);

  return (
    <div className={styles.container}>
      <nav className={styles.migas} aria-label="Ruta">
        <Link to="/metricas-ml?canal=fuera">Ventas por fuera</Link>
        <span aria-hidden="true"> › </span>
        <Link to="/metricas-ml/cargas">Cargas de PDF</Link>
      </nav>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <h1>Vendedores excluidos</h1>
          <p className={styles.description}>
            Al subir un PDF, estos vendedores aparecen sin marcar: sus ventas no se importan salvo que los elijas.
          </p>
        </div>
      </header>
      {esAdmin ? (
        <TabAdminVentasFuera />
      ) : (
        <p className={styles.vacio}>Solo un administrador puede gestionar los vendedores excluidos.</p>
      )}
    </div>
  );
}
