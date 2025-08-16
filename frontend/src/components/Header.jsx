import { useState, useEffect, useRef } from 'react'
import './Header.css'

const Header = () => {
  const [showAuthNotice, setShowAuthNotice] = useState(false)
  const [analysisRuns, setAnalysisRuns] = useState(null)
  const bumpedRef = useRef(false)

  const API = import.meta.env.VITE_API_URL || ''

  const fetchAnalysisRuns = async () => {
    try {
      const res = await fetch(`${API}/api/usage`, { method: 'GET' })
      const data = await res.json()
      if (typeof data.analysis_runs === 'number') setAnalysisRuns(data.analysis_runs)
    } catch {

    }
  }

  useEffect(() => {
    fetchAnalysisRuns()
  }, [API])

  const handleAuthClick = (e) => {
    e.preventDefault()
    setShowAuthNotice(true)
  }

  useEffect(() => {
    if (!showAuthNotice) return
    const t = setTimeout(() => setShowAuthNotice(false), 2000)
    return () => clearTimeout(t)
  }, [showAuthNotice])

  return (
    <header className="simple-header">
      <div className="header-container">
        <div className="header-content">
          <div className="brand-section">
            <div className="logo">
              <div className="logo-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <circle cx="12" cy="12" r="3"/>
                  <path d="M12 1v6m0 6v6"/>
                  <path d="m21 12-6-6-6 6-6-6"/>
                </svg>
              </div>
            </div>
            <div className="brand-text">
              <h1>Order Watch</h1>
              <p>Track order wins daily</p>
            </div>
          </div>

          <div className="auth-section">
            <div className="usage-counter" title="Total analyses performed">
              Analyses: {analysisRuns === null ? '—' : analysisRuns.toLocaleString()}
            </div>
            <div className="auth-buttons">
              <button className="login-btn" onClick={handleAuthClick}>Log In</button>
              <button className="signup-btn" onClick={handleAuthClick}>Sign Up</button>
            </div>

            {showAuthNotice && (
              <div className="auth-notice" role="status" aria-live="polite">
                <span className="dot" aria-hidden="true">•</span>
                <span>Coming soon</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}

export default Header
