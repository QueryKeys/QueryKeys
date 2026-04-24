/**
 * ErrorBoundary – catches render-time exceptions and displays a visible error
 * instead of a blank white/black screen.
 */
import React from 'react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Log to console for debugging
    console.error('App crashed:', error, info);
    this.setState({ info });
  }

  render() {
    if (this.state.error) {
      return (
        <div style={styles.wrap}>
          <div style={styles.box}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>⚠️</div>
            <h2 style={{ color: '#ef5350', margin: 0 }}>App crashed</h2>
            <pre style={styles.pre}>{String(this.state.error?.stack ?? this.state.error)}</pre>
            {this.state.info && (
              <pre style={{ ...styles.pre, color: '#8b949e' }}>{this.state.info.componentStack}</pre>
            )}
            <button style={styles.btn} onClick={() => window.location.reload()}>
              Reload page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const styles = {
  wrap: {
    position: 'fixed', inset: 0, background: '#0d1117',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    padding: 20, fontFamily: 'Consolas, monospace',
  },
  box: {
    maxWidth: 800, background: '#161b22', border: '1px solid #ef5350',
    borderRadius: 8, padding: 24, color: '#e6edf3',
  },
  pre: {
    marginTop: 12, padding: 12, background: '#0d1117', borderRadius: 4,
    overflow: 'auto', fontSize: 11, color: '#ef5350', whiteSpace: 'pre-wrap',
  },
  btn: {
    marginTop: 16, background: '#26a69a', color: '#fff', border: 'none',
    borderRadius: 4, padding: '8px 16px', cursor: 'pointer', fontWeight: 'bold',
  },
};
