import { createRouter, createWebHistory } from 'vue-router'
import Home from './pages/Home.vue'
import Quiz from './pages/Quiz.vue'
import Progression from './pages/Progression.vue'
import Analytics from './pages/Analytics.vue'
import Benchmark from './pages/Benchmark.vue'
import Login from './pages/Login.vue'
import Register from './pages/Register.vue'
import { useAuth } from './composables/useAuth.js'

const PUBLIC_ROUTES = ['/login', '/register']
let sessionInitialized = false

const router = createRouter({
  history: createWebHistory('/'),
  routes: [
    { path: '/', component: Home },
    { path: '/quiz', component: Quiz },
    { path: '/progression', component: Progression },
    { path: '/analytics', component: Analytics },
    { path: '/benchmark', component: Benchmark },
    { path: '/login', component: Login },
    { path: '/register', component: Register }
  ]
})

router.beforeEach(async (to) => {
  const { isLoggedIn, checkSession } = useAuth()

  if (!sessionInitialized) {
    sessionInitialized = true
    await checkSession()
  }

  if (PUBLIC_ROUTES.includes(to.path)) {
    if (isLoggedIn.value) return '/'
    return true
  }

  if (!isLoggedIn.value) return '/login'
  return true
})

export default router
