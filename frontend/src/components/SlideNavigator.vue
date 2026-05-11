<script setup lang="ts">
import { computed } from 'vue'

import { useDeckStore } from '@/stores/deck'

const deckStore = useDeckStore()
const slides = computed(() => deckStore.activeDeck?.slides ?? [])
</script>

<template>
  <aside class="workspace-panel flex min-h-0 flex-col rounded-md">
    <div class="border-b border-line p-4 dark:border-slate-700">
      <div class="text-sm font-semibold">幻灯片</div>
      <div class="mt-1 text-xs text-slate-500">{{ slides.length }} 页已解析</div>
    </div>
    <el-scrollbar class="min-h-0 flex-1">
      <button
        v-for="slide in slides"
        :key="slide.id"
        class="block w-full border-b border-line p-3 text-left transition hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
        :class="slide.id === deckStore.activeSlideId ? 'bg-slate-100 dark:bg-slate-800' : ''"
        @click="deckStore.activeSlideId = slide.id"
      >
        <div class="mb-2 flex items-center justify-between text-xs text-slate-500">
          <span>第 {{ slide.index }} 页</span>
          <span>{{ slide.assets.length }} 个媒体</span>
        </div>
        <div class="aspect-video rounded border border-slate-200 bg-white p-3 text-xs leading-5 text-slate-700 shadow-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200">
          <p class="line-clamp-3 font-semibold">{{ slide.title }}</p>
          <p class="mt-2 line-clamp-2 text-slate-500">{{ slide.notes || slide.text }}</p>
        </div>
      </button>
    </el-scrollbar>
  </aside>
</template>
