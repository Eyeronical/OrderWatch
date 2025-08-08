import { useState, useEffect } from 'react'
import Header from './components/Header'
import DatePicker from './components/DatePicker'
import LoadingSpinner from './components/LoadingSpinner'
import StatsPanel from './components/StatsPanel'
import Footer from './components/Footer'
import apiService from './services/api'

function App() {
  const [appState, setAppState] = useState('idle')
  const [selectedDate, setSelectedDate] = useState('')
  const [formattedDate, setFormattedDate] = useState('')
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [progressMessage, setProgressMessage] = useState('')
  const [results, setResults] = useState(null)
  const [error, setError] = useState('')
  const [serverHealth, setServerHealth] = useState(null)
  const [jobId, setJobId] = useState(null)

  useEffect(() => {
    checkServerHealth()
  }, [])

  const checkServerHealth = async () => {
    try {
      const response = await apiService.checkHealth()
      setServerHealth(response)
      if (!response.success) {
        setError('Service is temporarily unavailable. Please try again later.')
      }
    } catch (err) {
      setServerHealth({ success: false, error: err.message })
      setError('Unable to connect to service. Please check your internet connection.')
    }
  }

  const handleDateSubmit = async (date, formatted) => {
    try {
      setError('')
      setResults(null)
      setSelectedDate(date)
      setFormattedDate(formatted)
      setAppState('loading')
      setLoading(true)
      setProgress(0)
      setProgressMessage('Initializing analysis...')
      setJobId(null)

      const startResponse = await apiService.startScraping(date)
      if (!startResponse.success || !startResponse.jobId) {
        throw new Error(startResponse.error || 'Failed to start analysis')
      }
      setJobId(startResponse.jobId)
      setProgressMessage('Analysis started successfully...')

      const finalResults = await apiService.pollScrapingProgress(
        startResponse.jobId,
        (progressData) => {
          setProgress(progressData.progress || 0)
          setProgressMessage(progressData.message || 'Processing...')
          if (progressData.error) {
            setError(progressData.error)
            setAppState('error')
            setLoading(false)
          }
        },
        2000
      )

      if (finalResults.success && finalResults.data) {
        setResults(finalResults.data)
        setAppState('success')
        setProgressMessage('Analysis completed successfully!')
        setProgress(100)
      } else {
        throw new Error(finalResults.error || 'No results received')
      }
    } catch (err) {
      setError(err.message || 'An unexpected error occurred')
      setAppState('error')
    } finally {
      setLoading(false)
    }
  }

  const handleCancel = async () => {
    try {
      if (jobId) await apiService.stopScraping(jobId)
      setLoading(false)
      setAppState('idle')
      setProgress(0)
      setProgressMessage('')
      setError('')
      setResults(null)
      setJobId(null)
    } catch (err) {
      setError('Failed to cancel operation: ' + err.message)
    }
  }

  const handleRetry = () => {
    setAppState('idle')
    setError('')
    setResults(null)
    setProgress(0)
    setProgressMessage('')
    setLoading(false)
    setJobId(null)
    checkServerHealth()
  }

  const handleNewSearch = () => {
    setAppState('idle')
    setError('')
    setResults(null)
    setSelectedDate('')
    setFormattedDate('')
    setProgress(0)
    setProgressMessage('')
    setLoading(false)
    setJobId(null)
  }

  return (
    <div className="app">
      <Header />
      <main className="main-content">
        {serverHealth && !serverHealth.success && (
          <div className="server-warning">
            <div className="warning-card">
              <div className="warning-icon">⚠️</div>
              <div className="warning-content">
                <h3>Service Connection Issue</h3>
                <p>{error || 'Unable to connect to the service.'}</p>
                <div className="warning-actions">
                  <button className="btn btn-secondary" onClick={checkServerHealth}>🔄 Retry Connection</button>
                </div>
              </div>
            </div>
          </div>
        )}

        {loading && (
          <LoadingSpinner
            progress={progress}
            message={progressMessage}
            onCancel={handleCancel}
          />
        )}

        {(appState === 'idle' || appState === 'error') && !loading && (
          <div className="date-picker-section">
            <DatePicker onDateSubmit={handleDateSubmit} isLoading={loading} />
            {appState === 'error' && error && (
              <div className="error-section">
                <div className="error-card">
                  <div className="error-icon">❌</div>
                  <div className="error-content">
                    <h3>Analysis Failed</h3>
                    <p>{error}</p>
                    <div className="error-details">
                      {selectedDate && <p><strong>Date:</strong> {formattedDate}</p>}
                      <p><strong>Time:</strong> {new Date().toLocaleString()}</p>
                    </div>
                    <div className="error-actions">
                      <button className="btn btn-primary" onClick={handleRetry}>🔄 Try Again</button>
                      <button className="btn btn-secondary" onClick={handleNewSearch}>📅 New Search</button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {appState === 'success' && results && !loading && (
          <div className="results-section">
            <div className="results-header">
              <button className="btn btn-secondary new-search-btn" onClick={handleNewSearch}>📅 New Search</button>
            </div>
            {Array.isArray(results.orders) && results.orders.length > 0 ? (
              <StatsPanel data={results} />
            ) : (
              <div className="no-orders-section">
                <div className="no-orders-card">
                  <div className="no-orders-icon">📭</div>
                  <div className="no-orders-content">
                    <h3>No Order Awards Found</h3>
                    <p>
                      Analyzed {results.total_announcements?.toLocaleString() || 0} announcements
                      but found no order wins on {formattedDate}
                    </p>
                    <div className="no-orders-suggestions">
                      <h4>💡 This could mean:</h4>
                      <ul>
                        <li>• It was a non-trading day or holiday</li>
                        <li>• No companies received significant orders</li>
                        <li>• Orders were announced under different categories</li>
                        <li>• Companies delayed their announcements</li>
                      </ul>
                    </div>
                    <button className="btn btn-primary" onClick={handleNewSearch}>📅 Try Another Date</button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </main>
      <Footer />
    </div>
  )
}

export default App