import { Component } from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import styles from './ErrorBoundary.module.css';

// Class component required — getDerivedStateFromError has no hooks equivalent
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
    this.props.onReset?.();
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className={styles.container}>
          <AlertCircle size={32} className={styles.icon} />
          <h2 className={styles.title}>Algo salió mal</h2>
          <p className={styles.message}>
            {this.state.error?.message || 'Error inesperado al renderizar este componente.'}
          </p>
          <button className="btn-tesla outline-subtle-primary sm" onClick={this.handleReset}>
            <RefreshCw size={16} />
            Reintentar
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
