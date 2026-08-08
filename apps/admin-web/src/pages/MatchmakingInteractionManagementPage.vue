<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  matchmakingInteractionAdminApi,
  type InteractionAdminRow
} from "@/features/matchmaking-interactions/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();
const section = computed(() => String(route.meta.interactionSection ?? "dashboard"));
const detailId = computed(() => String(route.params.id ?? ""));
const rows = ref<InteractionAdminRow[]>([]);
const summary = ref<Record<string, unknown>>({});
const detail = ref<Record<string, unknown>>();
const boundary = ref("");
const reason = ref("");
const purpose = ref("");
const busy = ref(false);
const error = ref("");
const notice = ref("");

const sections = [
  ["dashboard", "运行概览", "matchmaking.analytics.read"],
  ["pairs", "用户对诊断", "matchmaking.interactions.read"],
  ["matches", "互选记录", "matchmaking.matches.read"],
  ["invitations", "认识邀请", "matchmaking.invitations.read"],
  ["contact-exchanges", "联系方式授权", "matchmaking.contact_exchange.read"],
  ["invalidations", "失效中心", "matchmaking.interactions.read"],
  ["dead-letters", "死信中心", "matchmaking.dead_letters.resolve"],
  ["incidents", "事件中心", "matchmaking.incidents.read"],
  ["audit", "互动审计", "matchmaking.audit.read"]
] as const;
const visibleSections = computed(() => sections.filter((item) => auth.hasPermission(item[2])));

async function load() {
  busy.value = true;
  error.value = "";
  rows.value = [];
  summary.value = {};
  detail.value = undefined;
  boundary.value = "";
  try {
    await auth.bootstrap();
    if (section.value === "dashboard") {
      summary.value = await matchmakingInteractionAdminApi.dashboard();
      summary.value = {
        ...summary.value,
        ...(await matchmakingInteractionAdminApi.duplicates())
      };
    } else if (section.value === "pairs") {
      rows.value = await matchmakingInteractionAdminApi.pairs();
      if (detailId.value) detail.value = await matchmakingInteractionAdminApi.pair(detailId.value);
    } else if (section.value === "matches") {
      rows.value = await matchmakingInteractionAdminApi.matches();
    } else if (section.value === "invitations") {
      rows.value = await matchmakingInteractionAdminApi.invitations();
    } else if (section.value === "contact-exchanges") {
      rows.value = await matchmakingInteractionAdminApi.contactExchanges();
      if (detailId.value) {
        detail.value = await matchmakingInteractionAdminApi.contactExchange(detailId.value);
      }
    } else if (section.value === "invalidations") {
      rows.value = await matchmakingInteractionAdminApi.invalidations();
    } else if (section.value === "dead-letters") {
      rows.value = await matchmakingInteractionAdminApi.deadLetters();
    } else if (section.value === "incidents") {
      const result = await matchmakingInteractionAdminApi.incidents();
      rows.value = result.incidents;
      boundary.value = result.boundary;
    } else {
      rows.value = await matchmakingInteractionAdminApi.audit();
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "互动运营中心加载失败";
  } finally {
    busy.value = false;
  }
}

function requirementsReady() {
  if (reason.value.trim().length >= 3 && purpose.value.trim().length >= 4) return true;
  error.value = "高风险操作必须填写原因和用途，二者都会进入不可变审计记录。";
  return false;
}

async function run(action: () => Promise<unknown>, message: string) {
  if (!requirementsReady()) return;
  if (!window.confirm("该操作会使互动或联系方式授权立即失效。确定继续吗？")) return;
  busy.value = true;
  try {
    await action();
    notice.value = message;
    await load();
    notice.value = message;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "运营操作失败";
  } finally {
    busy.value = false;
  }
}

function rowId(row: InteractionAdminRow) {
  return String(row.pair_id ?? row.id ?? row.mutual_match_id ?? "");
}

watch(() => route.fullPath, load);
onMounted(load);
</script>

<template>
  <section class="interaction-admin">
    <p class="eyebrow">
      BATCH 15 · INTERACTION OPERATIONS
    </p>
    <h2>互动运营中心</h2>
    <el-alert
      title="运营人员不能代替用户喜欢、接受、婉拒或同意交换联系方式；默认页面不展示单向选择、理由或联系方式。"
      type="warning"
      :closable="false"
    />

    <nav class="tabs">
      <RouterLink
        v-for="item in visibleSections"
        :key="item[0]"
        :to="`/admin/matchmaking-interactions/${item[0]}`"
      >
        {{ item[1] }}
      </RouterLink>
    </nav>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
    />
    <el-alert
      v-if="notice"
      :title="notice"
      type="success"
      :closable="false"
    />
    <p v-if="busy">
      正在加载…
    </p>
    <p
      v-if="boundary"
      class="boundary"
    >
      {{ boundary }}
    </p>

    <dl
      v-if="section === 'dashboard'"
      class="metrics"
    >
      <div
        v-for="(value, key) in summary"
        :key="key"
      >
        <dt>{{ key }}</dt><dd>{{ value }}</dd>
      </div>
    </dl>

    <article
      v-if="detail"
      class="detail"
    >
      <h3>受限诊断详情</h3>
      <pre>{{ JSON.stringify(detail, null, 2) }}</pre>
    </article>

    <el-table
      v-if="rows.length"
      :data="rows"
      stripe
    >
      <el-table-column
        label="标识"
        min-width="210"
      >
        <template #default="scope">
          {{ rowId(scope.row) }}
        </template>
      </el-table-column>
      <el-table-column
        prop="status"
        label="状态"
        width="150"
      />
      <el-table-column
        label="安全摘要"
        min-width="260"
      >
        <template #default="scope">
          <code>{{ JSON.stringify(scope.row) }}</code>
        </template>
      </el-table-column>
      <el-table-column
        label="操作"
        width="210"
      >
        <template #default="scope">
          <RouterLink
            v-if="section === 'pairs'"
            :to="`/admin/matchmaking-interactions/pairs/${scope.row.pair_id}`"
          >
            诊断
          </RouterLink>
          <RouterLink
            v-if="section === 'contact-exchanges'"
            :to="`/admin/matchmaking-interactions/contact-exchanges/${scope.row.id}`"
          >
            查看授权状态
          </RouterLink>
          <el-button
            v-if="section === 'pairs' && auth.hasPermission('matchmaking.matches.invalidate')"
            size="small"
            type="danger"
            @click="run(() => matchmakingInteractionAdminApi.invalidatePair(String(scope.row.pair_id), reason, purpose), '用户对互动已失效。')"
          >
            失效
          </el-button>
          <el-button
            v-if="section === 'contact-exchanges' && auth.hasPermission('matchmaking.contact_exchange.revoke')"
            size="small"
            type="danger"
            @click="run(() => matchmakingInteractionAdminApi.revokeContactExchange(String(scope.row.id), reason, purpose), '联系方式授权已撤销。')"
          >
            撤销授权
          </el-button>
          <el-button
            v-if="section === 'dead-letters' && auth.hasPermission('matchmaking.dead_letters.resolve')"
            size="small"
            @click="run(() => matchmakingInteractionAdminApi.resolveDeadLetter(String(scope.row.id), reason), '死信已记录人工处置。')"
          >
            处置
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div
      v-if="['pairs','contact-exchanges','dead-letters'].includes(section)"
      class="operation-context"
    >
      <label>操作原因<input
        v-model="reason"
        maxlength="128"
      ></label>
      <label>访问/操作用途<input
        v-model="purpose"
        maxlength="128"
      ></label>
    </div>
  </section>
</template>

<style scoped>
.interaction-admin { display: flex; flex-direction: column; gap: 1rem; }
.eyebrow { letter-spacing: .14em; font-size: .75rem; color: #64748b; }
.tabs { display: flex; flex-wrap: wrap; gap: .8rem; }
.metrics { display: grid; grid-template-columns: repeat(auto-fit,minmax(180px,1fr)); gap: .8rem; }
.metrics div, .detail, .operation-context { padding: 1rem; border: 1px solid #dbe2ea; border-radius: .6rem; }
.metrics dt { color: #64748b; font-size: .8rem; }
.metrics dd { margin: .3rem 0 0; font-size: 1.2rem; font-weight: 600; }
.detail pre { max-height: 32rem; overflow: auto; white-space: pre-wrap; }
.operation-context { display: flex; gap: 1rem; flex-wrap: wrap; }
.operation-context label { display: flex; flex-direction: column; gap: .35rem; min-width: 18rem; }
.boundary { padding: .8rem; background: #fff7ed; color: #9a3412; }
code { font-size: .72rem; white-space: normal; overflow-wrap: anywhere; }
</style>
