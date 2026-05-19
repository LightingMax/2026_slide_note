import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import {
  cancelAgentRun,
  clearDeckMemory,
  createAgentRun,
  exportDeck,
  fetchAgentStyles,
  fetchDecks,
  renderDeck,
  resetSlideNotes,
  updateSlideNotes,
  uploadDeck
} from '@/api/decks'
import type { ActivityItem, AgentAction, AgentResponse, AgentStylePreset, ChatMessage, Deck, Slide } from '@/types/deck'

const chatStorageKey = 'slide-note-chat-history'
const activityStorageKey = 'slide-note-activity-log'

type ChatHistory = Record<string, ChatMessage[]>

export const useDeckStore = defineStore('deck', () => {
  const decks = ref<Deck[]>([])
  const activeDeck = ref<Deck | null>(null)
  const activeSlideId = ref<string>('')
  const loading = ref(false)
  const chatMessages = ref<ChatMessage[]>([])
  const chatHistory = ref<ChatHistory>(loadJson<ChatHistory>(chatStorageKey, {}))
  const activityLog = ref<ActivityItem[]>(loadJson<ActivityItem[]>(activityStorageKey, []))
  const agentStyles = ref<AgentStylePreset[]>([])
  const agentRunning = ref(false)
  const activeRunId = ref<string>('')
  let activeEventSource: EventSource | null = null

  const activeSlide = computed<Slide | null>(() => {
    return activeDeck.value?.slides.find((slide) => slide.id === activeSlideId.value) ?? null
  })

  const activeChatKey = computed(() => {
    if (!activeDeck.value) return ''
    return activeDeck.value.id
  })

  watch(activeChatKey, (key) => {
    chatMessages.value = key ? [...(chatHistory.value[key] ?? [])] : []
  })

  watch(
    chatMessages,
    (messages) => {
      if (!activeChatKey.value) return
      chatHistory.value = { ...chatHistory.value, [activeChatKey.value]: messages }
      localStorage.setItem(chatStorageKey, JSON.stringify(chatHistory.value))
    },
    { deep: true }
  )

  watch(
    activityLog,
    (items) => {
      localStorage.setItem(activityStorageKey, JSON.stringify(items.slice(0, 80)))
    },
    { deep: true }
  )

  async function loadDecks() {
    agentStyles.value = await fetchAgentStyles()
    decks.value = await fetchDecks()
    if (!activeDeck.value && decks.value.length > 0) {
      setDeck(decks.value[0])
    }
  }

  function setDeck(deck: Deck) {
    activeDeck.value = deck
    activeSlideId.value = deck.slides[0]?.id || ''
    addActivity('打开演示文稿', `${deck.filename}，共 ${deck.slides.length} 页`)
  }

  async function upload(file: File) {
    loading.value = true
    try {
      const deck = await uploadDeck(file)
      decks.value = [deck, ...decks.value.filter((item) => item.id !== deck.id)]
      setDeck(deck)
      addActivity('解析 PPT 完成', `读取 ${deck.slides.length} 页，包含备注、文本和媒体关系`)
    } finally {
      loading.value = false
    }
  }

  async function saveNotes(notes: string) {
    if (!activeDeck.value || !activeSlideId.value) return
    activeDeck.value = await updateSlideNotes(activeDeck.value.id, activeSlideId.value, notes)
    syncActiveDeck()
    addActivity('保存备注', `${activeSlide.value?.title || '当前页'}，${notes.length} 字`)
  }

  async function resetActiveSlideNotes() {
    if (!activeDeck.value || !activeSlideId.value) return
    activeDeck.value = await resetSlideNotes(activeDeck.value.id, activeSlideId.value)
    syncActiveDeck()
    addActivity('重置当前页讲稿', `${activeSlide.value?.title || '当前页'} 已还原为 PPT 原始备注`)
  }

  async function exportActiveDeck() {
    if (!activeDeck.value) return
    const blob = await exportDeck(activeDeck.value.id)
    const name = activeDeck.value.filename.replace(/\.pptx$/i, '') || 'slide-note'
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${name}_slide-note.pptx`
    anchor.click()
    URL.revokeObjectURL(url)
    addActivity('导出 PPT', '已复制原始 PPT，并写入当前备注生成新文件')
  }

  async function rerenderSnapshots() {
    if (!activeDeck.value) return
    loading.value = true
    try {
      activeDeck.value = await renderDeck(activeDeck.value.id)
      syncActiveDeck()
      const status = activeDeck.value.slides.some((slide) => slide.render_status === 'ready')
        ? '已生成真实 PPT 快照'
        : '渲染服务暂不可用，已切换解析预览'
      addActivity('重新渲染快照', status)
    } finally {
      loading.value = false
    }
  }

  async function askAssistant(instruction: string): Promise<AgentResponse | null> {
    if (!activeDeck.value || !activeSlideId.value) return null
    if (agentRunning.value) return null
    chatMessages.value.push({ role: 'user', content: instruction })
    addActivity('发送生成要求', instruction)
    const run = await createAgentRun(
      activeDeck.value.id,
      activeSlideId.value,
      instruction,
      chatMessages.value,
      'auto'
    )
    activeRunId.value = run.run_id
    return streamAgentRun(run.run_id)
  }

  async function applyStyleTemplate(style: AgentStylePreset) {
    const instruction = `请把当前页讲稿迁移成「${style.name}」风格。风格要求：${style.description}`
    return askAssistant(instruction)
  }

  async function stopAgentRun() {
    if (!activeRunId.value) return
    await cancelAgentRun(activeRunId.value)
    activeEventSource?.close()
    activeEventSource = null
    addAgentMessage('已请求停止当前任务。')
    agentRunning.value = false
    activeRunId.value = ''
  }

  async function clearCurrentContext() {
    if (!activeDeck.value) return
    if (agentRunning.value) {
      await stopAgentRun()
    }
    await clearDeckMemory(activeDeck.value.id)
    const key = activeChatKey.value
    if (key) {
      const nextHistory = { ...chatHistory.value }
      delete nextHistory[key]
      chatHistory.value = nextHistory
      localStorage.setItem(chatStorageKey, JSON.stringify(nextHistory))
    }
    chatMessages.value = []
    addActivity('清除上下文', `${activeDeck.value.filename} 的会话历史和 PPT 记忆已清空`)
  }

  function addActivity(title: string, detail: string) {
    activityLog.value.unshift({
      id: crypto.randomUUID(),
      time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      title,
      detail
    })
    activityLog.value = activityLog.value.slice(0, 80)
  }

  function addAgentMessage(content: string) {
    chatMessages.value.push({ role: 'agent', content })
  }

  function applyAction(action: AgentAction) {
    if (!activeDeck.value || action.type !== 'replace_notes') return
    activeDeck.value = {
      ...activeDeck.value,
      slides: activeDeck.value.slides.map((slide) =>
        slide.id === action.slide_id ? { ...slide, notes: action.content } : slide
      )
    }
    syncActiveDeck()
  }

  function streamAgentRun(runId: string) {
    return new Promise<AgentResponse | null>((resolve, reject) => {
      const source = new EventSource(`/api/agent/runs/${runId}/events`)
      activeEventSource = source
      agentRunning.value = true
      let response: AgentResponse | null = null

      source.addEventListener('progress', (event) => {
        const payload = JSON.parse((event as MessageEvent).data) as { message: string }
        addAgentMessage(payload.message)
      })

      source.addEventListener('assistant', (event) => {
        response = JSON.parse((event as MessageEvent).data) as AgentResponse
        chatMessages.value.push({
          role: 'assistant',
          content: response.message,
          actions: response.actions,
          ui: response.ui
        })
        addActivity('生成备注草稿', `${activeSlide.value?.title || '当前页'}，${response.text.length} 字`)
      })

      source.addEventListener('action', (event) => {
        const action = JSON.parse((event as MessageEvent).data) as AgentAction
        applyAction(action)
        addAgentMessage(`动作完成：${action.label}`)
      })

      source.addEventListener('done', (event) => {
        const payload = JSON.parse((event as MessageEvent).data) as { deck: Deck }
        activeDeck.value = payload.deck
        syncActiveDeck()
        source.close()
        activeEventSource = null
        activeRunId.value = ''
        agentRunning.value = false
        resolve(response)
      })

      source.addEventListener('cancelled', (event) => {
        const payload = JSON.parse((event as MessageEvent).data) as { message: string }
        addAgentMessage(payload.message)
        source.close()
        activeEventSource = null
        activeRunId.value = ''
        agentRunning.value = false
        resolve(response)
      })

      source.addEventListener('error', (event) => {
        const message = (event as MessageEvent).data
          ? (JSON.parse((event as MessageEvent).data) as { message: string }).message
          : 'Agent run failed'
        chatMessages.value.push({ role: 'assistant', content: `请求失败：${message}` })
        addActivity('生成失败', message)
        source.close()
        activeEventSource = null
        activeRunId.value = ''
        agentRunning.value = false
        reject(new Error(message))
      })
    })
  }

  function syncActiveDeck() {
    decks.value = decks.value.map((deck) => (deck.id === activeDeck.value?.id ? activeDeck.value : deck))
  }

  return {
    decks,
    activeDeck,
    activeSlideId,
    activeSlide,
    loading,
    chatMessages,
    activityLog,
    agentStyles,
    agentRunning,
    loadDecks,
    setDeck,
    upload,
    saveNotes,
    resetActiveSlideNotes,
    exportActiveDeck,
    askAssistant,
    applyStyleTemplate,
    stopAgentRun,
    clearCurrentContext,
    rerenderSnapshots,
    addActivity,
    addAgentMessage
  }
})

function loadJson<T>(key: string, fallback: T): T {
  try {
    const value = localStorage.getItem(key)
    return value ? (JSON.parse(value) as T) : fallback
  } catch {
    return fallback
  }
}
