import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import { fetchDecks, renderDeck, requestNoteDraft, updateSlideNotes, uploadDeck } from '@/api/decks'
import type { ActivityItem, AgentResponse, ChatMessage, Deck, Slide } from '@/types/deck'

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

  const activeSlide = computed<Slide | null>(() => {
    return activeDeck.value?.slides.find((slide) => slide.id === activeSlideId.value) ?? null
  })

  const activeChatKey = computed(() => {
    if (!activeDeck.value || !activeSlideId.value) return ''
    return `${activeDeck.value.id}:${activeSlideId.value}`
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
    addActivity('保存备注', `${activeSlide.value?.title || '当前页'}，${notes.length} 字`)
  }

  async function rerenderSnapshots() {
    if (!activeDeck.value) return
    loading.value = true
    try {
      activeDeck.value = await renderDeck(activeDeck.value.id)
      decks.value = decks.value.map((deck) => (deck.id === activeDeck.value?.id ? activeDeck.value : deck))
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
    chatMessages.value.push({ role: 'user', content: instruction })
    addActivity('发送生成要求', instruction)
    try {
      const response = await requestNoteDraft(
        activeDeck.value.id,
        activeSlideId.value,
        instruction,
        chatMessages.value
      )
      chatMessages.value.push({
        role: 'assistant',
        content: response.message,
        actions: response.actions
      })
      addActivity('生成备注草稿', `${activeSlide.value?.title || '当前页'}，${response.text.length} 字`)
      return response
    } catch (error) {
      const message = error instanceof Error ? error.message : '生成失败'
      chatMessages.value.push({ role: 'assistant', content: `请求失败：${message}` })
      addActivity('生成失败', message)
      throw error
    }
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

  return {
    decks,
    activeDeck,
    activeSlideId,
    activeSlide,
    loading,
    chatMessages,
    activityLog,
    loadDecks,
    setDeck,
    upload,
    saveNotes,
    askAssistant,
    rerenderSnapshots,
    addActivity
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
