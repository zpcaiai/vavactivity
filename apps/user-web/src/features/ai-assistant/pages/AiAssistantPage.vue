<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import {
  aiAssistantApi,
  type AiConversation,
  type AiMessage,
  type AiTurnResult
} from "../api";

const route = useRoute();
const router = useRouter();
const conversations = ref<AiConversation[]>([]);
const selected = ref<AiConversation>();
const messages = ref<AiMessage[]>([]);
const latestTurn = ref<AiTurnResult>();
const draft = ref("");
const disclosureAccepted = ref(false);
const memoryOptIn = ref(false);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const pendingAction = ref("");

const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const copy = computed(() => {
  if (locale.value === "en") {
    return {
      title: "Hanna relationship assistant",
      disclosure: "Hanna is an AI service, not an emergency, medical, legal, or licensed counseling service. Responses may be incomplete or wrong. Safety signals can pause ordinary advice and create a restricted human review.",
      accept: "I understand and choose to start an AI conversation",
      memory: "Allow optional long-term memory for this conversation (separate consent; can be revoked)",
      newChat: "Start conversation",
      placeholder: "Describe one concrete interaction or ask about a current VAV service…",
      send: "Send",
      sources: "Authorized sources",
      paused: "Ordinary advice is paused. Follow the safety guidance and human-support status shown above.",
      empty: "No conversation selected. Read the disclosure and start when you are ready.",
      delete: "Delete conversation",
      saveAction: "Save as action item",
      confirmAction: "Confirm save",
      cancel: "Cancel"
    };
  }
  if (locale.value === "zh-TW") {
    return {
      title: "Hanna 關係助理",
      disclosure: "Hanna 是 AI 服務，不是緊急、醫療、法律或持牌輔導服務。回答可能不完整或有誤；安全訊號可暫停一般建議並建立受限人工覆核。",
      accept: "我已理解並選擇開始 AI 對話",
      memory: "允許本對話使用可選長期記憶（獨立同意，可隨時撤回）",
      newChat: "開始對話",
      placeholder: "描述一次具體互動，或詢問目前可用的 VAV 服務…",
      send: "傳送",
      sources: "已授權來源",
      paused: "一般建議已暫停。請優先依照安全指引並留意真人支援狀態。",
      empty: "尚未選擇對話。請先閱讀聲明，準備好後再開始。",
      delete: "刪除對話",
      saveAction: "儲存為行動項",
      confirmAction: "確認儲存",
      cancel: "取消"
    };
  }
  return {
    title: "Hanna 关系助理",
    disclosure: "Hanna 是 AI 服务，不是紧急、医疗、法律或持牌辅导服务。回答可能不完整或有误；安全信号可暂停普通建议并创建受限人工复核。",
    accept: "我已理解并选择开始 AI 对话",
    memory: "允许本对话使用可选长期记忆（单独同意，可随时撤回）",
    newChat: "开始对话",
    placeholder: "描述一次具体互动，或询问当前可用的 VAV 服务…",
    send: "发送",
    sources: "已授权来源",
    paused: "普通建议已暂停。请优先按照安全指引，并留意真人支持状态。",
    empty: "尚未选择对话。请先阅读声明，准备好后再开始。",
    delete: "删除对话",
    saveAction: "保存为行动项",
    confirmAction: "确认保存",
    cancel: "取消"
  };
});

async function loadList() {
  conversations.value = (await aiAssistantApi.list()).items;
  const requested = String(route.params.conversationId ?? "");
  const target = requested || conversations.value[0]?.id;
  if (target) await choose(target);
}

async function choose(id: string) {
  selected.value = await aiAssistantApi.detail(id);
  messages.value = selected.value.messages ?? [];
  memoryOptIn.value = selected.value.memory_consent_status === "granted";
  if (String(route.params.conversationId ?? "") !== id) {
    await router.replace({
      name: "ai-assistant-conversation",
      params: { locale: locale.value, conversationId: id }
    });
  }
}

async function createConversation() {
  if (!disclosureAccepted.value) return;
  busy.value = true;
  error.value = "";
  try {
    const value = await aiAssistantApi.create(locale.value, memoryOptIn.value);
    await loadList();
    await choose(value.id);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "Unable to start conversation";
  } finally {
    busy.value = false;
  }
}

async function send() {
  if (!selected.value || !draft.value.trim()) return;
  const content = draft.value.trim();
  draft.value = "";
  busy.value = true;
  error.value = "";
  try {
    latestTurn.value = await aiAssistantApi.send(selected.value.id, content, locale.value);
    await choose(selected.value.id);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "Unable to send message";
  } finally {
    busy.value = false;
  }
}

async function changeMemory() {
  if (!selected.value) return;
  const result = await aiAssistantApi.setMemory(selected.value.id, memoryOptIn.value);
  selected.value.memory_consent_status = result.memory_consent_status;
}

async function removeConversation() {
  if (!selected.value) return;
  await aiAssistantApi.remove(selected.value.id);
  selected.value = undefined;
  messages.value = [];
  latestTurn.value = undefined;
  await router.replace({ name: "ai-assistant", params: { locale: locale.value } });
  await loadList();
}

async function saveActionItem() {
  if (!selected.value || !pendingAction.value) return;
  busy.value = true;
  try {
    const argumentsValue = { content: pendingAction.value };
    const confirmation = await aiAssistantApi.confirmTool(
      selected.value.id,
      "create_user_action_item",
      argumentsValue
    );
    await aiAssistantApi.executeTool(
      selected.value.id,
      "create_user_action_item",
      confirmation.confirmation_token,
      argumentsValue
    );
    notice.value = copy.value.confirmAction;
    pendingAction.value = "";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "Unable to save action item";
  } finally {
    busy.value = false;
  }
}

onMounted(() => void loadList().catch((cause: unknown) => {
  error.value = cause instanceof Error ? cause.message : "Unable to load conversations";
}));
</script>

<template>
  <section class="ai-workspace">
    <aside
      class="ai-conversation-list"
      aria-label="AI conversations"
    >
      <h1>{{ copy.title }}</h1>
      <div
        class="ai-disclosure"
        role="note"
      >
        <p>{{ copy.disclosure }}</p>
        <label><input
          v-model="disclosureAccepted"
          type="checkbox"
        > {{ copy.accept }}</label>
        <label><input
          v-model="memoryOptIn"
          type="checkbox"
        > {{ copy.memory }}</label>
        <button
          type="button"
          :disabled="!disclosureAccepted || busy"
          @click="createConversation"
        >
          {{ copy.newChat }}
        </button>
      </div>
      <button
        v-for="conversation in conversations"
        :key="conversation.id"
        class="ai-conversation-button"
        :class="{ active: selected?.id === conversation.id }"
        type="button"
        @click="choose(conversation.id)"
      >
        <strong>{{ conversation.conversation_number }}</strong>
        <small>{{ conversation.primary_topic ?? conversation.status }}</small>
      </button>
    </aside>

    <div class="ai-chat-panel">
      <p
        v-if="error"
        class="form-error"
        role="alert"
      >
        {{ error }}
      </p>
      <p
        v-if="notice"
        class="form-success"
        role="status"
      >
        {{ notice }}
      </p>
      <p
        v-if="!selected"
        class="empty-state"
      >
        {{ copy.empty }}
      </p>
      <template v-else>
        <header class="ai-chat-header">
          <div>
            <strong>{{ selected.conversation_number }}</strong>
            <small>{{ selected.status }} · {{ selected.memory_consent_status }}</small>
          </div>
          <label><input
            v-model="memoryOptIn"
            type="checkbox"
            @change="changeMemory"
          > {{ copy.memory }}</label>
          <button
            type="button"
            class="danger-link"
            @click="removeConversation"
          >
            {{ copy.delete }}
          </button>
        </header>
        <div
          class="ai-message-stream"
          aria-live="polite"
        >
          <article
            v-for="message in messages"
            :key="message.id"
            :class="['ai-message', message.role]"
          >
            <p>{{ message.content }}</p>
            <div
              v-if="message.role === 'assistant'"
              class="ai-feedback"
            >
              <button
                type="button"
                aria-label="Helpful"
                @click="aiAssistantApi.feedback(message.id, 'up')"
              >
                👍
              </button>
              <button
                type="button"
                aria-label="Not helpful"
                @click="aiAssistantApi.feedback(message.id, 'down')"
              >
                👎
              </button>
            </div>
          </article>
        </div>
        <section
          v-if="latestTurn?.citations?.length"
          class="ai-citations"
        >
          <h2>{{ copy.sources }}</h2>
          <article
            v-for="citation in latestTurn.citations"
            :key="citation.citation_id"
          >
            <strong>{{ citation.document_code }}</strong>
            <p v-if="citation.excerpt">
              {{ citation.excerpt }}
            </p>
          </article>
        </section>
        <section
          v-if="latestTurn?.structured?.action_suggestions?.length"
          class="ai-action-items"
        >
          <button
            type="button"
            @click="pendingAction = latestTurn?.structured?.action_suggestions?.[0] ?? ''"
          >
            {{ copy.saveAction }}
          </button>
          <div
            v-if="pendingAction"
            class="ai-confirmation"
            role="dialog"
            aria-label="Tool confirmation"
          >
            <p>{{ pendingAction }}</p>
            <button
              type="button"
              :disabled="busy"
              @click="saveActionItem"
            >
              {{ copy.confirmAction }}
            </button>
            <button
              type="button"
              @click="pendingAction = ''"
            >
              {{ copy.cancel }}
            </button>
          </div>
        </section>
        <p
          v-if="selected.status === 'safety_paused'"
          class="ai-safety-pause"
          role="alert"
        >
          {{ copy.paused }}
        </p>
        <form
          class="ai-composer"
          @submit.prevent="send"
        >
          <textarea
            v-model="draft"
            :placeholder="copy.placeholder"
            :disabled="busy || selected.status === 'safety_paused'"
          />
          <button
            type="submit"
            :disabled="busy || !draft.trim() || selected.status === 'safety_paused'"
          >
            {{ copy.send }}
          </button>
        </form>
      </template>
    </div>
  </section>
</template>
