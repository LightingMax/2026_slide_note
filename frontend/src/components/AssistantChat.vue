<script setup lang="ts">
import { ChatLineRound, Clock, Delete, Notebook, Promotion, VideoPause } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ref } from 'vue'

import { useDeckStore } from '@/stores/deck'

const deckStore = useDeckStore()
const instruction = ref('')
const loading = ref(false)
const activeTab = ref('chat')

async function send() {
  const value = instruction.value.trim()
  if (!value) return
  loading.value = true
  try {
    await deckStore.askAssistant(value)
    instruction.value = ''
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '生成失败')
  } finally {
    loading.value = false
  }
}

async function applyStyle(styleId: string) {
  const style = deckStore.agentStyles.find((item) => item.id === styleId)
  if (!style) return
  loading.value = true
  try {
    await deckStore.applyStyleTemplate(style)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '生成失败')
  } finally {
    loading.value = false
  }
}

async function stop() {
  try {
    await deckStore.stopAgentRun()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '停止失败')
  } finally {
    loading.value = false
  }
}

async function clearContext() {
  try {
    await ElMessageBox.confirm('清除当前 PPT 的会话历史和后端记忆，不会修改已保存的讲稿。', '清除上下文', {
      confirmButtonText: '清除',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await deckStore.clearCurrentContext()
    ElMessage.success('上下文已清除')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error instanceof Error ? error.message : '清除失败')
    }
  }
}
</script>

<template>
  <aside class="workspace-panel flex min-h-0 flex-col rounded-md">
    <div class="border-b border-line p-4 dark:border-slate-700">
      <div class="flex items-center justify-between gap-3">
        <div class="flex items-center gap-2 text-sm font-semibold">
          <el-icon><ChatLineRound /></el-icon>
          <span>会话</span>
        </div>
        <el-button
          size="small"
          text
          :icon="Delete"
          :disabled="!deckStore.activeDeck"
          @click="clearContext"
        >
          清除上下文
        </el-button>
      </div>
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
                    : message.role === 'agent'
                      ? 'border-dashed border-slate-300 bg-slate-50 text-slate-600 shadow-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300'
                      : 'border-sky-200 bg-sky-50 text-slate-900 dark:border-sky-700 dark:bg-sky-950 dark:text-slate-50'
                "
              >
                <div class="mb-1 text-xs font-medium text-slate-500">
                  {{ message.role === 'assistant' ? 'Slide Note' : message.role === 'agent' ? '工作过程' : '你' }}
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
              description="当前讲稿已经准备好，你希望迁移成什么风格？"
            >
              <div class="grid grid-cols-2 gap-2">
                <el-button @click="applyStyle('business')">商务汇报</el-button>
                <el-button @click="applyStyle('children')">小朋友友好</el-button>
                <el-button @click="applyStyle('executive')">高管简报</el-button>
                <el-button @click="applyStyle('sales')">产品演示</el-button>
              </div>
            </el-empty>
          </div>
        </el-scrollbar>
      </el-tab-pane>

      <el-tab-pane name="activity">
        <template #label>
          <span class="inline-flex items-center gap-1">
            <el-icon><Notebook /></el-icon>
            会话
          </span>
        </template>
        <el-scrollbar class="assistant-scroll">
          <div class="space-y-3 p-4">
            <button
              v-for="deck in deckStore.decks"
              :key="deck.id"
              class="block w-full rounded-md border border-slate-200 bg-white p-3 text-left text-sm shadow-sm transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:hover:bg-slate-800"
              :class="deck.id === deckStore.activeDeck?.id ? 'border-sky-300 bg-sky-50 dark:border-sky-700 dark:bg-sky-950' : ''"
              @click="deckStore.setDeck(deck)"
            >
              <div class="font-medium text-slate-900 dark:text-slate-100">{{ deck.filename }}</div>
              <div class="mt-1 text-xs text-slate-500">{{ deck.slides.length }} 页 · 当前工作会话</div>
            </button>
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
        :rows="3"
        placeholder="输入消息，回车发送，Shift+Enter 换行"
        :disabled="deckStore.agentRunning"
        @keydown.enter.exact.prevent="send"
      />
      <el-button
        v-if="deckStore.agentRunning"
        class="mt-3 w-full"
        type="danger"
        :icon="VideoPause"
        @click="stop"
      >
        停止
      </el-button>
      <el-button v-else class="mt-3 w-full" type="primary" :icon="Promotion" :loading="loading" @click="send">
        发送
      </el-button>
    </div>
  </aside>
</template>
