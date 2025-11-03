import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useEffect } from 'react';
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
import ProtectedRoute from './components/ProtectedRoute';
import './styles/theme.css';

function PrivateRoute({ children }) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return isAuthenticated ? children : <Navigate to="/login" />;
}

function App() {
  const checkAuth = useAuthStore((state) => state.checkAuth);
  const token = useAuthStore((state) => state.token);
  
  useEffect(() => {
    if (token) {
      checkAuth();
    }
  }, []);
  
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Navigate to="/productos" replace />} />
          <Route path="*" element={
            <ProtectedRoute>
              <Navbar />
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
              </Routes>
            </ProtectedRoute>
          } />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;
