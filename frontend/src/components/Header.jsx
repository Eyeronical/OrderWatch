import { useState, useEffect, useRef } from 'react'
import './Header.css'

const Header = () => {
  const [showAuthNotice, setShowAuthNotice] = useState(false)
  const [visits, setVisits] = useState(null)
  const bumpedRef = useRef(false)

  // Support both absolute API URL and Vite proxy
  const API = import.meta.env.VITE_API_URL || ''

  const fetchVisits = async () => {
    try {
      const res = await fetch(`${API}/api/visit`, { method: 'GET' })
      const data = await res.json()
      if (typeof data.visits === 'number') setVisits(data.visits)
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    // Prevent double-increment in React 18 StrictMode (dev) and ensure 1 bump per tab
    const sessionKey = 'visit-hit-v1'
    const alreadyBumped = sessionStorage.getItem(sessionKey) === '1'
    if (alreadyBumped || bumpedRef.current) {
      fetchVisits()
      return
    }

    let cancelled = false
    const bump = async () => {
      try {
        const res = await fetch(`${API}/api/visit`, { method: 'POST' })
        const data = await res.json()
        if (!cancelled && typeof data.visits === 'number') setVisits(data.visits)
      } catch {
        // ignore
      } finally {
        bumpedRef.current = true
        sessionStorage.setItem(sessionKey, '1')
        // also fetch to confirm value
        fetchVisits()
      }
    }
    bump()
    return () => { cancelled = true }
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
            <div className="visit-counter" title="Total visits">
              Visits: {visits === null ? '—' : visits.toLocaleString()}
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