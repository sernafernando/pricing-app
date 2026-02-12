import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import logoIcon from '../assets/white-g-logo.png';
import styles from './Login.module.css';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [loginExitoso, setLoginExitoso] = useState(false);

  const login = useAuthStore((state) => state.login);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    const result = await login(username, password);

    if (result.success) {
      setLoginExitoso(true);
      // Pequeña pausa para mostrar feedback antes de navegar
      setTimeout(() => {
        navigate('/');
      }, 300);
    } else {
      setError(result.error);
      setLoading(false);
    }
  };
  
  // Mostrar pantalla de carga después de login exitoso
  if (loginExitoso) {
    return (
      <div className={styles.container}>
        <div className={styles.loadingOverlay}>
          <div className={styles.spinner}></div>
          <p>Cargando tu sesión...</p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.card}>
        <div className={styles.logo}>
          <img src={logoIcon} alt="Logo empresa" className={styles.logoImg} />
          <h1 className={styles.title}>Pricing App</h1>
          <p className={styles.subtitle}>Sistema de gestión integral</p>
        </div>

        <form onSubmit={handleSubmit} className={styles.form}>
          <div className={styles.formGroup}>
            <label className={styles.label}>Usuario o Email</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className={styles.input}
              placeholder="usuario o tu@email.com"
              required
              autoFocus
            />
          </div>
          
          <div className={styles.formGroup}>
            <label className={styles.label}>Contraseña</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={styles.input}
              placeholder="••••••••"
              required
            />
          </div>
          
          {error && (
            <div className={styles.error}>
              {error}
            </div>
          )}
          
          <button
            type="submit"
            disabled={loading}
            className={styles.button}
          >
            {loading ? 'Ingresando...' : 'Iniciar Sesión'}
          </button>
        </form>
        
        <div className={styles.footer}>
          <p>¿Problemas para ingresar? Contactá al administrador</p>
        </div>
      </div>
    </div>
  );
}
