import axios from 'axios'

// Use env if present; fallback to localhost for dev
const API = axios.create({ baseURL: import.meta.env.VITE_API_URL || 'http://localhost:5000' })

// Simple demo auth header
API.interceptors.request.use(cfg => { cfg.headers['X-User-Id'] = 'U123'; return cfg })

export const login         = (userId='U123', name='Demo User') => API.post('/auth/login', { userId, name })
export const getPlan       = () => API.get('/me/plan').then(r => r.data)
export const completePlan  = () => API.post('/me/plan/complete').then(r => r.data)
export const getRecs       = () => API.get('/me/recommendations').then(r => r.data)
export const makeNudge     = () => API.post('/me/nudge').then(r => r.data)
export const ingest        = (metricType, value) => API.post('/me/metrics', { metricType, value })
export const listMetrics   = () => API.get('/me/metrics').then(r => r.data)

// NEW: one-per-day steps endpoint
export const setSteps      = (value) => API.post('/me/metrics/steps', { value }).then(r => r.data)
