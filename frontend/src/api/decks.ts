import { http } from './http'
import type { AgentRunCreated, AgentStylePreset, ChatMessage, Deck } from '@/types/deck'

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

export async function clearDeckMemory(deckId: string) {
  await http.delete(`/decks/${deckId}/memory`)
}

export async function fetchAgentStyles() {
  const { data } = await http.get<AgentStylePreset[]>('/agent/styles')
  return data
}

export async function createAgentRun(
  deckId: string,
  slideId: string,
  instruction: string,
  messages: ChatMessage[],
  stylePreset: string
) {
  const { data } = await http.post<AgentRunCreated>('/agent/runs', {
    deck_id: deckId,
    slide_id: slideId,
    instruction,
    style_preset: stylePreset,
    messages: messages.filter((message) => message.role === 'user' || message.role === 'assistant')
  })
  return data
}

export async function cancelAgentRun(runId: string) {
  const { data } = await http.delete<{ cancelled: boolean }>(`/agent/runs/${runId}`)
  return data
}
