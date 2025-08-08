import React from 'react'

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null, errorInfo: null }
  }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ error, errorInfo })
    if (import.meta.env.PROD && window.gtag) {
      window.gtag('event', 'exception', { description: String(error), fatal: false })
    }
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-boundary">
          <div className="error-container">
            <div className="error-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
              </svg>
            </div>
            <div className="error-content">
              <h2>Oops! Something went wrong</h2>
              <p>We're sorry, but something unexpected happened. Please try refreshing the page.</p>
              <div className="error-actions">
                <button onClick={this.handleReset} className="retry-btn">Try Again</button>
                <button onClick={() => window.location.reload()} className="refresh-btn">Refresh Page</button>
              </div>
              {import.meta.env.DEV && this.state.error && (
                <details className="error-details">
                  <summary>Error Details (Development Only)</summary>
                  <pre>{this.state.error && this.state.error.toString()}</pre>
                  <pre>{this.state.errorInfo?.componentStack || ''}</pre>
                </details>
              )}
            </div>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

export default ErrorBoundary