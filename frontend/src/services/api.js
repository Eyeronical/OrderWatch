import DOMPurify from 'dompurify'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5001'
const API_KEY = import.meta.env.VITE_API_KEY || null
const REQUEST_TIMEOUT = parseInt(import.meta.env.VITE_REQUEST_TIMEOUT) || 30000
const IS_PRODUCTION = import.meta.env.PROD
const MAX_RETRY_ATTEMPTS = 3
const RETRY_DELAY = 1000

const ENDPOINTS = {
  HEALTH: '/api/health',
  SCRAPE: '/api/scrape',
  STATUS: '/api/status',
  RESULTS: '/api/results',
  STOP: '/api/stop'
}

class ApiError extends Error {
  constructor(message, status, data = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

const sanitizeInput = (input) => {
  if (typeof input === 'string') {
    return DOMPurify.sanitize(input.trim(), { ALLOWED_TAGS: [], ALLOWED_ATTR: [] })
  }
  if (Array.isArray(input)) {
    return input.map(sanitizeInput)
  }
  if (input && typeof input === 'object') {
    const sanitized = {}
    for (const [key, value] of Object.entries(input)) {
      sanitized[key] = sanitizeInput(value)
    }
    return sanitized
  }
  return input
}

const validateResponse = (response, expectedKeys = []) => {
  if (!response || typeof response !== 'object') {
    throw new ApiError('Invalid response format', 0)
  }
  for (const key of expectedKeys) {
    if (!(key in response)) {
      throw new ApiError(`Missing required field: ${key}`, 0)
    }
  }
  return true
}

const safeLog = (level, message, data = null) => {
  if (IS_PRODUCTION) return
  const timestamp = new Date().toISOString()
  const logData = data ? (typeof data === 'object' ? JSON.stringify(data, null, 2) : data) : ''
  if (level === 'error') {
    console.error(`[${timestamp}] API Error: ${message}`, logData)
  } else {
    console.log(`[${timestamp}] API Info: ${message}`, logData)
  }
}

const activeRequests = new Map()
const getRequestKey = (url, options) => `${options.method || 'GET'}:${url}:${JSON.stringify(options.body || {})}`

const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms))

const makeRequestWithRetry = async (url, options = {}, attempt = 1) => {
  try {
    return await makeRequest(url, options)
  } catch (error) {
    if (attempt >= MAX_RETRY_ATTEMPTS) throw error
    const shouldRetry = error.status === 0 || error.status >= 500 || error.name === 'AbortError'
    if (!shouldRetry) throw error
    const retryDelay = RETRY_DELAY * Math.pow(2, attempt - 1)
    safeLog('info', `Retrying request in ${retryDelay}ms (attempt ${attempt}/${MAX_RETRY_ATTEMPTS})`)
    await delay(retryDelay)
    return makeRequestWithRetry(url, options, attempt + 1)
  }
}

const makeRequest = async (url, options = {}) => {
  if (!url || typeof url !== 'string') {
    throw new ApiError('Invalid URL provided', 400)
  }
  const requestKey = getRequestKey(url, options)
  if (activeRequests.has(requestKey)) {
    return activeRequests.get(requestKey)
  }

  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT)

  const requestPromise = (async () => {
    try {
      if (options.body) {
        try {
          const bodyData = JSON.parse(options.body)
          const sanitizedData = sanitizeInput(bodyData)
          options.body = JSON.stringify(sanitizedData)
        } catch {
          options.body = sanitizeInput(options.body)
        }
      }

      const defaultHeaders = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      }
      if (API_KEY) {
        defaultHeaders['X-API-Key'] = API_KEY
      }
      defaultHeaders['Cache-Control'] = 'no-cache'
      defaultHeaders['Pragma'] = 'no-cache'

      const defaultOptions = {
        credentials: 'same-origin',
        signal: controller.signal,
        headers: defaultHeaders
      }

      const response = await fetch(`${API_BASE_URL}${url}`, {
        ...defaultOptions,
        ...options,
        headers: { ...defaultHeaders, ...options.headers }
      })

      clearTimeout(timeoutId)

      if (response.status === 429) {
        const retryAfter = response.headers.get('Retry-After')
        const retryDelay = retryAfter ? parseInt(retryAfter) * 1000 : 5000
        throw new ApiError(`Rate limited. Please wait ${Math.ceil(retryDelay / 1000)} seconds.`, 429)
      }

      if (!response.ok) {
        let errorMessage = `HTTP ${response.status}: ${response.statusText}`
        let errorData = null
        try {
          errorData = await response.json()
          errorMessage = sanitizeInput(errorData.error || errorData.message || errorMessage)
          errorData = sanitizeInput(errorData)
        } catch {}
        throw new ApiError(errorMessage, response.status, errorData)
      }

      const contentType = response.headers.get('content-type')
      let responseData
      if (contentType && contentType.includes('application/json')) {
        responseData = await response.json()
        responseData = sanitizeInput(responseData)
      } else {
        responseData = await response.text()
        responseData = sanitizeInput(responseData)
      }
      return responseData
    } catch (error) {
      clearTimeout(timeoutId)
      if (error.name === 'AbortError') {
        throw new ApiError('Request timeout - server is taking too long to respond', 408)
      }
      if (error instanceof ApiError) {
        throw error
      }
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        throw new ApiError('Unable to connect to server. Please check if the server is running.', 0)
      }
      throw new ApiError(sanitizeInput(error.message) || 'An unexpected error occurred', 0)
    } finally {
      activeRequests.delete(requestKey)
    }
  })()

  activeRequests.set(requestKey, requestPromise)
  return requestPromise
}

const apiService = {
  async checkHealth() {
    try {
      const response = await makeRequestWithRetry(ENDPOINTS.HEALTH, { method: 'GET' })
      validateResponse(response, ['status'])
      safeLog('info', 'API Health Check Success', { status: response.status, timestamp: response.timestamp })
      return { success: true, data: response, message: 'Server is healthy' }
    } catch (error) {
      safeLog('error', 'API Health Check Failed', { message: error.message, status: error.status })
      return { success: false, error: error.message, status: error.status || 0 }
    }
  },

  async startScraping(date) {
    try {
      const sanitizedDate = sanitizeInput(date)
      if (!sanitizedDate || typeof sanitizedDate !== 'string') {
        throw new ApiError('Date is required', 400)
      }
      if (!/^\d{4}-\d{2}-\d{2}$/.test(sanitizedDate)) {
        throw new ApiError('Invalid date format. Please use YYYY-MM-DD format.', 400)
      }
      const dateObj = new Date(sanitizedDate)
      const today = new Date()
      const minDate = new Date('2010-01-01')
      if (isNaN(dateObj.getTime())) {
        throw new ApiError('Invalid date provided', 400)
      }
      if (dateObj > today) {
        throw new ApiError('Date cannot be in the future', 400)
      }
      if (dateObj < minDate) {
        throw new ApiError('Date cannot be before 2010', 400)
      }
      const response = await makeRequestWithRetry(ENDPOINTS.SCRAPE, {
        method: 'POST',
        body: JSON.stringify({ date: sanitizedDate })
      })
      validateResponse(response, ['message'])
      safeLog('info', 'Scraping Started', { date: sanitizedDate, message: response.message })
      return { success: true, data: response, message: 'Scraping started successfully' }
    } catch (error) {
      safeLog('error', 'Failed to Start Scraping', { date: date, error: error.message, status: error.status })
      return { success: false, error: error.message, status: error.status || 0 }
    }
  },

  async getScrapingStatus() {
    try {
      const response = await makeRequest(ENDPOINTS.STATUS, { method: 'GET' })
      validateResponse(response, ['is_running'])
      return {
        success: true,
        data: response,
        isRunning: Boolean(response.is_running),
        progress: Math.max(0, Math.min(100, Number(response.progress) || 0)),
        message: sanitizeInput(response.message) || 'Status retrieved successfully'
      }
    } catch (error) {
      safeLog('error', 'Failed to Get Status', { error: error.message, status: error.status })
      return { success: false, error: error.message, status: error.status || 0, isRunning: false, progress: 0 }
    }
  },

  async getResults() {
    try {
      const response = await makeRequest(ENDPOINTS.RESULTS, { method: 'GET' })
      if (!(response && typeof response === 'object' && response.success === true && Array.isArray(response.orders))) {
        throw new ApiError('Results not ready', 202)
      }
      safeLog('info', 'Results Retrieved', {
        totalAwards: response.total_awards,
        totalValue: response.total_value_crores,
        date: response.date
      })
      return { success: true, data: response, message: 'Results retrieved successfully' }
    } catch (error) {
      safeLog('error', 'Failed to Get Results', { error: error.message, status: error.status })
      return { success: false, error: error.message, status: error.status || 0 }
    }
  },

  async stopScraping() {
    try {
      const response = await makeRequest(ENDPOINTS.STOP, { method: 'POST' })
      safeLog('info', 'Scraping Stopped', response)
      return { success: true, data: response, message: 'Scraping stopped successfully' }
    } catch (error) {
      safeLog('error', 'Failed to Stop Scraping', { error: error.message, status: error.status })
      return { success: false, error: error.message, status: error.status || 0 }
    }
  },

  async pollScrapingProgress(onProgress, pollInterval = 2000) {
    if (onProgress && typeof onProgress !== 'function') {
      throw new ApiError('onProgress must be a function', 400)
    }
    const safePollInterval = Math.max(1000, Math.min(10000, pollInterval))
    return new Promise((resolve) => {
      let pollCount = 0
      const maxPolls = 300
      const poll = async () => {
        try {
          pollCount++
          if (pollCount > maxPolls) {
            resolve({ success: false, error: 'Polling timeout - operation took too long', status: 408 })
            return
          }
          const statusResponse = await this.getScrapingStatus()
          if (!statusResponse.success) {
            resolve({ success: false, error: statusResponse.error, status: statusResponse.status })
            return
          }
          const { data, isRunning, progress } = statusResponse
          if (onProgress) {
            try {
              onProgress({ isRunning, progress, message: data.message, error: data.error })
            } catch (callbackError) {
              safeLog('error', 'Progress callback error', callbackError.message)
            }
          }
          if (!isRunning) {
            if (data.error) {
              resolve({ success: false, error: data.error, message: data.message })
              return
            }
            if (data.results) {
              resolve({ success: true, data: data.results, message: 'Scraping completed successfully' })
              return
            }
            const resultsResponse = await this.getResults()
            if (!resultsResponse.success) {
              setTimeout(poll, safePollInterval)
              return
            }
            resolve(resultsResponse)
            return
          }
          setTimeout(poll, safePollInterval)
        } catch (error) {
          resolve({ success: false, error: error.message || 'Polling failed', status: 0 })
        }
      }
      poll()
    })
  }
}

export const utils = {
  formatDate(dateString) {
    try {
      const sanitizedDate = sanitizeInput(dateString)
      const date = new Date(sanitizedDate)
      if (isNaN(date.getTime())) {
        return 'Invalid Date'
      }
      return date.toLocaleDateString('en-US', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      })
    } catch {
      return 'Invalid Date'
    }
  },

  formatCurrency(amount) {
    const safeAmount = Number(amount)
    if (isNaN(safeAmount) || safeAmount < 0) {
      return '₹0.00 Cr'
    }
    if (safeAmount >= 1000) {
      return `₹${(safeAmount / 1000).toFixed(1)}K Cr`
    }
    return `₹${safeAmount.toFixed(2)} Cr`
  },

  isWeekend(dateString) {
    try {
      const sanitizedDate = sanitizeInput(dateString)
      const date = new Date(sanitizedDate)
      if (isNaN(date.getTime())) {
        return false
      }
      const day = date.getDay()
      return day === 0 || day === 6
    } catch {
      return false
    }
  },

  validateDate(dateString) {
    const sanitizedDate = sanitizeInput(dateString)
    if (!sanitizedDate) {
      return { isValid: false, error: 'Date is required' }
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(sanitizedDate)) {
      return { isValid: false, error: 'Invalid date format. Use YYYY-MM-DD' }
    }
    const date = new Date(sanitizedDate)
    const today = new Date()
    const minDate = new Date('2010-01-01')
    if (isNaN(date.getTime())) {
      return { isValid: false, error: 'Invalid date' }
    }
    if (date > today) {
      return { isValid: false, error: 'Date cannot be in the future' }
    }
    if (date < minDate) {
      return { isValid: false, error: 'Date cannot be before 2010' }
    }
    const isWeekendDate = this.isWeekend(sanitizedDate)
    return {
      isValid: true,
      isWeekend: isWeekendDate,
      warning: isWeekendDate ? 'Selected date is a weekend - markets may be closed' : null
    }
  }
}

export const useApi = () => ({ ...apiService, utils })
export default apiService
export const { checkHealth, startScraping, getScrapingStatus, getResults, stopScraping, pollScrapingProgress } = apiService
export { ApiError }

export const API_STATUS = {
  IDLE: 'idle',
  LOADING: 'loading',
  SUCCESS: 'success',
  ERROR: 'error',
  TIMEOUT: 'timeout'
}

export const HTTP_STATUS = {
  OK: 200,
  CREATED: 201,
  BAD_REQUEST: 400,
  UNAUTHORIZED: 401,
  FORBIDDEN: 403,
  NOT_FOUND: 404,
  TIMEOUT: 408,
  TOO_MANY_REQUESTS: 429,
  INTERNAL_SERVER_ERROR: 500,
  BAD_GATEWAY: 502,
  SERVICE_UNAVAILABLE: 503,
  GATEWAY_TIMEOUT: 504
}

export const RESPONSE_SCHEMAS = {
  HEALTH: ['status', 'message'],
  SCRAPE_START: ['message'],
  STATUS: ['is_running', 'progress', 'message'],
  RESULTS: ['success', 'date', 'total_awards'],
  STOP: ['message']
}

const validateConfig = () => {
  if (!API_BASE_URL) {
    throw new Error('API_BASE_URL is required')
  }
  try {
    new URL(API_BASE_URL)
  } catch {
    throw new Error('Invalid API_BASE_URL format')
  }
  if (IS_PRODUCTION && !API_KEY) {
    console.warn('⚠️ No API key configured for production environment')
  }
}

try {
  validateConfig()
} catch (error) {
  console.error('❌ API Configuration Error:', error.message)
  throw error
}

export const API_CONFIG = {
  BASE_URL: API_BASE_URL,
  HAS_API_KEY: !!API_KEY,
  TIMEOUT: REQUEST_TIMEOUT,
  IS_PRODUCTION,
  MAX_RETRIES: MAX_RETRY_ATTEMPTS
}