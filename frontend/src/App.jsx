import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useEffect } from 'react';
import { useAuthStore } from './store/authStore';
import Login from './pages/Login';
import Layout from './components/Layout';
import Productos from './pages/Productos';
import Navbar from './components/Navbar';
import Admin from './pages/Admin';

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
      <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/" element={<Navigate to="/productos" replace />} />
              <Route path="*" element={
                <>
                  <Navbar />
                  <Routes>
                    <Route path="/productos" element={<Productos />} />
                    <Route path="/admin" element={<Admin />} />
                  </Routes>
                </>
              } />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
