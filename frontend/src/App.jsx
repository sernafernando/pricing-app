import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useAuthStore } from './store/authStore';
import { ThemeProvider } from './contexts/ThemeContext';
import { PermisosProvider } from './contexts/PermisosContext';
import Login from './pages/Login';
import Layout from './components/Layout';
import Productos from './pages/Productos';
import Tienda from './pages/Tienda';
import Navbar from './components/Navbar';
import AppLayout from './components/AppLayout';
import Admin from './pages/Admin';
import UltimosCambios from './pages/UltimosCambios';
import PreciosListas from './pages/PreciosListas';
import GestionPM from './pages/GestionPM';
import Banlist from './pages/Banlist';
import ItemsSinMLA from './pages/ItemsSinMLA';
import DashboardVentas from './pages/DashboardVentas';
import DashboardMetricasML from './pages/DashboardMetricasML';
import DashboardVentasFuera from './pages/DashboardVentasFuera';
import DashboardTiendaNube from './pages/DashboardTiendaNube';
import Calculos from './pages/Calculos';
import TestStatsDinamicos from './pages/TestStatsDinamicos';
import Notificaciones from './pages/Notificaciones';
import PedidosPreparacion from './pages/PedidosPreparacion';
import Clientes from './pages/Clientes';
import TurboRouting from './pages/TurboRouting';
import ProtectedRoute from './components/ProtectedRoute';
import ModalCalculadora from './components/ModalCalculadora';
import SmartRedirect from './components/SmartRedirect';
import './styles/design-tokens.css';
import './styles/components.css';
import './styles/buttons-tesla.css';
import './styles/modals-tesla.css';
import './styles/table-tesla.css';
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
      <PermisosProvider>
        <BrowserRouter
          future={{
            v7_startTransition: true,
            v7_relativeSplatPath: true
          }}
        >
          <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<ProtectedRoute><SmartRedirect /></ProtectedRoute>} />
          <Route element={
            <ProtectedRoute>
              <AppLayout />
            </ProtectedRoute>
          }>
            <Route path="/productos" element={
                  <ProtectedRoute permiso="productos.ver">
                    <Productos />
                  </ProtectedRoute>
                } />
                <Route path="/tienda" element={
                  <ProtectedRoute permiso="productos.ver_tienda">
                    <Tienda />
                  </ProtectedRoute>
                } />
                <Route path="/precios-listas" element={
                  <ProtectedRoute permiso="productos.ver">
                    <PreciosListas />
                  </ProtectedRoute>
                } />
                <Route path="/ultimos-cambios" element={
                  <ProtectedRoute permiso="productos.ver_auditoria">
                    <UltimosCambios />
                  </ProtectedRoute>
                } />
                <Route path="/admin" element={
                  <ProtectedRoute permiso="admin.ver_panel">
                    <Admin />
                  </ProtectedRoute>
                } />
                <Route path="/gestion-pm" element={
                  <ProtectedRoute permiso="admin.gestionar_pms">
                    <GestionPM />
                  </ProtectedRoute>
                } />
                <Route path="/mla-banlist" element={
                  <ProtectedRoute permiso="admin.gestionar_mla_banlist">
                    <Banlist />
                  </ProtectedRoute>
                } />
                <Route path="/dashboard-ventas" element={
                  <ProtectedRoute permisos={['ventas_ml.ver_dashboard', 'ventas_fuera.ver_dashboard', 'ventas_tn.ver_dashboard']}>
                    <DashboardVentas />
                  </ProtectedRoute>
                } />
                <Route path="/dashboard-metricas-ml" element={
                  <ProtectedRoute permiso="ventas_ml.ver_dashboard">
                    <DashboardMetricasML />
                  </ProtectedRoute>
                } />
                <Route path="/dashboard-ventas-fuera" element={
                  <ProtectedRoute permiso="ventas_fuera.ver_dashboard">
                    <DashboardVentasFuera />
                  </ProtectedRoute>
                } />
                <Route path="/dashboard-tienda-nube" element={
                  <ProtectedRoute permiso="ventas_tn.ver_dashboard">
                    <DashboardTiendaNube />
                  </ProtectedRoute>
                } />
                <Route path="/calculos" element={
                  <ProtectedRoute permiso="reportes.ver_calculadora">
                    <Calculos />
                  </ProtectedRoute>
                } />
                <Route path="/items-sin-mla" element={
                  <ProtectedRoute permiso="admin.ver_items_sin_mla">
                    <ItemsSinMLA />
                  </ProtectedRoute>
                } />
                <Route path="/test-stats-dinamicos" element={
                  <ProtectedRoute permiso="admin.sincronizar">
                    <TestStatsDinamicos />
                  </ProtectedRoute>
                } />
                <Route path="/notificaciones" element={
                  <ProtectedRoute permiso="reportes.ver_notificaciones">
                    <Notificaciones />
                  </ProtectedRoute>
                } />
                <Route path="/pedidos-preparacion" element={
                  <ProtectedRoute permiso="ordenes.ver_preparacion">
                    <PedidosPreparacion />
                  </ProtectedRoute>
                } />
                <Route path="/clientes" element={
                  <ProtectedRoute permiso="clientes.ver">
                    <Clientes />
                  </ProtectedRoute>
                } />
            <Route path="/turbo-routing" element={
              <ProtectedRoute permiso="ordenes.gestionar_turbo_routing">
                <TurboRouting />
              </ProtectedRoute>
            } />
          </Route>
          </Routes>
        </BrowserRouter>
      </PermisosProvider>
    </ThemeProvider>
  );
}

export default App;
