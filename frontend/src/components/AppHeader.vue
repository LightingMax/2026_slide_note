<script setup lang="ts">
import { Download, Moon, Refresh, Sunny, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, type UploadRequestOptions } from 'element-plus'

import { useDeckStore } from '@/stores/deck'
import { useThemeStore } from '@/stores/theme'

const deckStore = useDeckStore()
const theme = useThemeStore()

async function handleUpload(options: UploadRequestOptions) {
  try {
    await deckStore.upload(options.file)
    ElMessage.success('PPT 已解析完成')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '上传失败')
  }
}

async function renderSnapshots() {
  try {
    await deckStore.rerenderSnapshots()
    ElMessage.success('快照任务已完成')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '快照生成失败')
  }
}

async function exportPpt() {
  try {
    await deckStore.exportActiveDeck()
    ElMessage.success('PPT 已导出')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '导出失败')
  }
}
</script>

<template>
  <header class="flex h-16 items-center justify-between border-b border-slate-200 bg-white px-5 dark:border-slate-700 dark:bg-slate-950">
    <div>
      <h1 class="text-lg font-semibold tracking-normal text-ink dark:text-slate-100">Slide Note</h1>
      <p class="text-xs text-slate-500 dark:text-slate-400">解析 PPT，整理备注，生成适合语音播报的讲稿</p>
    </div>

    <div class="flex items-center gap-3">
      <el-switch
        :model-value="theme.dark"
        :active-action-icon="Moon"
        :inactive-action-icon="Sunny"
        @change="(value: string | number | boolean) => theme.toggle(Boolean(value))"
      />
      <el-button :icon="Refresh" :loading="deckStore.loading" :disabled="!deckStore.activeDeck" @click="renderSnapshots">
        生成快照
      </el-button>
      <el-button :icon="Download" :disabled="!deckStore.activeDeck" @click="exportPpt">
        导出 PPT
      </el-button>
      <el-upload
        accept=".pptx"
        :show-file-list="false"
        :http-request="handleUpload"
      >
        <el-button type="primary" :icon="UploadFilled" :loading="deckStore.loading">上传 PPTX</el-button>
      </el-upload>
    </div>
  </header>
</template>
