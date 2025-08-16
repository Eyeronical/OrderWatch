import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './styles/index.css'
import { Analytics } from '@vercel/analytics/react'

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
      window.gtag('event', 'exception', {
        description: String(error),
        fatal: false
      })
    }
  }

  handleReload = () => {
    window.location.reload()
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-boundary">
          <div className="error-boundary-content">
            <div className="error-boundary-icon">⚠️</div>
            <h1>Something went wrong</h1>
            <p>We apologize for the inconvenience. The application encountered an unexpected error.</p>
            <div className="error-actions">
              <button className="btn btn-primary" onClick={this.handleReload}>🔄 Reload Application</button>
              <button className="btn btn-secondary" onClick={() => window.history.back()}>← Go Back</button>
            </div>
            <div className="error-help">
              <h3>Troubleshooting</h3>
              <ul>
                <li>• Refresh the page</li>
                <li>• Clear browser cache</li>
                <li>• Try again in a few minutes</li>
                <li>• Check your internet connection</li>
              </ul>
            </div>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

if (import.meta.env.PROD) {
  console.log = () => {}
  console.warn = () => {}
  console.error = () => {}
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
      <Analytics />
    </ErrorBoundary>
  </React.StrictMode>
)

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').then(() => {}).catch(() => {})
  })
}

window.addEventListener('error', (event) => {
  if (import.meta.env.PROD && window.gtag) {
    window.gtag('event', 'exception', {
      description: event.error ? String(event.error) : 'Unknown error',
      fatal: false
    })
  }
})

window.addEventListener('unhandledrejection', (event) => {
  if (import.meta.env.PROD && window.gtag) {
    window.gtag('event', 'exception', {
      description: event.reason ? String(event.reason) : 'Unhandled promise rejection',
      fatal: false
    })
  }
})

if (import.meta.hot) {
  import.meta.hot.accept()
}
