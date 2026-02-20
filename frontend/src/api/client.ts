/**
 * API Client for VibeDispatch
 *
 * Handles all HTTP communication with the Flask backend.
 */

import { getErrorMessage } from '../utils'

export interface ApiClientConfig {
  baseUrl: string
  getAuthKey?: () => string | null
}

export interface ApiError extends Error {
  status?: number
  response?: unknown
}

/**
 * Create an API client instance
 */
export function createApiClient(config: ApiClientConfig) {
  const { baseUrl, getAuthKey } = config

  async function request<T>(method: 'GET' | 'POST', endpoint: string, data?: unknown): Promise<T> {
    const url = `${baseUrl}${endpoint}`

    const headers: HeadersInit = {
      'Content-Type': 'application/json'
    }

    // Add auth key if available
    const authKey = getAuthKey?.()
    if (authKey) {
      headers['X-User-Key'] = authKey
    }

    const options: RequestInit = {
      method,
      headers,
      credentials: 'include' // Include cookies for CORS
    }

    if (data && method === 'POST') {
      options.body = JSON.stringify(data)
    }

    try {
      const response = await fetch(url, options)

      if (!response.ok) {
        const error: ApiError = new Error(`API error: ${response.status} ${response.statusText}`)
        error.status = response.status
        try {
          error.response = await response.json()
        } catch {
          // Response wasn't JSON
        }
        throw error
      }

      return (await response.json()) as T
    } catch (err) {
      if (err instanceof Error && 'status' in err) {
        throw err // Re-throw API errors
      }
      // Network or other errors
      const error: ApiError = new Error(`Network error: ${getErrorMessage(err)}`)
      throw error
    }
  }

  return {
    /**
     * Make a GET request
     */
    get: <T>(endpoint: string): Promise<T> => request<T>('GET', endpoint),

    /**
     * Make a POST request
     */
    post: <T>(endpoint: string, data?: unknown): Promise<T> => request<T>('POST', endpoint, data)
  }
}

// ============ Default Client ============

// Auth key from URL params or sessionStorage (like old getAdminKey)
function getAuthKey(): string | null {
  if (typeof window === 'undefined') return null

  // Check URL params first (like old getAdminKey)
  const params = new URLSearchParams(window.location.search)
  const keyFromUrl = params.get('key')
  if (keyFromUrl) {
    // Store in sessionStorage for subsequent requests
    sessionStorage.setItem('dispatch_key', keyFromUrl)
    return keyFromUrl
  }

  return sessionStorage.getItem('dispatch_key')
}

// Determine base URL based on environment
function getBaseUrl(): string {
  // Vite proxy handles /dispatch/* routes in dev
  // In production, same origin with /dispatch prefix
  return '/dispatch'
}

/**
 * Default API client instance
 */
export const apiClient = createApiClient({
  baseUrl: getBaseUrl(),
  getAuthKey
})
