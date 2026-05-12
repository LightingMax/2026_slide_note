import { http } from './http'
import type { AgentResponse, ChatMessage, Deck } from '@/types/deck'

export async function fetchDecks() {
  const { data } = await http.get<Deck[]>('/decks')
  return data
}

export async function uploadDeck(file: File) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<Deck>('/decks/upload', form)
  return data
}

export async function updateSlideNotes(deckId: string, slideId: string, notes: string) {
  const { data } = await http.patch<Deck>(`/decks/${deckId}/slides/${slideId}/notes`, { notes })
  return data
}

export async function resetSlideNotes(deckId: string, slideId: string) {
  const { data } = await http.post<Deck>(`/decks/${deckId}/slides/${slideId}/notes/reset`)
  return data
}

export async function exportDeck(deckId: string) {
  const response = await http.get<Blob>(`/decks/${deckId}/export`, { responseType: 'blob' })
  return response.data
}

export async function renderDeck(deckId: string) {
  const { data } = await http.post<Deck>(`/decks/${deckId}/render`)
  return data
}

export async function requestNoteDraft(
  deckId: string,
  slideId: string,
  instruction: string,
  messages: ChatMessage[]
) {
  const { data } = await http.post<AgentResponse>(`/decks/${deckId}/chat`, {
    slide_id: slideId,
    instruction,
    messages: messages.filter((message) => message.role === 'user' || message.role === 'assistant')
  })
  return data
}
