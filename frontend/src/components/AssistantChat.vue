<script setup lang="ts">
import { ChatLineRound, EditPen } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { ref } from 'vue'

import { useDeckStore } from '@/stores/deck'

const deckStore = useDeckStore()
const emit = defineEmits<{
  apply: [value: string]
}>()

const instruction = ref('把这一页备注改写成 40 秒左右的自然中文播报稿')
const loading = ref(false)

async function send() {
  const value = instruction.value.trim()
  if (!value) return
  loading.value = true
  try {
    const text = await deckStore.askAssistant(value)
    instruction.value = ''
    emit('apply', text)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '生成失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <aside class="workspace-panel flex min-h-0 flex-col rounded-md">
    <div class="flex items-center gap-2 border-b border-line p-3 text-sm font-medium dark:border-slate-700">
      <el-icon><ChatLineRound /></el-icon>
      <span>智能备注助手</span>
    </div>

    <el-scrollbar class="min-h-0 flex-1">
      <div class="space-y-3 p-3">
        <div
          v-for="(message, index) in deckStore.chatMessages"
          :key="`${message.role}-${index}`"
          class="rounded-md border border-line p-3 text-sm leading-6 dark:border-slate-700"
          :class="message.role === 'assistant' ? 'bg-sky-50 dark:bg-slate-800' : 'bg-white dark:bg-slate-950'"
        >
          <div class="mb-1 text-xs font-medium text-slate-500">
            {{ message.role === 'assistant' ? '助手' : '你' }}
          </div>
          <p class="whitespace-pre-line">{{ message.content }}</p>
        </div>
        <el-empty v-if="deckStore.chatMessages.length === 0" description="选择一页后让助手生成或改写备注" />
      </div>
    </el-scrollbar>

    <div class="border-t border-line p-3 dark:border-slate-700">
      <el-input
        v-model="instruction"
        type="textarea"
        resize="none"
        :rows="4"
        placeholder="输入改写要求"
      />
      <div class="mt-3 grid grid-cols-2 gap-2">
        <el-button @click="instruction = '润色当前备注，使其更适合语音播报'">润色</el-button>
        <el-button @click="instruction = '根据幻灯片内容生成 60 秒讲稿'">生成讲稿</el-button>
      </div>
      <el-button class="mt-3 w-full" type="primary" :icon="EditPen" :loading="loading" @click="send">
        生成并填入备注
      </el-button>
    </div>
  </aside>
</template>

