import { Link, useLocation, useNavigate } from 'react-router-dom';
import styles from './Navbar.module.css';
import logo from '../assets/white-g-logo.png';

export default function Navbar() {
  const location = useLocation();
  const navigate = useNavigate();
  
  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  const isActive = (path) => location.pathname === path;

  return (
    <nav className={styles.navbar}>
      <div className={styles.container}>
        <div className={styles.brand}>
          <img src={logo} alt="Logo" className={styles.logo} />
          <span className={styles.title}>Pricing App</span>
        </div>
        
        <div className={styles.links}>
          <Link 
            to="/productos" 
            className={`${styles.link} ${isActive('/productos') ? styles.active : ''}`}
          >
            📦 Productos
          </Link>

          <Link
            to="/precios-listas"
            className={`${styles.link} ${isActive('/precios-listas') ? styles.active : ''}`}
          >
            💰 Precios por Lista
          </Link>

          <Link
            to="/ultimos-cambios"
            className={`${styles.link} ${isActive('/ultimos-cambios') ? styles.active : ''}`}
          >
            📋 Últimos Cambios
          </Link>
          
          <Link 
            to="/admin" 
            className={`${styles.link} ${isActive('/admin') ? styles.active : ''}`}
          >
            ⚙️ Admin
          </Link>
        </div>

        <button onClick={handleLogout} className={styles.logoutBtn}>
          🚪 Salir
        </button>
      </div>
    </nav>
  );
}
