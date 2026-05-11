export interface SlideAsset {
  name: string
  kind: 'image' | 'audio' | 'video'
  url: string
  content_type?: string
}

export interface Slide {
  id: string
  index: number
  title: string
  text: string
  notes: string
  assets: SlideAsset[]
}

export interface Deck {
  id: string
  filename: string
  created_at: string
  slides: Slide[]
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ActivityItem {
  id: string
  time: string
  title: string
  detail: string
}
