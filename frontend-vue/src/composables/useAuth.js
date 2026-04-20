import { ref, computed } from 'vue'
import { apiConfig } from '../config/api'

const user = ref(null)
const isLoggedIn = computed(() => !!user.value)

export function useAuth() {
  const login = async (username, password) => {
    const response = await fetch(`${apiConfig.baseUrl}${apiConfig.endpoints.login}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, password })
    })

    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Login failed')
    }

    const data = await response.json()
    user.value = data.user || { username }
    return data
  }

  const register = async (username, password, displayName) => {
    const response = await fetch(`${apiConfig.baseUrl}${apiConfig.endpoints.register}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        username,
        password,
        display_name: displayName || username
      })
    })

    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Registration failed')
    }

    return await response.json()
  }

  const logout = async () => {
    try {
      await fetch(`${apiConfig.baseUrl}${apiConfig.endpoints.logout}`, {
        method: 'POST',
        credentials: 'include'
      })
    } catch (e) {
      // Ignore errors
    }
    user.value = null
    window.location.href = '/'
  }

  const checkSession = async () => {
    try {
      const response = await fetch(`${apiConfig.baseUrl}${apiConfig.endpoints.me}`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        user.value = { id: data.user_id, username: data.username }
      } else {
        user.value = null
      }
    } catch (e) {
      user.value = null
    }
  }

  return {
    user,
    isLoggedIn,
    login,
    register,
    logout,
    checkSession
  }
}
