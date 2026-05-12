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
  original_notes?: string | null
  snapshot_url?: string | null
  render_status: 'pending' | 'ready' | 'missing' | 'unavailable'
  render_error?: string | null
  assets: SlideAsset[]
}

export interface Deck {
  id: string
  filename: string
  created_at: string
  slides: Slide[]
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'agent'
  content: string
  actions?: AgentAction[]
}

export interface AgentAction {
  type: 'replace_notes'
  slide_id: string
  label: string
  content: string
}

export interface AgentResponse {
  text: string
  message: string
  actions: AgentAction[]
}

export interface ActivityItem {
  id: string
  time: string
  title: string
  detail: string
}
