import { http } from './http'
import type { ChatMessage, Deck } from '@/types/deck'

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

export async function requestNoteDraft(
  deckId: string,
  slideId: string,
  instruction: string,
  messages: ChatMessage[]
) {
  const { data } = await http.post<{ text: string }>(`/decks/${deckId}/chat`, {
    slide_id: slideId,
    instruction,
    messages
  })
  return data.text
}

