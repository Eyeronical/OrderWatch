import { useState } from 'react'
import DOMPurify from 'dompurify'
import './DatePicker.css'

const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const parseISODateUTC = (iso) => {
  if (!ISO_DATE_RE.test(iso)) return null
  const d = new Date(`${iso}T00:00:00Z`)
  return isNaN(d.getTime()) ? null : d
}

const DatePicker = ({ onDateSubmit, isLoading }) => {
  const [selectedDate, setSelectedDate] = useState('')
  const [error, setError] = useState('')

  const today = new Date().toISOString().split('T')[0]
  const minDate = '2010-01-01'

  const validateDate = (dateStr) => {
    if (!dateStr || typeof dateStr !== 'string') return 'Please select a date'
    const sanitized = DOMPurify.sanitize(dateStr, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] })
    if (!ISO_DATE_RE.test(sanitized)) return 'Invalid date format'
    const selected = parseISODateUTC(sanitized)
    const max = parseISODateUTC(today)
    const min = parseISODateUTC(minDate)
    if (!selected || !max || !min) return 'Invalid date'
    if (selected > max) return 'Date cannot be in the future'
    if (selected < min) return 'Date cannot be before 2010'
    // No weekday restriction — weekends are allowed
    return null
  }

  const handleDateChange = (e) => {
    const raw = e.target.value
    const sanitized = DOMPurify.sanitize(raw, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] })
    setSelectedDate(sanitized)
    setError(validateDate(sanitized) || '')
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (isLoading) return
    const validationError = validateDate(selectedDate)
    if (validationError) {
      setError(validationError)
      return
    }
    try {
      const d = parseISODateUTC(selectedDate)
      const formattedDate = d.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      }) // No weekday in label
      if (typeof onDateSubmit === 'function') {
        onDateSubmit(selectedDate, formattedDate)
      }
    } catch {
      setError('Failed to process date')
    }
  }

  const hasError = Boolean(error)
  const isDisabled = isLoading || hasError || !selectedDate

  return (
    <div className="premium-date-picker">
      <div className="date-picker-card">
        <div className="picker-header">
          <div className="header-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
              <line x1="16" y1="2" x2="16" y2="6"/>
              <line x1="8" y1="2" x2="8" y2="6"/>
              <line x1="3" y1="10" x2="21" y2="10"/>
            </svg>
          </div>
          <div className="header-text">
            <h2>Select Date</h2>
            <p>Pick any date to track order wins</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="picker-form" noValidate>
          <div className="date-input-wrapper">
            <label htmlFor="date-input" className="date-label">Enter Date</label>
            <div className="input-container">
              <input
                id="date-input"
                type="date"
                value={selectedDate}
                onChange={handleDateChange}
                min={minDate}
                max={today}
                className={`date-input ${hasError ? 'error' : ''}`}
                disabled={isLoading}
                placeholder="Select date"
                required
                aria-invalid={hasError}
                aria-describedby={hasError ? 'date-error' : undefined}
              />
              <div className="input-border"></div>
            </div>
          </div>

          {hasError && (
            <div id="date-error" className="status-message error" role="alert" aria-live="polite">
              <div className="status-icon" aria-hidden="true">❌</div>
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            className={`submit-btn ${isLoading ? 'loading' : ''}`}
            disabled={isDisabled}
            aria-busy={isLoading}
          >
            {isLoading ? (
              <div className="btn-loading">
                <div className="loading-spinner" aria-hidden="true"></div>
                <span>Analyzing...</span>
              </div>
            ) : (
              <div className="btn-content">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
                  <circle cx="11" cy="11" r="8"/>
                  <path d="M21 21l-4.35-4.35"/>
                </svg>
                <span>Start Analysis</span>
              </div>
            )}
          </button>
        </form>

        <div className="picker-info" aria-hidden="true">
          <div className="info-grid">
            <div className="info-card">
              <div className="info-icon">🎯</div>
              <div className="info-content">
                <span className="info-title">Order Tracking</span>
                <span className="info-desc">Real-time detection</span>
              </div>
            </div>
            <div className="info-card">
              <div className="info-icon">📅</div>
              <div className="info-content">
                <span className="info-title">Any Day</span>
                <span className="info-desc">2010 to present, weekends included</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default DatePicker