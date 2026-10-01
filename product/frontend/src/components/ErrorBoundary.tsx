import { Component, type ErrorInfo, type ReactNode } from 'react';

type Props = {
  children: ReactNode;
  fallbackTitle?: string;
  /** Optional recovery action (e.g. clear cache + reload). */
  onRecover?: () => void;
  recoverLabel?: string;
};

type State = {
  error: Error | null;
  componentStack: string | null;
};

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, componentStack: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary', error, info.componentStack);
    this.setState({ componentStack: info.componentStack || null });
  }

  private handleRecover = () => {
    if (this.props.onRecover) {
      this.setState({ error: null, componentStack: null });
      this.props.onRecover();
      return;
    }
    this.setState({ error: null, componentStack: null });
  };

  render() {
    if (this.state.error) {
      const detail =
        this.state.error.message || 'The view failed to render.';
      return (
        <div
          role="alert"
          style={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#c00',
            textAlign: 'center',
            padding: '2rem'
          }}
        >
          <div style={{ maxWidth: 640 }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>
              {this.props.fallbackTitle || 'Something went wrong'}
            </div>
            <div style={{ marginBottom: 12 }}>
              {detail}
            </div>
            {this.state.componentStack ? (
              <pre
                style={{
                  textAlign: 'left',
                  fontSize: '11px',
                  color: '#666',
                  whiteSpace: 'pre-wrap',
                  marginBottom: 16,
                  maxHeight: 180,
                  overflow: 'auto',
                  background: '#f6f6f6',
                  padding: 8,
                  borderRadius: 4
                }}
              >
                {this.state.componentStack}
              </pre>
            ) : null}
            {this.props.onRecover ? (
              <button
                type="button"
                onClick={this.handleRecover}
                style={{
                  fontSize: '12px',
                  padding: '6px 12px',
                  cursor: 'pointer'
                }}
              >
                {this.props.recoverLabel || 'Clear cache and reload'}
              </button>
            ) : (
              <button
                type="button"
                onClick={() => window.location.reload()}
                style={{
                  fontSize: '12px',
                  padding: '6px 12px',
                  cursor: 'pointer'
                }}
              >
                Reload page
              </button>
            )}
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
