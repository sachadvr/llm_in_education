<template>
  <main class="mx-auto w-full max-w-[1160px] px-6 pb-20 pt-12">

    <!-- Header -->
    <div class="mb-12 text-center">
      <p class="text-xs uppercase tracking-[0.3em] mb-3" style="color: var(--warm)">QCM adaptatif</p>
      <h1 class="text-3xl font-semibold tracking-tight sm:text-4xl" style="color: var(--text)">Exercices ciblés</h1>
      <p class="mt-3 text-sm" style="color: var(--text-dim)">
        Priorité aux révisions dues · feedback pédagogique structuré · suivi de maîtrise
      </p>
    </div>

    <div class="grid gap-6 lg:grid-cols-[1fr_320px] lg:items-start">

      <!-- Main quiz card -->
      <div class="glass-card rounded-3xl overflow-hidden">

        <!-- Question area -->
        <div class="px-6 py-5 border-b" style="border-color: var(--border)">
          <div class="traffic-lights"><span style="background:#ff5f57"></span><span style="background:#febc2e"></span><span style="background:#28c840"></span></div>
          <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-3">
              <span v-if="errorType" class="text-[10px] uppercase tracking-widest px-2 py-1 rounded" style="background: var(--warm-dim); color: var(--warm)">{{ errorType }}</span>
              <span v-if="isDueReview" class="text-[10px] uppercase tracking-widest px-2 py-1 rounded" style="background: rgba(251,146,60,0.2); color: var(--warm)">révision due</span>
            </div>
            <button @click="fetchQuiz" class="text-[11px] transition hover:opacity-70" style="color: var(--text-dim)">
              nouvelle question →
            </button>
          </div>
          <div class="text-base leading-relaxed" style="color: var(--text)">{{ inputText }}</div>
        </div>

        <!-- Options -->
        <div class="p-4 space-y-2">
          <label v-for="(opt, idx) in options" :key="idx"
            class="flex items-center gap-3 rounded-lg px-4 py-3 cursor-pointer transition-all"
            :style="optionStyle(opt)"
          >
            <input type="radio" name="qcm" :value="opt" v-model="selectedAnswer" class="opacity-0 absolute" />
            <span class="h-4 w-4 rounded-full border grid place-items-center shrink-0 transition-all"
              :style="selectedAnswer === opt
                ? 'border-color: var(--accent); background: var(--accent)'
                : 'border-color: var(--border)'"
            >
              <span v-if="selectedAnswer === opt" class="h-2 w-2 rounded-full" style="background: var(--bg)"></span>
            </span>
            <span class="text-sm">{{ opt }}</span>
          </label>
        </div>

        <!-- Submit -->
        <div class="px-4 pb-4">
          <button @click="submitQuiz" :disabled="submitting || !selectedAnswer"
            class="w-full rounded-lg py-3 text-sm font-medium transition-all"
            style="background: var(--accent); color: var(--bg)"
            :class="(!selectedAnswer || submitting) ? 'opacity-40 cursor-not-allowed' : 'hover:opacity-90'"
          >
            {{ submitting ? 'Évaluation...' : 'Valider' }}
          </button>
        </div>

        <!-- Feedback -->
        <transition name="slide-up">
          <div v-if="feedbackData" class="border-t" style="border-color: var(--border)">

            <!-- Result header -->
            <div class="px-5 py-4 flex items-start justify-between border-b" style="border-color: var(--border)"
              :style="feedbackData.is_correct ? 'background: var(--success-dim)' : 'background: rgba(248,113,113,0.06)'"
            >
              <div>
                <div class="flex items-center gap-2 mb-1">
                  <span class="text-sm font-medium" :style="feedbackData.is_correct ? 'color: var(--success)' : 'color: var(--danger)'">
                    {{ feedbackData.is_correct ? '✓ Correct' : '✗ Incorrect' }}
                  </span>
                  <span v-if="!feedbackData.is_correct" class="text-[11px]" style="color: var(--text-dim)">
                    → {{ feedbackData.correct_answer }}
                  </span>
                </div>
                <p v-if="feedbackData.feedback?.rule" class="text-xs font-medium" style="color: var(--text)">{{ feedbackData.feedback.rule }}</p>
              </div>
              <!-- Mastery badge -->
              <div v-if="masteryUpdate" class="text-right shrink-0 ml-4">
                <div class="flex items-center gap-1 justify-end mb-1">
                  <span v-for="i in 5" :key="i"
                    class="h-2 w-2 rounded-full transition-all duration-500"
                    :style="i <= masteryUpdate.new_level
                      ? 'background: var(--accent); box-shadow: 0 0 6px var(--accent)'
                      : 'border: 1px solid rgba(255,255,255,0.12)'"
                  ></span>
                </div>
                <p class="text-[10px]" style="color: var(--text-dim)">
                  {{ masteryUpdate.message }}
                </p>
              </div>
            </div>

            <!-- Pedagogical feedback -->
            <div class="p-5 space-y-3 text-sm">
              <div v-if="feedbackData.feedback?.explanation" class="leading-relaxed" style="color: var(--text-dim)">
                {{ feedbackData.feedback.explanation }}
              </div>
              <div v-if="feedbackData.feedback?.example" class="rounded-lg px-4 py-3 font-mono text-xs" style="background: var(--accent-dim); color: var(--accent)">
                ex. {{ feedbackData.feedback.example }}
              </div>
              <div v-if="feedbackData.feedback?.hint" class="text-xs" style="color: var(--pipeline)">
                → {{ feedbackData.feedback.hint }}
              </div>
            </div>
          </div>
        </transition>

      </div>

      <!-- Side panel -->
      <div class="space-y-4">

        <!-- Session stats -->
        <div class="glass-card rounded-3xl p-5">
          <p class="text-[10px] uppercase tracking-widest mb-4" style="color: var(--text-dim)">Session</p>
          <div class="grid grid-cols-2 gap-3">
            <div class="rounded-lg p-3 text-center" style="background: rgba(255,255,255,0.03)">
              <p class="text-xl font-medium tabular-nums" style="color: var(--text)">{{ sessionStats.correct }}</p>
              <p class="text-[10px] mt-0.5" style="color: var(--success)">corrects</p>
            </div>
            <div class="rounded-lg p-3 text-center" style="background: rgba(255,255,255,0.03)">
              <p class="text-xl font-medium tabular-nums" style="color: var(--text)">{{ sessionStats.total }}</p>
              <p class="text-[10px] mt-0.5" style="color: var(--text-dim)">total</p>
            </div>
          </div>
          <div class="mt-3 h-1 rounded-full overflow-hidden" style="background: var(--border)">
            <div class="h-full rounded-full transition-all duration-500"
              :style="`width: ${sessionStats.total ? Math.round(sessionStats.correct / sessionStats.total * 100) : 0}%; background: var(--success)`"
            ></div>
          </div>
        </div>

        <!-- Similar errors from memory -->
        <div v-if="similarErrors.length" class="glass-card rounded-3xl overflow-hidden">
          <div class="px-4 py-3 border-b flex items-center gap-2" style="border-color: var(--border); background: var(--bg-card)">
            <span class="text-[10px] uppercase tracking-widest" style="color: var(--pipeline)">Mémoire pgvector</span>
            <span class="text-[10px] rounded px-1.5 py-0.5" style="background: var(--pipeline-dim); color: var(--pipeline)">{{ similarErrors.length }}</span>
          </div>
          <div class="divide-y" style="border-color: var(--border)">
            <div v-for="(err, idx) in similarErrors" :key="idx" class="px-4 py-3">
              <p class="text-xs leading-relaxed mb-1" style="color: var(--text-dim)">{{ err.original || err.input_text || '—' }}</p>
              <p class="text-xs" style="color: var(--accent)">→ {{ err.corrected || '—' }}</p>
              <p v-if="err.error_type" class="text-[10px] mt-1" style="color: var(--text-dim2)">{{ err.error_type }}</p>
            </div>
          </div>
        </div>

        <!-- Pipeline source -->
        <div class="glass-card rounded-3xl p-4 text-[11px] space-y-2" style="color: var(--text-dim)">
          <p class="uppercase tracking-widest text-[10px] mb-3" style="color: var(--text-dim)">Pipeline</p>
          <div class="flex justify-between"><span>Source</span><span style="color: var(--pipeline)">{{ lastSource || '—' }}</span></div>
          <div class="flex justify-between"><span>Type cible</span><span style="color: var(--warm)">{{ errorType || '—' }}</span></div>
          <div class="flex justify-between"><span>Mode</span><span style="color: var(--accent)">{{ isDueReview ? 'spaced rep.' : 'weak area' }}</span></div>
        </div>

      </div>
    </div>
  </main>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { apiConfig, apiFetch } from '../config/api.js'

defineProps({ apiStatusLabel: String, apiStatusClass: String })

const inputText = ref('Chargement...')
const options = ref([])
const correctAnswer = ref('')
const selectedAnswer = ref(null)
const questionId = ref('')
const errorType = ref('')
const feedbackData = ref(null)
const submitting = ref(false)
const similarErrors = ref([])
const masteryUpdate = ref(null)
const isDueReview = ref(false)
const lastSource = ref('')

const sessionStats = reactive({ correct: 0, total: 0 })

function getSessionId() {
  let sid = sessionStorage.getItem('mvp_session_id')
  if (!sid) { sid = crypto.randomUUID ? crypto.randomUUID() : `s${Date.now()}`; sessionStorage.setItem('mvp_session_id', sid) }
  return sid
}

function optionStyle(opt) {
  const base = 'border: 1px solid; '
  if (!feedbackData.value) {
    return base + (selectedAnswer.value === opt
      ? 'border-color: var(--accent); background: var(--accent-dim); color: var(--text)'
      : 'border-color: var(--border); background: var(--bg-card); color: var(--text-dim)')
  }
  if (opt === correctAnswer.value) return base + 'border-color: var(--success); background: var(--success-dim); color: var(--success)'
  if (opt === selectedAnswer.value && opt !== correctAnswer.value) return base + 'border-color: var(--danger); background: rgba(248,113,113,0.08); color: var(--danger)'
  return base + 'border-color: var(--border); background: transparent; color: var(--text-dim2); opacity: 0.5'
}

const fetchSimilarErrors = async () => {
  try {
    const r = await apiFetch(`${apiConfig.endpoints.quizSimilarErrors}?input_text=${encodeURIComponent(inputText.value)}&error_type=${encodeURIComponent(errorType.value || '')}&k=3`, { headers: { 'X-Session-Id': getSessionId() } })
    const data = await r.json()
    if (r.ok) similarErrors.value = data.similar_errors || []
  } catch { similarErrors.value = [] }
}

const fetchQuiz = async () => {
  feedbackData.value = null
  masteryUpdate.value = null
  selectedAnswer.value = null
  similarErrors.value = []
  isDueReview.value = false
  try {
    const r = await apiFetch(apiConfig.endpoints.quiz, {
      headers: { 'X-Session-Id': getSessionId() }
    })
    const data = await r.json()
    if (!r.ok) throw new Error(data.detail || r.statusText)
    inputText.value = data.input_text
    options.value = data.options
    correctAnswer.value = data.correct_answer
    questionId.value = data.question_id
    errorType.value = data.error_type
    lastSource.value = data.source || 'pipeline'
    await fetchSimilarErrors()
  } catch (e) {
    inputText.value = `Erreur: ${e.message}`
  }
}

const submitQuiz = async () => {
  if (!selectedAnswer.value) return
  submitting.value = true
  try {
    const r = await apiFetch(apiConfig.endpoints.quizSubmit, {
      method: 'POST',
      headers: { 'X-Session-Id': getSessionId() },
      body: JSON.stringify({
        question_id: questionId.value,
        input_text: inputText.value,
        user_answer: selectedAnswer.value,
        correct_answer: correctAnswer.value,
        error_type: errorType.value
      })
    })
    const data = await r.json()
    if (!r.ok) throw new Error(data.detail || r.statusText)

    feedbackData.value = {
      is_correct: data.is_correct,
      correct_answer: correctAnswer.value,
      feedback: data.feedback,
      error_type: data.error_type,
    }

    sessionStats.total++
    if (data.is_correct) {
      sessionStats.correct++
      // Fetch updated mastery level from progression
      try {
        const progRes = await apiFetch(apiConfig.endpoints.learnerProgress(getSessionId()))
        const progData = await progRes.json()
        const updated = (progData.error_history || []).find(e => e.error_type === errorType.value)
        if (updated) {
          masteryUpdate.value = {
            new_level: updated.mastery_level || 0,
            message: `maîtrise niveau ${updated.mastery_level}/4 · prochaine révision dans ${updated.next_review_in_days ?? updated.interval_days}j`
          }
        }
      } catch {}
    }

    lastSource.value = data.source || 'pipeline'
  } catch (e) {
    feedbackData.value = { is_correct: false, correct_answer: '', feedback: { rule: `Erreur: ${e.message}` }, error_type: '' }
  }
  submitting.value = false
}

onMounted(fetchQuiz)
</script>

<style scoped>
.slide-up-enter-active { transition: all 0.3s ease-out; }
.slide-up-enter-from { opacity: 0; transform: translateY(8px); }
</style>
