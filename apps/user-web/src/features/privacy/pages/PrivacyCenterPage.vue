<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  privacyApi,
  type Consent,
  type MemoryItem,
  type PrivacyProfile,
  type PrivacyRequest
} from "@/features/privacy/api";

type PrivacySettings = {
  privacy_mode: "strict" | "balanced" | "custom";
  searchable_by_platform_users: boolean;
  visible_in_activity_directory: boolean;
  visible_in_matchmaking: boolean;
  allow_contact_exchange_after_mutual_confirmation: boolean;
  allow_profile_use_by_ai: boolean;
  allow_service_history_use_by_ai: boolean;
  settings_version: number;
  field_rules: unknown[];
};
type MemoryPreferences = {
  long_term_memory_enabled: boolean;
  allow_profile_facts: boolean;
  allow_service_history: boolean;
  allow_relationship_context: boolean;
  allow_cross_conversation_use: boolean;
  settings_version: number;
};

const route = useRoute();
const busy = ref(false);
const error = ref("");
const notice = ref("");
const profile = ref<PrivacyProfile>();
const settings = ref<PrivacySettings>();
const consents = ref<Consent[]>([]);
const requests = ref<PrivacyRequest[]>([]);
const memories = ref<MemoryItem[]>([]);
const memoryPreferences = ref<MemoryPreferences>();
const password = ref("");
const correctionReason = ref("Please correct this account profile value.");
const profileForm = reactive({ display_name: "", city: "", region: "", public_bio: "" });

const section = computed(() => {
  const name = String(route.name ?? "");
  if (name.includes("ai-memory")) return "memory";
  if (name.includes("consent")) return "consents";
  if (name.includes("profile") || name.includes("contact")) return "profile";
  if (name.includes("privacy-request") || name.includes("export") || name.includes("correction") || name.includes("erasure")) return "requests";
  return "settings";
});
const locale = computed(() => String(route.params.locale));

function applyProfile(value: PrivacyProfile) {
  profile.value = value;
  profileForm.display_name = value.display_name ?? "";
  profileForm.city = value.city ?? "";
  profileForm.region = value.region ?? "";
  profileForm.public_bio = value.public_bio ?? "";
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    const [profileValue, settingsValue, consentValue, requestValue, memoryValue, memoryPreferenceValue] = await Promise.all([
      privacyApi<PrivacyProfile>("/account/profile"),
      privacyApi<PrivacySettings>("/account/privacy/settings"),
      privacyApi<{ items: Consent[] }>("/account/consents"),
      privacyApi<{ items: PrivacyRequest[] }>("/account/privacy/requests"),
      privacyApi<{ items: MemoryItem[] }>("/account/ai-memory/items"),
      privacyApi<MemoryPreferences>("/account/ai-memory/preferences")
    ]);
    applyProfile(profileValue);
    settings.value = settingsValue;
    consents.value = consentValue.items;
    requests.value = requestValue.items;
    memories.value = memoryValue.items;
    memoryPreferences.value = memoryPreferenceValue;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "隐私中心加载失败";
  } finally {
    busy.value = false;
  }
}

async function saveProfile() {
  if (!profile.value) return;
  const value = await privacyApi<PrivacyProfile>("/account/profile", {
    method: "PATCH",
    body: JSON.stringify({ ...profileForm, version: profile.value.version })
  });
  applyProfile(value);
  notice.value = "档案已保存并增加版本。";
}

async function saveSettings() {
  if (!settings.value) return;
  const payload = {
    ...settings.value,
    field_rules: settings.value.field_rules ?? []
  };
  const result = await privacyApi<{ settings_version: number }>("/account/privacy/settings", {
    method: "PUT",
    body: JSON.stringify(payload)
  });
  settings.value.settings_version = result.settings_version;
  notice.value = "隐私设置已保存并使权限缓存失效。";
}

async function changeConsent(item: Consent) {
  const grant = item.status !== "granted";
  await privacyApi(`/account/consents/${item.consent_code}/${grant ? "grant" : "withdraw"}`, {
    method: "POST",
    body: grant ? JSON.stringify({ release_id: item.release_id, evidence: { source: "user_privacy_web" } }) : undefined
  });
  notice.value = grant ? "同意已记录到具体版本。" : "同意已撤回并传播到关联服务。";
  await load();
}

async function requestInventory() {
  await privacyApi("/account/privacy/data-inventory", { method: "POST" });
  notice.value = "数据清单已生成。";
  await load();
}

async function requestExport() {
  await privacyApi("/account/privacy/exports", {
    method: "POST",
    body: JSON.stringify({ password: password.value, requested_format: "json", modules: [] })
  });
  password.value = "";
  notice.value = "加密导出请求已验证，后台任务将逐模块处理。";
  await load();
}

async function requestCorrection() {
  await privacyApi("/account/privacy/corrections", {
    method: "POST",
    body: JSON.stringify({ items: [{ module_code: "identity", entity_reference_type: "profile", field_path: "display_name", requested_value: profileForm.display_name, reason: correctionReason.value }] })
  });
  notice.value = "更正请求已提交；历史事实不会被静默覆盖。";
  await load();
}

async function requestErasure() {
  await privacyApi("/account/privacy/erasures", {
    method: "POST",
    body: JSON.stringify({ password: password.value, requested_scope: ["all"], confirmation: "REQUEST_ACCOUNT_ERASURE" })
  });
  password.value = "";
  notice.value = "删除影响计划已生成；有效服务与留置将阻止执行。";
  await load();
}

async function updateMemoryPreferences() {
  if (!memoryPreferences.value) return;
  const payload = { ...memoryPreferences.value, delete_existing_when_disabled: false };
  const result = await privacyApi<{ settings_version: number }>("/account/ai-memory/preferences", { method: "PUT", body: JSON.stringify(payload) });
  memoryPreferences.value.settings_version = result.settings_version;
  notice.value = "AI 记忆设置已更新；关闭后读写均停止。";
}

async function memoryAction(item: MemoryItem, action: "approve" | "reject" | "delete") {
  await privacyApi(`/account/ai-memory/items/${item.id}${action === "delete" ? "" : `/${action}`}`, { method: action === "delete" ? "DELETE" : "POST" });
  await load();
}

async function clearMemory() {
  await privacyApi("/account/ai-memory/clear-all", { method: "POST" });
  notice.value = "长期记忆、向量与缓存引用已清理。";
  await load();
}

onMounted(() => void load());
watch(() => route.fullPath, () => { notice.value = ""; });
</script>

<template>
  <section class="privacy-center">
    <p class="eyebrow">
      BATCH 12 · PRIVACY CONTROL PLANE
    </p>
    <h1>隐私与数据中心</h1>
    <p>严格模式默认开启。导出、删除、同意和 AI 记忆均采用独立授权与可审计流程。</p>
    <nav
      class="privacy-tabs"
      aria-label="隐私中心导航"
    >
      <RouterLink :to="`/${locale}/account/profile`">
        个人档案
      </RouterLink>
      <RouterLink :to="`/${locale}/account/privacy`">
        隐私设置
      </RouterLink>
      <RouterLink :to="`/${locale}/account/consents`">
        同意管理
      </RouterLink>
      <RouterLink :to="`/${locale}/account/privacy/requests`">
        数据请求
      </RouterLink>
      <RouterLink :to="`/${locale}/account/ai-memory`">
        AI 记忆
      </RouterLink>
    </nav>
    <p
      v-if="busy"
      role="status"
    >
      正在加载隐私控制面…
    </p>
    <p
      v-if="error"
      role="alert"
    >
      {{ error }}
    </p>
    <p
      v-if="notice"
      role="status"
    >
      {{ notice }}
    </p>

    <form
      v-if="section === 'profile' && profile"
      class="privacy-card"
      @submit.prevent="saveProfile"
    >
      <h2>个人档案</h2>
      <p>档案版本 {{ profile.version }} · 完整度 {{ profile.completeness_basis_points / 100 }}%</p>
      <label>显示名称<input v-model="profileForm.display_name"></label>
      <label>城市<input v-model="profileForm.city"></label>
      <label>地区<input v-model="profileForm.region"></label>
      <label>公开简介<textarea v-model="profileForm.public_bio" /></label>
      <button
        class="primary-button"
        type="submit"
      >
        保存档案
      </button>
      <p>联系方式独立加密保存，默认仅本人可见，不会因档案公开而自动交换。</p>
    </form>

    <form
      v-if="section === 'settings' && settings"
      class="privacy-card"
      @submit.prevent="saveSettings"
    >
      <h2>隐私设置</h2>
      <label>隐私模式<select v-model="settings.privacy_mode"><option value="strict">严格</option><option value="balanced">平衡</option><option value="custom">自定义</option></select></label>
      <label><input
        v-model="settings.searchable_by_platform_users"
        type="checkbox"
        :disabled="settings.privacy_mode === 'strict'"
      >允许平台用户搜索</label>
      <label><input
        v-model="settings.visible_in_activity_directory"
        type="checkbox"
        :disabled="settings.privacy_mode === 'strict'"
      >显示在活动名录</label>
      <label><input
        v-model="settings.allow_profile_use_by_ai"
        type="checkbox"
        :disabled="settings.privacy_mode === 'strict'"
      >允许 AI 使用档案</label>
      <button
        class="primary-button"
        type="submit"
      >
        保存隐私设置
      </button>
    </form>

    <div
      v-if="section === 'consents'"
      class="privacy-card"
    >
      <h2>同意管理</h2>
      <article
        v-for="item in consents"
        :key="item.consent_code"
        class="consent-row"
      >
        <div><strong>{{ item.title }}</strong><p>{{ item.summary }}</p><small>版本 {{ item.semantic_version }} · {{ item.status }}</small></div>
        <button
          v-if="item.withdrawable || item.status !== 'granted'"
          type="button"
          @click="changeConsent(item)"
        >
          {{ item.status === 'granted' ? '撤回' : '同意' }}
        </button>
      </article>
      <p>外部模型训练默认未授权，且不会与 AI 助手或长期记忆同意合并。</p>
    </div>

    <div
      v-if="section === 'requests'"
      class="privacy-card"
    >
      <h2>数据请求</h2>
      <div class="request-actions">
        <button
          type="button"
          @click="requestInventory"
        >
          生成数据清单
        </button>
        <input
          v-model="password"
          type="password"
          aria-label="当前密码"
          placeholder="导出或删除需重新验证密码"
        >
        <button
          type="button"
          @click="requestExport"
        >
          请求加密导出
        </button>
        <button
          type="button"
          @click="requestCorrection"
        >
          请求更正显示名称
        </button>
        <button
          type="button"
          class="danger-button"
          @click="requestErasure"
        >
          生成账户删除影响计划
        </button>
      </div>
      <table>
        <thead><tr><th>编号</th><th>类型</th><th>状态</th><th>提交时间</th></tr></thead><tbody>
          <tr
            v-for="item in requests"
            :key="item.id"
          >
            <td>{{ item.request_number }}</td><td>{{ item.request_type }}</td><td>{{ item.status }}</td><td>{{ item.submitted_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div
      v-if="section === 'memory' && memoryPreferences"
      class="privacy-card"
    >
      <h2>AI 长期记忆</h2>
      <p>长期记忆默认关闭；模型推断不是用户确认事实，并需用户复核。</p>
      <label><input
        v-model="memoryPreferences.long_term_memory_enabled"
        type="checkbox"
      >启用长期记忆（须先授予独立同意）</label>
      <label><input
        v-model="memoryPreferences.allow_profile_facts"
        type="checkbox"
      >允许档案事实</label>
      <label><input
        v-model="memoryPreferences.allow_cross_conversation_use"
        type="checkbox"
      >允许跨会话使用</label>
      <button
        type="button"
        @click="updateMemoryPreferences"
      >
        保存记忆设置
      </button>
      <button
        type="button"
        class="danger-button"
        @click="clearMemory"
      >
        清除全部长期记忆
      </button>
      <article
        v-for="item in memories"
        :key="item.id"
        class="memory-row"
      >
        <div><strong>{{ item.memory_type }}</strong><p>{{ item.content }}</p><small>{{ item.certainty }} · {{ item.status }}</small></div><div>
          <button
            v-if="item.status === 'user_approval_required'"
            @click="memoryAction(item, 'approve')"
          >
            确认
          </button><button
            v-if="item.status === 'user_approval_required'"
            @click="memoryAction(item, 'reject')"
          >
            拒绝
          </button><button @click="memoryAction(item, 'delete')">
            删除
          </button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.privacy-center { max-width: 1080px; margin: 0 auto; padding: 7rem 1.5rem 5rem; }
.privacy-tabs, .request-actions { display: flex; gap: .75rem; flex-wrap: wrap; margin: 1.5rem 0; }
.privacy-tabs a { padding: .65rem 1rem; border: 1px solid #c9b7a8; border-radius: 999px; }
.privacy-tabs a.router-link-active { background: #3f3028; color: white; }
.privacy-card { background: #fffaf5; border: 1px solid #e4d8ce; border-radius: 1rem; padding: 1.5rem; }
.privacy-card label { display: grid; gap: .35rem; margin: 1rem 0; }
.privacy-card input, .privacy-card textarea, .privacy-card select { padding: .7rem; border: 1px solid #b9aaa0; border-radius: .4rem; }
.consent-row, .memory-row { display: flex; justify-content: space-between; gap: 1rem; border-top: 1px solid #e4d8ce; padding: 1rem 0; }
table { width: 100%; border-collapse: collapse; margin-top: 1.5rem; } th, td { text-align: left; padding: .7rem; border-bottom: 1px solid #e4d8ce; }
.danger-button { color: #8a1f1f; }
</style>
