import { createContext, useContext, useState, useEffect } from 'react';

const ThemeContext = createContext();

// eslint-disable-next-line react-refresh/only-export-components
export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within ThemeProvider');
  }
  return context;
};

export const ThemeProvider = ({ children }) => {
  const [theme, setTheme] = useState(() => {
    // Cargar tema guardado o usar 'light' por defecto
    return localStorage.getItem('theme') || 'light';
  });

  const [highContrast, setHighContrast] = useState(() => {
    // Cargar preferencia de alto contraste
    return localStorage.getItem('highContrast') === 'true';
  });

  useEffect(() => {
    // Aplicar la clase al documento
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  useEffect(() => {
    // Aplicar/remover clase high-contrast
    if (highContrast) {
      document.documentElement.classList.add('high-contrast');
      console.log('✅ High contrast activado - clase agregada a <html>');
    } else {
      document.documentElement.classList.remove('high-contrast');
      console.log('❌ High contrast desactivado - clase removida de <html>');
    }
    localStorage.setItem('highContrast', highContrast);
  }, [highContrast]);

  const toggleTheme = () => {
    setTheme(prevTheme => prevTheme === 'light' ? 'dark' : 'light');
  };

  const toggleHighContrast = () => {
    setHighContrast(prev => !prev);
  };

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, highContrast, toggleHighContrast }}>
      {children}
    </ThemeContext.Provider>
  );
};
