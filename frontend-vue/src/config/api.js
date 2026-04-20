// Configuration API
// En Docker : backend accessible sur localhost:8000

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export const apiConfig = {
  baseUrl: API_BASE_URL,
  endpoints: {
    health: '/health',
    correct: '/correct',
    exercise: '/exercise',
    exerciseAdaptive: '/exercise/adaptive',
    exerciseGrade: '/exercise/grade',
    quiz: '/quiz',
    quizSubmit: '/quiz/submit',
    quizSimilarErrors: '/quiz/similar-errors',
    learnerProgress: (userId) => `/learner/${encodeURIComponent(userId)}/progress`,
    session: '/api/session',
    datasetStats: '/api/dataset/stats',
    analytics: {
      heatmap: '/api/analytics/error-heatmap',
      trends: '/api/analytics/learner-trends',
      distribution: '/api/analytics/error-distribution',
      systemMetrics: '/api/analytics/system-metrics'
    },
    benchmarks: {
      run: '/api/benchmark/run',
      compare: '/api/benchmark/compare',
      latest: '/api/benchmark/latest'
    },
    evaluate: '/api/evaluate',
    feedbackRate: '/feedback/rate',
    ollama: '/config/ollama',
    login: '/login',
    register: '/register',
    logout: '/logout',
    me: '/me'
  }
}

export function getApiUrl(endpoint) {
  return `${API_BASE_URL}${endpoint}`
}

// Helper pour fetch avec l'URL de base
export async function apiFetch(endpoint, options = {}) {
  const url = getApiUrl(endpoint)
  const response = await fetch(url, {
    credentials: 'include',
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    }
  })
  return response
}
