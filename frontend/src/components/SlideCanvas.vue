<script setup lang="ts">
import { Files, Picture, Refresh, VideoCameraFilled } from '@element-plus/icons-vue'
import { computed } from 'vue'

import { useDeckStore } from '@/stores/deck'

const deckStore = useDeckStore()
const imageAssets = computed(() => deckStore.activeSlide?.assets.filter((asset) => asset.kind === 'image') ?? [])
const audioAssets = computed(() => deckStore.activeSlide?.assets.filter((asset) => asset.kind === 'audio') ?? [])
const videoAssets = computed(() => deckStore.activeSlide?.assets.filter((asset) => asset.kind === 'video') ?? [])
const previewLines = computed(() => {
  const slide = deckStore.activeSlide
  if (!slide) return []
  return slide.text
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(1, 8)
})
const renderLabel = computed(() => {
  const status = deckStore.activeSlide?.render_status
  if (status === 'ready') return '真实快照'
  if (status === 'missing') return '缺少页面'
  if (status === 'unavailable') return '解析预览'
  return '等待渲染'
})
</script>

<template>
  <main class="workspace-panel flex min-h-0 flex-col rounded-md">
    <div class="flex items-center justify-between border-b border-line px-5 py-4 dark:border-slate-700">
      <div>
        <p class="text-xs font-medium uppercase tracking-[0.16em] text-slate-500">Slide Snapshot</p>
        <h2 class="mt-1 text-base font-semibold">{{ deckStore.activeSlide?.title || '等待上传 PPT' }}</h2>
      </div>
      <div v-if="deckStore.activeSlide" class="flex items-center gap-2">
        <el-tag :type="deckStore.activeSlide.render_status === 'ready' ? 'success' : 'warning'">
          {{ renderLabel }}
        </el-tag>
        <el-tag>第 {{ deckStore.activeSlide.index }} 页</el-tag>
        <el-button
          size="small"
          :icon="Refresh"
          :loading="deckStore.loading"
          @click="deckStore.rerenderSnapshots"
        >
          重渲染
        </el-button>
      </div>
    </div>

    <el-scrollbar class="min-h-0 flex-1">
      <section v-if="deckStore.activeSlide" class="space-y-4 p-5">
        <div v-if="deckStore.activeSlide.snapshot_url" class="slide-stage">
          <img
            :src="deckStore.activeSlide.snapshot_url"
            :alt="deckStore.activeSlide.title"
            class="slide-rendered-image"
          />
        </div>

        <el-alert
          v-else-if="deckStore.activeSlide.render_status === 'unavailable'"
          type="warning"
          :closable="false"
          show-icon
          title="PPT 渲染服务未启用，当前显示解析预览。"
          :description="deckStore.activeSlide.render_error || '请在后端安装 LibreOffice，并可选配置 LIBREOFFICE_PATH。'"
        />

        <div v-if="!deckStore.activeSlide.snapshot_url" class="slide-stage">
          <div class="slide-sheet">
            <div class="slide-ribbon">预览快照</div>
            <h3>{{ deckStore.activeSlide.title }}</h3>
            <div class="mt-5 grid min-h-0 flex-1 grid-cols-[1fr_170px] gap-6">
              <div class="space-y-3">
                <p
                  v-for="line in previewLines"
                  :key="line"
                  class="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-700"
                >
                  {{ line }}
                </p>
                <p v-if="previewLines.length === 0" class="text-sm text-slate-500">
                  这一页没有可抽取的正文文本。
                </p>
              </div>
              <div class="space-y-3">
                <div
                  v-if="imageAssets[0]"
                  class="aspect-[4/3] rounded border border-slate-200 bg-white p-2"
                >
                  <img :src="imageAssets[0].url" :alt="imageAssets[0].name" class="h-full w-full object-contain" />
                </div>
                <div class="rounded border border-slate-200 bg-white p-3 text-xs leading-5 text-slate-500">
                  备注 {{ deckStore.activeSlide.notes.length }} 字<br />
                  媒体 {{ deckStore.activeSlide.assets.length }} 个
                </div>
              </div>
            </div>
          </div>
        </div>

        <el-collapse>
          <el-collapse-item name="parsed">
            <template #title>
              <span class="inline-flex items-center gap-2 text-sm font-medium">
                <el-icon><Files /></el-icon>
                解析详情
              </span>
            </template>
            <div class="grid gap-4 lg:grid-cols-2">
              <div class="rounded-md border border-line bg-white p-4 dark:border-slate-700 dark:bg-slate-950">
                <div class="mb-3 flex items-center gap-2 text-sm text-slate-500">
                  <el-icon><Picture /></el-icon>
                  <span>后台抽取文本</span>
                </div>
                <p class="max-h-48 overflow-auto whitespace-pre-line text-sm leading-7 text-slate-700 dark:text-slate-200">
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
            </div>
          </el-collapse-item>
        </el-collapse>

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
