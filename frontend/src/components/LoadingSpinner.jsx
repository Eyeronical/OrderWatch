import { useEffect, useState } from 'react'
import './LoadingSpinner.css'

const LoadingSpinner = ({ progress = 0, message = 'Loading...', onCancel }) => {
  const [dots, setDots] = useState('')

  useEffect(() => {
    const interval = setInterval(() => {
      setDots(prev => (prev === '...' ? '' : prev + '.'))
    }, 500)
    return () => clearInterval(interval)
  }, [])

  const getProgressColor = (p) => {
    if (p < 30) return '#ef4444'
    if (p < 70) return '#f59e0b'
    return '#10b981'
  }

  const getStatusIcon = (p) => {
    if (p < 25) return '🔧'
    if (p < 50) return '🌐'
    if (p < 75) return '🔍'
    if (p < 100) return '📊'
    return '✅'
  }

  return (
    <div className="premium-loading-overlay">
      <div className="loading-backdrop">
        <div className="loading-card">
          <div className="loading-header">
            <div className="loading-icon">
              <span className="status-icon">{getStatusIcon(progress)}</span>
            </div>
            <div className="header-content">
              <h3>Order Watch Analysis</h3>
              <p>Analyzing order data for your selected date</p>
            </div>
          </div>

          <div className="progress-section">
            <div className="progress-circle">
              <svg className="progress-ring" width="100" height="100">
                <circle
                  className="progress-ring-background"
                  stroke="#e5e7eb"
                  strokeWidth="6"
                  fill="transparent"
                  r="42"
                  cx="50"
                  cy="50"
                />
                <circle
                  className="progress-ring-progress"
                  stroke={getProgressColor(progress)}
                  strokeWidth="6"
                  fill="transparent"
                  r="42"
                  cx="50"
                  cy="50"
                  style={{
                    strokeDasharray: `${2 * Math.PI * 42}`,
                    strokeDashoffset: `${2 * Math.PI * 42 * (1 - progress / 100)}`
                  }}
                />
              </svg>
              <div className="progress-text">
                <span className="progress-percentage">{progress}%</span>
              </div>
            </div>
          </div>

          <div className="status-section">
            <div className="status-message">
              <span className="message-text">{message}{dots}</span>
              <span className="eta-chip" aria-live="polite">ETA ~ 1–2 min</span>
            </div>
            <div className="progress-bar">
              <div
                className="progress-bar-fill"
                style={{
                  width: `${progress}%`,
                  backgroundColor: getProgressColor(progress)
                }}
              />
            </div>
          </div>

          <div className="progress-steps">
            <div className={`step ${progress >= 25 ? 'completed' : progress >= 10 ? 'active' : ''}`}>
              <div className="step-dot"></div>
              <span>Setup</span>
            </div>
            <div className={`step ${progress >= 50 ? 'completed' : progress >= 25 ? 'active' : ''}`}>
              <div className="step-dot"></div>
              <span>Connect</span>
            </div>
            <div className={`step ${progress >= 75 ? 'completed' : progress >= 50 ? 'active' : ''}`}>
              <div className="step-dot"></div>
              <span>Analyze</span>
            </div>
            <div className={`step ${progress >= 100 ? 'completed' : progress >= 75 ? 'active' : ''}`}>
              <div className="step-dot"></div>
              <span>Complete</span>
            </div>
          </div>

          {onCancel && (
            <button className="cancel-button" onClick={onCancel}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <circle cx="12" cy="12" r="10"/>
                <path d="M15 9l-6 6M9 9l6 6"/>
              </svg>
              Cancel Analysis
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default LoadingSpinner