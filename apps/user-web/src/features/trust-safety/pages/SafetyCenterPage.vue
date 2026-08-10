<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { safetyApi, type SafetyBlock, type SafetyReport } from "@/features/trust-safety/api";

const route = useRoute();
const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const supportOnly = computed(() => route.path.endsWith("/safety-support"));
const reports = ref<SafetyReport[]>([]);
const blocks = ref<SafetyBlock[]>([]);
const restrictions = ref<Record<string, unknown>>({});
const appeals = ref<Array<Record<string, unknown>>>([]);
const reportedUserId = ref("");
const category = ref("harassment");
const description = ref("");
const blockTogether = ref(true);
const immediateDanger = ref(false);
const evidenceReportId = ref("");
const evidenceContent = ref("");
const appealRestrictionId = ref("");
const appealReason = ref("");
const busy = ref(false);
const error = ref("");
const notice = ref("");

async function load() {
  if (supportOnly.value) return;
  busy.value = true;
  error.value = "";
  try {
    [reports.value, blocks.value, restrictions.value, appeals.value] = await Promise.all([
      safetyApi.reports(),
      safetyApi.blocks(),
      safetyApi.restrictions(),
      safetyApi.appeals()
    ]);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "安全中心加载失败";
  } finally {
    busy.value = false;
  }
}

async function submitReport() {
  if (!reportedUserId.value.trim()) return;
  busy.value = true;
  try {
    await safetyApi.report({
      target_type: "user",
      reported_user_id: reportedUserId.value.trim(),
      category: category.value,
      description: description.value || undefined,
      block_user: blockTogether.value,
      immediate_danger: immediateDanger.value,
      idempotency_key: `safety-report-${crypto.randomUUID()}`,
      source_context: { surface: "user_safety_center" }
    });
    notice.value = blockTogether.value
      ? "举报已保密提交，对方也已立即被屏蔽。"
      : "举报已保密提交。";
    description.value = "";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "举报提交失败";
  } finally {
    busy.value = false;
  }
}

async function unblock(userId: string) {
  if (!window.confirm("解除屏蔽不会恢复旧邀请、互选、联系方式授权或关系旅程。继续吗？")) return;
  await safetyApi.unblock(userId);
  notice.value = "已解除主动屏蔽；历史访问不会自动恢复。";
  await load();
}

async function uploadEvidence() {
  if (!evidenceReportId.value || !evidenceContent.value.trim()) return;
  await safetyApi.uploadEvidence(evidenceReportId.value, {
    evidence_type: "text",
    content: evidenceContent.value.trim(),
    collection_reason: "reporter_submission"
  });
  evidenceContent.value = "";
  notice.value = "补充证据已加密保存并绑定完整性校验。";
}

async function submitAppeal() {
  if (appealReason.value.trim().length < 10) return;
  await safetyApi.appeal(appealRestrictionId.value, appealReason.value);
  notice.value = "申诉已提交，将由独立审核员复核。";
  appealReason.value = "";
  await load();
}

watch(() => route.fullPath, load);
onMounted(load);
</script>

<template>
  <main class="safety-center">
    <p class="eyebrow">
      BATCH 18 · TRUST &amp; SAFETY
    </p>
    <h1>{{ supportOnly ? "安全支持" : "安全中心" }}</h1>
    <p class="intro">
      如果你正面临即时人身危险，请优先联系当地紧急服务或可信任的人。VAV 不能替代警方、医疗或法律支持。
    </p>
    <section class="support panel">
      <h2>你不需要先与对方沟通</h2>
      <p>你可以立即屏蔽、撤销联系方式访问并保密举报。被举报者不会看到你的身份、描述、证据或案件优先级。</p>
      <RouterLink
        v-if="supportOnly"
        :to="`/${locale}/account/safety`"
        class="button"
      >
        进入我的安全中心
      </RouterLink>
    </section>

    <template v-if="!supportOnly">
      <p
        v-if="busy"
        role="status"
      >
        正在安全加载…
      </p>
      <p
        v-if="error"
        role="alert"
        class="alert error"
      >
        {{ error }}
      </p>
      <p
        v-if="notice"
        role="status"
        class="alert notice"
      >
        {{ notice }}
      </p>
      <section class="grid">
        <form
          class="panel"
          @submit.prevent="submitReport"
        >
          <h2>举报用户或内容</h2>
          <label>被举报用户 ID<input
            v-model="reportedUserId"
            required
            autocomplete="off"
          ></label>
          <label>类别<select v-model="category"><option value="harassment">骚扰</option><option value="threat">威胁</option><option value="fraud_or_scam">诈骗</option><option value="money_request">资金请求</option><option value="impersonation">冒充</option><option value="underage_concern">疑似未成年人</option><option value="privacy_violation">隐私侵犯</option><option value="other">其他</option></select></label>
          <label>补充说明<textarea
            v-model="description"
            maxlength="5000"
          /></label>
          <label class="check"><input
            v-model="blockTogether"
            type="checkbox"
          > 同时立即屏蔽</label>
          <label class="check"><input
            v-model="immediateDanger"
            type="checkbox"
          > 涉及即时人身安全</label>
          <button :disabled="busy">
            保密提交举报
          </button>
        </form>
        <article class="panel">
          <h2>我的举报</h2>
          <ul>
            <li
              v-for="item in reports"
              :key="item.id"
            >
              <div><strong>{{ item.report_number }}</strong><span>{{ item.category }} · {{ item.status }}</span></div><small>{{ item.submitted_at }}</small>
            </li>
          </ul>
          <p v-if="!reports.length">
            暂无举报。
          </p>
          <form @submit.prevent="uploadEvidence">
            <label>举报 ID<select
              v-model="evidenceReportId"
              required
            ><option
              value=""
              disabled
            >选择举报</option><option
              v-for="item in reports"
              :key="item.id"
              :value="item.id"
            >{{ item.report_number }}</option></select></label><label>补充证据<textarea
              v-model="evidenceContent"
              required
              maxlength="20000"
            /></label><button>加密上传证据</button>
          </form>
        </article>
        <article class="panel">
          <h2>我已屏蔽的用户</h2>
          <ul>
            <li
              v-for="item in blocks"
              :key="item.id"
            >
              <div><strong>{{ item.blocked_user_id }}</strong><span>{{ item.reason_code ?? "用户主动保护" }}</span></div><button
                class="secondary"
                @click="unblock(item.blocked_user_id)"
              >
                解除屏蔽
              </button>
            </li>
          </ul>
          <p v-if="!blocks.length">
            暂无主动屏蔽。
          </p>
        </article>
        <article class="panel">
          <h2>账号限制与申诉</h2>
          <pre>{{ JSON.stringify(restrictions, null, 2) }}</pre>
          <form @submit.prevent="submitAppeal">
            <label>限制 ID<input
              v-model="appealRestrictionId"
              required
            ></label><label>申诉理由<textarea
              v-model="appealReason"
              required
              minlength="10"
              maxlength="5000"
            /></label><button>提交独立复核</button>
          </form>
          <ul>
            <li
              v-for="item in appeals"
              :key="String(item.id)"
            >
              <strong>{{ item.appeal_number }}</strong><span>{{ item.status }} · {{ item.outcome ?? "待处理" }}</span>
            </li>
          </ul>
        </article>
      </section>
    </template>
  </main>
</template>

<style scoped>
.safety-center{max-width:1120px;margin:0 auto;padding:3rem 1.25rem 5rem}.eyebrow{letter-spacing:.14em;color:#8c3c35}.intro{max-width:820px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:1rem}.panel{display:grid;gap:.8rem;padding:1.25rem;border:1px solid #dfd7ce;border-radius:18px;background:#fff}.support{margin:1rem 0;background:#fff5ec}.panel label{display:grid;gap:.35rem}.check{display:flex!important;align-items:center;gap:.5rem}input,select,textarea{padding:.7rem;border:1px solid #c8c0b7;border-radius:10px}textarea{min-height:100px}button,.button{justify-self:start;padding:.7rem 1rem;border:0;border-radius:999px;background:#8c3c35;color:white;text-decoration:none}.secondary{background:#555}ul{display:grid;gap:.75rem;padding:0;list-style:none}li{display:flex;justify-content:space-between;gap:1rem;padding-bottom:.65rem;border-bottom:1px solid #eee}li div{display:grid}pre{max-height:220px;overflow:auto;padding:.75rem;background:#f5f3ef}.alert{padding:.8rem;border-radius:10px}.error{background:#fde8e7}.notice{background:#e7f4ed}
</style>
