<script setup lang="ts">
import { onMounted, ref } from 'vue'

import AppHeader from '@/components/AppHeader.vue'
import AssistantChat from '@/components/AssistantChat.vue'
import NotesEditor from '@/components/NotesEditor.vue'
import SlideCanvas from '@/components/SlideCanvas.vue'
import SlideNavigator from '@/components/SlideNavigator.vue'
import { useDeckStore } from '@/stores/deck'

const deckStore = useDeckStore()
const notesEditor = ref<InstanceType<typeof NotesEditor> | null>(null)

onMounted(() => {
  deckStore.loadDecks()
})

function applyAssistantText(value: string) {
  notesEditor.value?.replaceText(value)
}
</script>

<template>
  <div class="flex h-screen flex-col bg-[#eef2f7] dark:bg-slate-900">
    <AppHeader />
    <div class="grid min-h-0 flex-1 grid-cols-[260px_minmax(0,1fr)_390px] gap-4 p-4">
      <SlideNavigator />
      <div class="flex min-h-0 flex-col gap-4">
        <SlideCanvas />
        <NotesEditor ref="notesEditor" />
      </div>
      <AssistantChat @apply="applyAssistantText" />
    </div>
  </div>
</template>
