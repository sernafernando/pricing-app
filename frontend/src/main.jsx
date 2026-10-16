import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { applyStoredBrand } from './contexts/ThemeContext'
// After App, so it lands after theme.css: brand blocks override the base theme.
import './styles/brand-tplink.css'

// Before the first render: a reload must not flash the base theme for
// TP-only users while their permissions load.
applyStoredBrand()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
