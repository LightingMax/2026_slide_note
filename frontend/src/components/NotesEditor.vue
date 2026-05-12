<script setup lang="ts">
import { Download, DocumentChecked, RefreshLeft } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { ref, watch } from 'vue'

import { useDeckStore } from '@/stores/deck'

const deckStore = useDeckStore()
const notes = ref('')
const saving = ref(false)

watch(
  () => deckStore.activeSlide,
  (slide) => {
    notes.value = slide?.notes ?? ''
  },
  { immediate: true }
)

async function save() {
  saving.value = true
  try {
    await deckStore.saveNotes(notes.value)
    ElMessage.success('备注已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function reset() {
  saving.value = true
  try {
    await deckStore.resetActiveSlideNotes()
    ElMessage.success('已还原为 PPT 原始备注')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重置失败')
  } finally {
    saving.value = false
  }
}

async function exportPpt() {
  saving.value = true
  try {
    await deckStore.exportActiveDeck()
    ElMessage.success('PPT 已导出')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '导出失败')
  } finally {
    saving.value = false
  }
}

function replaceText(value: string) {
  notes.value = value
}

defineExpose({ replaceText })
</script>

<template>
  <section class="workspace-panel flex h-64 flex-col rounded-md">
    <div class="flex items-center justify-between border-b border-line px-5 py-3 dark:border-slate-700">
      <div class="flex items-center gap-2 text-sm font-medium">
        <el-icon><DocumentChecked /></el-icon>
        <span>当前页讲稿</span>
      </div>
      <div class="flex items-center gap-2">
        <el-button size="small" :icon="RefreshLeft" :loading="saving" @click="reset">重置</el-button>
        <el-button size="small" :icon="Download" :loading="saving" @click="exportPpt">导出 PPT</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="save">保存当前讲稿</el-button>
      </div>
    </div>
    <el-input
      v-model="notes"
      type="textarea"
      resize="none"
      :rows="7"
      placeholder="这里的文字会作为语音播报稿，请使用自然口语、短句和清晰转场。"
      class="min-h-0 flex-1"
    />
  </section>
</template>
