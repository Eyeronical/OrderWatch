import { useState } from 'react'
import DOMPurify from 'dompurify'
import './Footer.css'

const Footer = () => {
  const [email, setEmail] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState('')

  const validateEmail = (email) => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    if (!email) return 'Email is required'
    if (!emailRegex.test(email)) return 'Please enter a valid email'
    if (email.length > 254) return 'Email is too long'
    return null
  }

  const sanitizeEmail = (email) => {
    return DOMPurify.sanitize(email.trim().toLowerCase(), { ALLOWED_TAGS: [], ALLOWED_ATTR: [] })
  }

  const handleEmailSubmit = async (e) => {
    e.preventDefault()
    if (isSubmitting) return
    const cleanEmail = sanitizeEmail(email)
    const validationError = validateEmail(cleanEmail)
    if (validationError) {
      setError(validationError)
      return
    }
    setIsSubmitting(true)
    setError('')
    try {
      await new Promise(resolve => setTimeout(resolve, 1500))
      setError('Email subscription feature coming soon! Thanks for your interest.')
      setEmail('')
    } catch {
      setError('Subscription service temporarily unavailable. Please try again later.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleEmailChange = (e) => {
    const value = e.target.value
    if (value.length <= 254) {
      setEmail(value)
      setError('')
    }
  }

  const socialLinks = [
    {
      name: 'Telegram',
      url: 'https://telegram.me/StocksRoyale',
      icon: (
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/>
        </svg>
      )
    },
    {
      name: 'Twitter',
      url: 'https://x.com/StocksRoyale1',
      icon: (
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
        </svg>
      )
    }
  ]

  return (
    <footer className="simple-footer">
      <div className="footer-container">
        <div className="footer-brand">
          <div className="brand-logo">
            <div className="logo-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <rect x="3" y="3" width="18" height="18" rx="2"/>
                <rect x="7" y="7" width="10" height="10" rx="1"/>
              </svg>
            </div>
            <div className="brand-text">
              <h3>Order Watch</h3>
              <p>Track order wins</p>
            </div>
          </div>
          <p className="brand-description">
            Track order wins from all listed companies in the Indian Stock Exchange. 
            Removing junk from all the BSE corporate announcements.
          </p>
        </div>

        <div className="footer-connect">
          <h4>JOIN US</h4>
          <div className="social-buttons">
            {socialLinks.map((social, index) => (
              <a
                key={index}
                href={social.url}
                target="_blank"
                rel="noopener noreferrer"
                className={`social-btn ${social.name.toLowerCase()}`}
                aria-label={`Join us on ${social.name}`}
              >
                {social.icon}
                <span>{social.name}</span>
              </a>
            ))}
          </div>
        </div>

        <div className="footer-newsletter">
          <h4>STAY UPDATED</h4>
          <p>Get notified about new features</p>
          {error && (
            <div className="error-message" role="alert" aria-live="polite">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
              </svg>
              <span>{error}</span>
            </div>
          )}
          <form onSubmit={handleEmailSubmit} className="newsletter-form" noValidate>
            <input
              type="email"
              placeholder="Enter your email"
              value={email}
              onChange={handleEmailChange}
              className="email-input"
              required
              disabled={isSubmitting}
              maxLength={254}
              aria-invalid={!!error}
              aria-describedby={error ? 'newsletter-error' : undefined}
            />
            <button
              type="submit"
              className="submit-btn"
              disabled={isSubmitting || !email}
              aria-label="Subscribe to newsletter"
            >
              {isSubmitting ? (
                <svg className="spinner" viewBox="0 0 24 24" aria-hidden="true">
                  <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" opacity="0.25" />
                  <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
                  <path d="M5 12h14M12 5l7 7-7 7"/>
                </svg>
              )}
            </button>
          </form>
        </div>
      </div>

      <div className="footer-bottom">
        <div className="footer-bottom-content">
          <div className="copyright">
            <p>&copy; 2025 Order Watch. All rights reserved.</p>
          </div>
          <div className="made-with-love">
            <span>Made with</span>
            <svg className="heart" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
            </svg>
            <span>by</span>
            <strong>Parth Goyal</strong>
          </div>
          <div className="footer-socials">
            {socialLinks.map((social, index) => (
              <a
                key={index}
                href={social.url}
                target="_blank"
                rel="noopener noreferrer"
                title={social.name}
                aria-label={social.name}
              >
                {social.icon}
              </a>
            ))}
          </div>
        </div>
      </div>

      <div className="footer-background" aria-hidden="true">
        <div className="bg-gradient"></div>
      </div>
    </footer>
  )
}

export default Footer