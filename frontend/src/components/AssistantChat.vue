<script setup lang="ts">
import { ChatLineRound, Clock, EditPen, Notebook } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { ref } from 'vue'

import { useDeckStore } from '@/stores/deck'
import type { AgentAction } from '@/types/deck'

const deckStore = useDeckStore()
const emit = defineEmits<{
  apply: [action: AgentAction]
}>()

const instruction = ref('把这一页备注改写成 40 秒左右的自然中文播报稿')
const loading = ref(false)
const activeTab = ref('chat')

async function send() {
  const value = instruction.value.trim()
  if (!value) return
  loading.value = true
  try {
    const response = await deckStore.askAssistant(value)
    instruction.value = ''
    response?.actions.forEach((action) => {
      if (action.type === 'replace_notes') {
        emit('apply', action)
      }
    })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '生成失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <aside class="workspace-panel flex min-h-0 flex-col rounded-md">
    <div class="border-b border-line p-4 dark:border-slate-700">
      <div class="flex items-center gap-2 text-sm font-semibold">
        <el-icon><ChatLineRound /></el-icon>
        <span>智能备注助手</span>
      </div>
      <p class="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
        保留你和助手的对话，以及我对这份 PPT 做过的操作记录。
      </p>
    </div>

    <el-tabs v-model="activeTab" class="assistant-tabs min-h-0 flex-1">
      <el-tab-pane name="chat">
        <template #label>
          <span class="inline-flex items-center gap-1">
            <el-icon><ChatLineRound /></el-icon>
            对话
          </span>
        </template>
        <el-scrollbar class="assistant-scroll">
          <div class="space-y-4 p-4">
            <div
              v-for="(message, index) in deckStore.chatMessages"
              :key="`${message.role}-${index}`"
              class="flex"
              :class="message.role === 'user' ? 'justify-end' : 'justify-start'"
            >
              <article
                class="max-w-[88%] rounded-md border px-3 py-2 text-sm leading-6 shadow-sm"
                :class="
                  message.role === 'assistant'
                    ? 'border-slate-200 bg-white text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100'
                    : 'border-sky-200 bg-sky-50 text-slate-900 dark:border-sky-700 dark:bg-sky-950 dark:text-slate-50'
                "
              >
                <div class="mb-1 text-xs font-medium text-slate-500">
                  {{ message.role === 'assistant' ? 'Slide Note' : '你' }}
                </div>
                <p class="whitespace-pre-line">{{ message.content }}</p>
                <div v-if="message.actions?.length" class="mt-3 space-y-2">
                  <div
                    v-for="action in message.actions"
                    :key="`${action.type}-${action.slide_id}-${action.label}`"
                    class="rounded border border-slate-200 bg-slate-50 p-2 text-xs dark:border-slate-700 dark:bg-slate-800"
                  >
                    <div class="mb-1 font-medium text-slate-700 dark:text-slate-200">
                      {{ action.label }}
                    </div>
                    <p class="line-clamp-3 leading-5 text-slate-500 dark:text-slate-400">
                      {{ action.content }}
                    </p>
                  </div>
                </div>
              </article>
            </div>
            <el-empty
              v-if="deckStore.chatMessages.length === 0"
              description="这一页还没有对话记录"
            />
          </div>
        </el-scrollbar>
      </el-tab-pane>

      <el-tab-pane name="activity">
        <template #label>
          <span class="inline-flex items-center gap-1">
            <el-icon><Notebook /></el-icon>
            记录
          </span>
        </template>
        <el-scrollbar class="assistant-scroll">
          <div class="space-y-3 p-4">
            <article
              v-for="item in deckStore.activityLog"
              :key="item.id"
              class="rounded-md border border-slate-200 bg-white p-3 text-sm shadow-sm dark:border-slate-700 dark:bg-slate-900"
            >
              <div class="mb-1 flex items-center justify-between gap-3">
                <div class="font-medium text-slate-900 dark:text-slate-100">{{ item.title }}</div>
                <div class="inline-flex items-center gap-1 text-xs text-slate-500">
                  <el-icon><Clock /></el-icon>
                  {{ item.time }}
                </div>
              </div>
              <p class="line-clamp-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
                {{ item.detail }}
              </p>
            </article>
            <el-empty v-if="deckStore.activityLog.length === 0" description="还没有操作记录" />
          </div>
        </el-scrollbar>
      </el-tab-pane>
    </el-tabs>

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
        <el-button @click="instruction = '把现在的内容压缩成更短、更容易听懂的版本'">压缩</el-button>
      </div>
      <el-button class="mt-3 w-full" type="primary" :icon="EditPen" :loading="loading" @click="send">
        生成并填入备注
      </el-button>
    </div>
  </aside>
</template>
