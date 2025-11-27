import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useAuthStore } from './store/authStore';
import { ThemeProvider } from './contexts/ThemeContext';
import Login from './pages/Login';
import Layout from './components/Layout';
import Productos from './pages/Productos';
import Navbar from './components/Navbar';
import Admin from './pages/Admin';
import UltimosCambios from './pages/UltimosCambios';
import PreciosListas from './pages/PreciosListas';
import GestionPM from './pages/GestionPM';
import Banlist from './pages/Banlist';
import ItemsSinMLA from './pages/ItemsSinMLA';
import DashboardVentas from './pages/DashboardVentas';
import DashboardMetricasML from './pages/DashboardMetricasML';
import Calculos from './pages/Calculos';
import TestStatsDinamicos from './pages/TestStatsDinamicos';
import Notificaciones from './pages/Notificaciones';
import ProtectedRoute from './components/ProtectedRoute';
import ModalCalculadora from './components/ModalCalculadora';
import './styles/theme.css';

function PrivateRoute({ children }) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return isAuthenticated ? children : <Navigate to="/login" />;
}

function App() {
  const checkAuth = useAuthStore((state) => state.checkAuth);
  const token = useAuthStore((state) => state.token);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const [mostrarCalculadora, setMostrarCalculadora] = useState(false);

  useEffect(() => {
    if (token) {
      checkAuth();
    }
  }, []);

  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ctrl+P o Cmd+P para abrir calculadora
      if ((e.ctrlKey || e.metaKey) && e.key === 'p' && isAuthenticated) {
        e.preventDefault();
        setMostrarCalculadora(true);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isAuthenticated]);

  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Navigate to="/productos" replace />} />
          <Route path="*" element={
            <ProtectedRoute>
              <Navbar />
              <ModalCalculadora
                isOpen={mostrarCalculadora}
                onClose={() => setMostrarCalculadora(false)}
              />
              <Routes>
                <Route path="/productos" element={
                  <ProtectedRoute>
                    <Productos />
                  </ProtectedRoute>
                } />
                <Route path="/precios-listas" element={
                  <ProtectedRoute>
                    <PreciosListas />
                  </ProtectedRoute>
                } />
                <Route path="/ultimos-cambios" element={
                  <ProtectedRoute allowedRoles={['SUPERADMIN', 'ADMIN', 'GERENTE']}>
                    <UltimosCambios />
                  </ProtectedRoute>
                } />
                <Route path="/admin" element={
                  <ProtectedRoute allowedRoles={['SUPERADMIN', 'ADMIN']}>
                    <Admin />
                  </ProtectedRoute>
                } />
                <Route path="/gestion-pm" element={
                  <ProtectedRoute allowedRoles={['SUPERADMIN', 'ADMIN']}>
                    <GestionPM />
                  </ProtectedRoute>
                } />
                <Route path="/mla-banlist" element={
                  <ProtectedRoute>
                    <Banlist />
                  </ProtectedRoute>
                } />
                <Route path="/dashboard-ventas" element={
                  <ProtectedRoute>
                    <DashboardVentas />
                  </ProtectedRoute>
                } />
                <Route path="/dashboard-metricas-ml" element={
                  <ProtectedRoute>
                    <DashboardMetricasML />
                  </ProtectedRoute>
                } />
                <Route path="/calculos" element={
                  <ProtectedRoute>
                    <Calculos />
                  </ProtectedRoute>
                } />
                <Route path="/items-sin-mla" element={
                  <ProtectedRoute>
                    <ItemsSinMLA />
                  </ProtectedRoute>
                } />
                <Route path="/test-stats-dinamicos" element={
                  <ProtectedRoute allowedRoles={['SUPERADMIN', 'ADMIN']}>
                    <TestStatsDinamicos />
                  </ProtectedRoute>
                } />
                <Route path="/notificaciones" element={
                  <ProtectedRoute>
                    <Notificaciones />
                  </ProtectedRoute>
                } />
              </Routes>
            </ProtectedRoute>
          } />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;
