import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { fetchDecks, requestNoteDraft, updateSlideNotes, uploadDeck } from '@/api/decks'
import type { ChatMessage, Deck, Slide } from '@/types/deck'

export const useDeckStore = defineStore('deck', () => {
  const decks = ref<Deck[]>([])
  const activeDeck = ref<Deck | null>(null)
  const activeSlideId = ref<string>('')
  const loading = ref(false)
  const chatMessages = ref<ChatMessage[]>([])

  const activeSlide = computed<Slide | null>(() => {
    return activeDeck.value?.slides.find((slide) => slide.id === activeSlideId.value) ?? null
  })

  async function loadDecks() {
    decks.value = await fetchDecks()
    if (!activeDeck.value && decks.value.length > 0) {
      setDeck(decks.value[0])
    }
  }

  function setDeck(deck: Deck) {
    activeDeck.value = deck
    activeSlideId.value = deck.slides[0]?.id || ''
    chatMessages.value = []
  }

  async function upload(file: File) {
    loading.value = true
    try {
      const deck = await uploadDeck(file)
      decks.value = [deck, ...decks.value.filter((item) => item.id !== deck.id)]
      setDeck(deck)
    } finally {
      loading.value = false
    }
  }

  async function saveNotes(notes: string) {
    if (!activeDeck.value || !activeSlideId.value) return
    activeDeck.value = await updateSlideNotes(activeDeck.value.id, activeSlideId.value, notes)
  }

  async function askAssistant(instruction: string) {
    if (!activeDeck.value || !activeSlideId.value) return ''
    chatMessages.value.push({ role: 'user', content: instruction })
    const text = await requestNoteDraft(
      activeDeck.value.id,
      activeSlideId.value,
      instruction,
      chatMessages.value
    )
    chatMessages.value.push({ role: 'assistant', content: text })
    return text
  }

  return {
    decks,
    activeDeck,
    activeSlideId,
    activeSlide,
    loading,
    chatMessages,
    loadDecks,
    setDeck,
    upload,
    saveNotes,
    askAssistant
  }
})

