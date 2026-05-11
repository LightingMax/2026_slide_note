<script setup lang="ts">
import { Picture, VideoCameraFilled } from '@element-plus/icons-vue'
import { computed } from 'vue'

import { useDeckStore } from '@/stores/deck'

const deckStore = useDeckStore()
const imageAssets = computed(() => deckStore.activeSlide?.assets.filter((asset) => asset.kind === 'image') ?? [])
const audioAssets = computed(() => deckStore.activeSlide?.assets.filter((asset) => asset.kind === 'audio') ?? [])
const videoAssets = computed(() => deckStore.activeSlide?.assets.filter((asset) => asset.kind === 'video') ?? [])
</script>

<template>
  <main class="workspace-panel flex min-h-0 flex-col rounded-md">
    <div class="flex items-center justify-between border-b border-line px-4 py-3 dark:border-slate-700">
      <div>
        <p class="text-xs text-slate-500">内容预览</p>
        <h2 class="text-base font-semibold">{{ deckStore.activeSlide?.title || '等待上传 PPT' }}</h2>
      </div>
      <el-tag v-if="deckStore.activeSlide">第 {{ deckStore.activeSlide.index }} 页</el-tag>
    </div>

    <el-scrollbar class="min-h-0 flex-1">
      <section v-if="deckStore.activeSlide" class="space-y-4 p-5">
        <div class="rounded-md border border-line bg-white p-6 dark:border-slate-700 dark:bg-slate-950">
          <div class="mb-4 flex items-center gap-2 text-sm text-slate-500">
            <el-icon><Picture /></el-icon>
            <span>幻灯片文字</span>
          </div>
          <p class="min-h-48 whitespace-pre-line text-sm leading-7 text-slate-800 dark:text-slate-100">
            {{ deckStore.activeSlide.text || '这一页没有可抽取文字。' }}
          </p>
        </div>

        <div v-if="imageAssets.length" class="grid grid-cols-2 gap-3">
          <img
            v-for="asset in imageAssets"
            :key="asset.url"
            :src="asset.url"
            :alt="asset.name"
            class="aspect-video w-full rounded-md border border-line object-contain dark:border-slate-700"
          />
        </div>

        <div v-if="audioAssets.length || videoAssets.length" class="space-y-3">
          <div class="flex items-center gap-2 text-sm font-medium">
            <el-icon><VideoCameraFilled /></el-icon>
            <span>媒体播放</span>
          </div>
          <audio
            v-for="asset in audioAssets"
            :key="asset.url"
            controls
            class="w-full"
            :src="asset.url"
          />
          <video
            v-for="asset in videoAssets"
            :key="asset.url"
            controls
            class="aspect-video w-full rounded-md bg-black"
            :src="asset.url"
          />
        </div>
      </section>
      <el-empty v-else description="上传 PPTX 后开始编辑备注" />
    </el-scrollbar>
  </main>
</template>

