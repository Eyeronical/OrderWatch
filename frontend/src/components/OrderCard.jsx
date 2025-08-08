import { useState } from 'react'
import DOMPurify from 'dompurify'
import './OrderCard.css'

const OrderCard = ({ order, index }) => {
  const [isExpanded, setIsExpanded] = useState(false)

  const getValueBadge = (totalValue) => {
    if (totalValue >= 100) return { label: 'High Value', class: 'high-value', icon: '💎' }
    if (totalValue >= 10) return { label: 'Medium Value', class: 'medium-value', icon: '📈' }
    if (totalValue > 0) return { label: 'Low Value', class: 'low-value', icon: '💰' }
    return { label: 'Value N/A', class: 'no-value', icon: '📋' }
  }

  const formatCurrency = (amount) => {
    if (amount >= 1000) return `₹${(amount / 1000).toFixed(1)}K Cr`
    return `₹${amount.toFixed(2)} Cr`
  }

  const truncateText = (text, maxLength = 120) => {
    if (!text || typeof text !== 'string') return 'No description available'
    if (text.length <= maxLength) return text
    return text.substring(0, maxLength) + '...'
  }

  const sanitizeText = (text) => {
    if (!text) return 'N/A'
    return DOMPurify.sanitize(String(text), { ALLOWED_TAGS: [], ALLOWED_ATTR: [] })
  }

  const isValidPDFUrl = (url) => {
    if (!url || url === 'No PDF available') return false
    try {
      const urlObj = new URL(url)
      return urlObj.protocol === 'https:' && urlObj.hostname === 'www.bseindia.com' && (url.toLowerCase().includes('.pdf') || url.includes('download'))
    } catch {
      return false
    }
  }

  const safeNumber = (value) => {
    const num = Number(value)
    return isNaN(num) ? 0 : Math.max(0, Math.min(999999, num))
  }

  const badge = getValueBadge(safeNumber(order.total_value_crores))
  const safeOrder = {
    company: sanitizeText(order.company),
    title: sanitizeText(order.title),
    summary: sanitizeText(order.summary),
    raw_company: sanitizeText(order.raw_company),
    pdf_extract: sanitizeText(order.pdf_extract),
    page: safeNumber(order.page),
    announcement_num: safeNumber(order.announcement_num),
    total_value_crores: safeNumber(order.total_value_crores),
    pdf_link: order.pdf_link
  }

  return (
    <div className={`premium-order-card ${badge.class}`}>
      <div className="card-header">
        <div className="rank-badge">
          <span className="rank-number">#{index + 1}</span>
        </div>
        <div className="value-badge">
          <span className="badge-icon">{badge.icon}</span>
          <span className="badge-label">{badge.label}</span>
        </div>
      </div>

      <div className="company-section">
        <h3 className="company-name">{safeOrder.company}</h3>
        <div className="company-meta">
          <div className="meta-chip">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <circle cx="12" cy="12" r="10"/>
              <path d="M12 6v6l4 2"/>
            </svg>
            <span>Position {safeOrder.announcement_num}</span>
          </div>
        </div>
      </div>

      <div className="value-section">
        {safeOrder.total_value_crores > 0 ? (
          <div className="value-container">
            <div className="primary-value">
              <span className="currency-symbol">₹</span>
              <span className="amount">{formatCurrency(safeOrder.total_value_crores).replace('₹', '')}</span>
            </div>
            {order.order_values && Array.isArray(order.order_values) && order.order_values.length > 0 && (
              <div className="value-breakdown">
                {order.order_values.slice(0, 2).map((val, idx) => (
                  <span key={idx} className="value-chip">
                    {sanitizeText(val.formatted)}
                  </span>
                ))}
                {order.order_values.length > 2 && (
                  <span className="more-values">+{order.order_values.length - 2} more</span>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="value-container no-value">
            <div className="primary-value">
              <span className="no-value-text">Value Not Available</span>
            </div>
            <div className="value-note">Analysis pending</div>
          </div>
        )}
      </div>

      <div className="summary-section">
        <div className="summary-content">
          <p className="summary-text">
            {isExpanded ? safeOrder.summary : truncateText(safeOrder.summary)}
          </p>
        </div>
      </div>

      <div className="actions-section">
        {isValidPDFUrl(safeOrder.pdf_link) ? (
          <a href={safeOrder.pdf_link} target="_blank" rel="noopener noreferrer" className="action-btn primary">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14,2 14,8 20,8"/>
              <line x1="16" y1="13" x2="8" y2="13"/>
              <line x1="16" y1="17" x2="8" y2="17"/>
              <polyline points="10,9 9,9 8,9"/>
            </svg>
            View Document
          </a>
        ) : (
          <button className="action-btn disabled" disabled>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14,2 14,8 20,8"/>
            </svg>
            {safeOrder.pdf_link && safeOrder.pdf_link !== 'No PDF available' ? 'Invalid Document' : 'No Document'}
          </button>
        )}
        <button className="action-btn secondary" onClick={() => setIsExpanded(!isExpanded)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1 1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
          {isExpanded ? 'Less Details' : 'More Details'}
        </button>
      </div>

      {isExpanded && (
        <div className="expanded-section">
          <div className="details-grid">
            <div className="detail-item">
              <span className="detail-label">Full Title</span>
              <span className="detail-value">{safeOrder.title}</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">Company (Raw)</span>
              <span className="detail-value">{safeOrder.raw_company}</span>
            </div>
            {safeOrder.pdf_extract && safeOrder.pdf_extract !== 'PDF not accessible' && (
              <div className="detail-item full-width">
                <span className="detail-label">Document Extract</span>
                <div className="pdf-extract">{safeOrder.pdf_extract}</div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default OrderCard