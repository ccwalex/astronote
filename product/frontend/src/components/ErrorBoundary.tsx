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
};

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary', error, info.componentStack);
  }

  private handleRecover = () => {
    if (this.props.onRecover) {
      this.setState({ error: null });
      this.props.onRecover();
      return;
    }
    this.setState({ error: null });
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
          <div>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>
              {this.props.fallbackTitle || 'Something went wrong'}
            </div>
            <div style={{ marginBottom: this.props.onRecover ? 16 : 0 }}>
              {detail}
            </div>
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
            ) : null}
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
