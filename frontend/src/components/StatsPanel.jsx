import { useState, useEffect } from 'react'
import DOMPurify from 'dompurify'
import './StatsPanel.css'

const StatsPanel = ({ data }) => {
  const [animatedValues, setAnimatedValues] = useState({ totalAwards: 0, totalProcessed: 0 })

  const sanitizeText = (text) => {
    if (!text || typeof text !== 'string') return 'N/A'
    return DOMPurify.sanitize(text, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] })
  }

  const safeNumber = (value) => {
    const num = Number(value)
    return isNaN(num) ? 0 : Math.max(0, Math.min(999999, num))
  }

  const validateDate = (dateStr) => {
    if (!dateStr || typeof dateStr !== 'string') return null
    try {
      const parts = dateStr.split('/')
      if (parts.length !== 3) return null
      const day = parseInt(parts[0])
      const month = parseInt(parts[1])
      const year = parseInt(parts[2])
      if (day < 1 || day > 31 || month < 1 || month > 12 || year < 2000 || year > 2030) return null
      return new Date(year, month - 1, day)
    } catch {
      return null
    }
  }

  const isValidPDFUrl = (url) => {
    if (!url || url === 'No PDF available') return false
    try {
      const urlObj = new URL(url)
      return urlObj.protocol === 'https:' && urlObj.hostname === 'www.bseindia.com'
    } catch {
      return false
    }
  }

  useEffect(() => {
    if (!data) return
    const duration = 1500
    const steps = 45
    const stepDuration = duration / steps
    let currentStep = 0
    const interval = setInterval(() => {
      currentStep++
      const progress = currentStep / steps
      const safeAwards = safeNumber(data.total_awards)
      const safeProcessed = safeNumber(data.total_announcements)
      setAnimatedValues({
        totalAwards: Math.floor(safeAwards * progress),
        totalProcessed: Math.floor(safeProcessed * progress)
      })
      if (currentStep >= steps) {
        clearInterval(interval)
        setAnimatedValues({ totalAwards: safeAwards, totalProcessed: safeProcessed })
      }
    }, stepDuration)
    return () => clearInterval(interval)
  }, [data])

  if (!data) return null

  const formatDate = (dateStr) => {
    const validDate = validateDate(dateStr)
    if (!validDate) return 'Invalid Date'
    return validDate.toLocaleDateString('en-US', {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    })
  }

  const truncateText = (text, maxLength = 100) => {
    const safeText = sanitizeText(text)
    if (safeText.length <= maxLength) return safeText
    return safeText.substring(0, maxLength) + '...'
  }

  const safeData = {
    date: data.date,
    total_awards: safeNumber(data.total_awards),
    total_announcements: safeNumber(data.total_announcements),
    orders: Array.isArray(data.orders) ? data.orders : []
  }

  return (
    <div className="premium-stats-panel">
      <div className="detection-summary">
        <div className="summary-card">
          <div className="summary-header">
            <div className="summary-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M9 12l2 2 4-4"/>
                <circle cx="12" cy="12" r="9"/>
              </svg>
            </div>
            <div className="summary-content">
              <h2>Analysis Complete</h2>
              <p>Order detection results for {formatDate(safeData.date)}</p>
            </div>
          </div>
          <div className="summary-stats">
            <div className="summary-stat">
              <div className="stat-number">{animatedValues.totalProcessed.toLocaleString()}</div>
              <div className="stat-label">Announcements Scanned</div>
            </div>
            <div className="summary-divider"></div>
            <div className="summary-stat highlight">
              <div className="stat-number">{animatedValues.totalAwards}</div>
              <div className="stat-label">Order Wins Detected</div>
            </div>
            <div className="summary-divider">=</div>
            <div className="summary-stat success-rate">
              <div className="stat-number">
                {safeData.total_announcements ? ((safeData.total_awards / safeData.total_announcements) * 100).toFixed(2) : '0.00'}%
              </div>
              <div className="stat-label">Success Rate</div>
            </div>
          </div>
        </div>
      </div>

      {safeData.orders.length > 0 ? (
        <div className="order-wins-section">
          <div className="section-header">
            <h3>📋 Detected Order Wins</h3>
            <span className="results-count">{safeData.total_awards} results</span>
          </div>
          <div className="order-wins-list">
            {safeData.orders.map((order, index) => {
              const safeOrder = {
                company: sanitizeText(order.company),
                title: sanitizeText(order.title),
                summary: sanitizeText(order.summary),
                page: safeNumber(order.page),
                announcement_num: safeNumber(order.announcement_num),
                pdf_link: order.pdf_link
              }
              return (
                <div key={`${safeOrder.company}-${index}`} className="order-win-card">
                  <div className="order-header">
                    <div className="order-rank">#{index + 1}</div>
                    <div className="order-status">
                      <div className="status-dot"></div>
                      <span>Order Win</span>
                    </div>
                  </div>
                  <div className="order-content">
                    <div className="company-info">
                      <h4 className="company-name">{safeOrder.company}</h4>
                      <div className="order-meta">
                        <span className="meta-item">
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                            <circle cx="12" cy="12" r="10"/>
                            <path d="M12 6v6l4 2"/>
                          </svg>
                          Page {safeOrder.page}, Position {safeOrder.announcement_num}
                        </span>
                      </div>
                    </div>
                    <div className="announcement-details">
                      <div className="announcement-title">
                        <strong>Title:</strong> {truncateText(safeOrder.title, 120)}
                      </div>
                      <div className="announcement-summary">
                        <strong>Summary:</strong> {truncateText(safeOrder.summary, 150)}
                      </div>
                    </div>
                  </div>
                  <div className="order-actions">
                    {isValidPDFUrl(safeOrder.pdf_link) ? (
                      <a href={safeOrder.pdf_link} target="_blank" rel="noopener noreferrer" className="pdf-button available">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                          <polyline points="14,2 14,8 20,8"/>
                          <line x1="16" y1="13" x2="8" y2="13"/>
                          <line x1="16" y1="17" x2="8" y2="17"/>
                        </svg>
                        View PDF
                      </a>
                    ) : (
                      <button className="pdf-button unavailable" disabled>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                          <polyline points="14,2 14,8 20,8"/>
                          <path d="M9 9l6 6M15 9l-6 6"/>
                        </svg>
                        {safeOrder.pdf_link && safeOrder.pdf_link !== 'No PDF available' ? 'Invalid PDF' : 'No PDF'}
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ) : (
        <div className="no-results-section">
          <div className="no-results-card">
            <div className="no-results-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <circle cx="12" cy="12" r="10"/>
                <path d="M8 12h8"/>
              </svg>
            </div>
            <div className="no-results-content">
              <h3>No Order Wins Found</h3>
              <p>No companies announced order receipts on {formatDate(safeData.date)}</p>
              <div className="no-results-suggestions">
                <span>💡 This could mean:</span>
                <ul>
                  <li>It was a non-trading day</li>
                  <li>No significant orders were announced</li>
                  <li>Orders were announced under different categories</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default StatsPanel