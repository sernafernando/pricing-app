import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useEffect } from 'react';
import { useAuthStore } from './store/authStore';
import Login from './pages/Login';
import Layout from './components/Layout';
import Productos from './pages/Productos';
import Navbar from './components/Navbar';
import Admin from './pages/Admin';
import UltimosCambios from './pages/UltimosCambios';
import PreciosListas from './pages/PreciosListas';
import ProtectedRoute from './components/ProtectedRoute';

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
    <BrowserRouter>
	 <div style={{ fontFamily: 'Inter, sans-serif' }}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Navigate to="/productos" replace />} />
        <Route path="*" element={
          <ProtectedRoute>
            <Navbar />
            <Routes>
              <Route path="/productos" element={<Productos />} />
              <Route path="/precios-listas" element={<PreciosListas />} />
              <Route path="/ultimos-cambios" element={<UltimosCambios />} />
              <Route path="/admin" element={<Admin />} />
            </Routes>
          </ProtectedRoute>
        } />
      </Routes>
     </div>
    </BrowserRouter>
  );
}

export default App;
