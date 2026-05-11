<script setup lang="ts">
import { computed } from 'vue'

import { useDeckStore } from '@/stores/deck'

const deckStore = useDeckStore()
const slides = computed(() => deckStore.activeDeck?.slides ?? [])
</script>

<template>
  <aside class="workspace-panel flex min-h-0 flex-col rounded-md">
    <div class="border-b border-line p-3 text-sm font-medium dark:border-slate-700">幻灯片</div>
    <el-scrollbar class="min-h-0 flex-1">
      <button
        v-for="slide in slides"
        :key="slide.id"
        class="block w-full border-b border-line p-3 text-left transition hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
        :class="slide.id === deckStore.activeSlideId ? 'bg-sky-50 dark:bg-slate-800' : ''"
        @click="deckStore.activeSlideId = slide.id"
      >
        <div class="mb-2 flex items-center justify-between text-xs text-slate-500">
          <span>第 {{ slide.index }} 页</span>
          <span>{{ slide.assets.length }} 个媒体</span>
        </div>
        <div class="aspect-video rounded border border-line bg-white p-2 text-xs leading-5 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
          <p class="line-clamp-4 whitespace-pre-line">{{ slide.title }}</p>
        </div>
      </button>
    </el-scrollbar>
  </aside>
</template>

