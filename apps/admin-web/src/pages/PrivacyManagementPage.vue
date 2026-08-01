<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { catalogApi } from "@/features/catalog/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

type Dashboard = { requests: Array<{ request_type: string; status: string; count: number }>; blocked_erasures: number; active_holds: number; break_glass_pending: number; retention_due: number };
type Row = Record<string, unknown> & { id?: string; status?: string };

const route = useRoute();
const auth = useAdminAuthStore();
const section = ref(String(route.meta.privacySection ?? "dashboard"));
const dashboard = ref<Dashboard>();
const rows = ref<Row[]>([]);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const reason = ref("Batch 12 governed privacy operation.");

const sections = [
  ["dashboard", "总览", "privacy.requests.read"],
  ["requests", "数据权利请求", "privacy.requests.read"],
  ["exports", "加密导出", "privacy.exports.read"],
  ["consents", "同意注册表", "privacy.consents.read"],
  ["consent-releases", "同意版本", "privacy.consents.read"],
  ["inventory", "数据清单", "privacy.inventory.read"],
  ["processing", "处理活动", "privacy.inventory.read"],
  ["classifications", "敏感分类", "privacy.classifications.read"],
  ["corrections", "更正", "privacy.corrections.read"],
  ["erasures", "删除计划", "privacy.erasures.read"],
  ["retention", "保留策略", "privacy.retention.read"],
  ["retention-instances", "保留实例", "privacy.retention.read"],
  ["holds", "法律与调查留置", "privacy.holds.read"],
  ["break-glass", "紧急访问", "privacy.break_glass.read"],
  ["access-events", "敏感访问", "privacy.sensitive_access.read"],
  ["incidents", "隐私信号", "privacy.incidents.read"],
  ["audit", "隐私审计", "privacy.audit.read"]
] as const;

const endpointBySection: Record<string, string> = {
  requests: "/admin/privacy/requests",
  exports: "/admin/privacy/exports",
  consents: "/admin/privacy/consents",
  "consent-releases": "/admin/privacy/consent-releases",
  inventory: "/admin/privacy/data-inventory",
  processing: "/admin/privacy/processing-activities",
  classifications: "/admin/privacy/classifications",
  corrections: "/admin/privacy/corrections",
  erasures: "/admin/privacy/erasures",
  retention: "/admin/privacy/retention-policies",
  "retention-instances": "/admin/privacy/retention-instances",
  holds: "/admin/privacy/legal-holds",
  "break-glass": "/admin/privacy/break-glass",
  "access-events": "/admin/privacy/access-events",
  incidents: "/admin/privacy/incidents",
  audit: "/admin/privacy/audit"
};

async function load() {
  busy.value = true;
  error.value = "";
  rows.value = [];
  try {
    await auth.bootstrap();
    if (section.value === "dashboard") {
      dashboard.value = await catalogApi<Dashboard>("/admin/privacy/dashboard");
    } else {
      const result = await catalogApi<{ items: Row[] }>(endpointBySection[section.value]);
      rows.value = result.items;
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "隐私运营中心加载失败";
  } finally {
    busy.value = false;
  }
}

async function switchSection(value: string) {
  section.value = value;
  notice.value = "";
  await load();
}

async function requestAction(row: Row, action: "approve" | "reject") {
  await catalogApi(`/admin/privacy/requests/${row.id}/${action}`, {
    method: "POST",
    body: JSON.stringify({ reason: reason.value, user_visible_message: action === "approve" ? "Your request was approved for governed processing." : "Your request could not be approved after review." })
  });
  notice.value = "请求决策已记录，用户只会看到安全说明。";
  await load();
}

async function correctionAction(row: Row, action: "approve" | "reject") {
  await catalogApi(`/admin/privacy/corrections/${row.id}/${action}`, {
    method: "POST",
    body: JSON.stringify({ reason: reason.value, user_visible_message: action === "approve" ? "Correction approved; historical facts remain preserved." : "Correction rejected after review." })
  });
  await load();
}

async function erasureAction(row: Row, action: "replan" | "approve" | "execute") {
  await catalogApi(`/admin/privacy/erasures/${row.id}/${action}`, {
    method: "POST",
    body: action === "approve" ? JSON.stringify({ reason: reason.value }) : undefined
  });
  notice.value = "删除计划已重新校验；阻断、留存例外和模块结果保持可见。";
  await load();
}

async function retentionRun() {
  const result = await catalogApi<{ items: Row[] }>("/admin/privacy/workers/retention/run", { method: "POST" });
  notice.value = `已评估 ${result.items.length} 个到期实例；有效留置不会被绕过。`;
  await load();
}

async function breakGlassAction(row: Row, action: "approve" | "use") {
  await catalogApi(`/admin/privacy/break-glass/${row.id}/${action}`, {
    method: "POST",
    body: action === "approve" ? JSON.stringify({ reason: reason.value }) : undefined
  });
  notice.value = "紧急访问操作已按独立审批、短时授权和逐资产审计处理。";
  await load();
}

onMounted(() => void load());
</script>

<template>
  <section class="admin-page privacy-admin-page">
    <div class="page-heading">
      <div>
        <p class="admin-kicker">
          BATCH 12 · DATA RIGHTS & GOVERNANCE
        </p><h2>隐私运营中心</h2><p>统一处理数据权利、同意版本、数据清单、删除、保留、留置与敏感访问。</p>
      </div>
      <el-button
        :loading="busy"
        @click="load"
      >
        刷新
      </el-button>
    </div>
    <el-alert
      title="敏感字段值、导出令牌、留置原因和调查细节默认不显示；遮罩不替代授权。"
      type="warning"
      :closable="false"
    />
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
    />
    <el-alert
      v-if="notice"
      :title="notice"
      type="success"
      show-icon
    />
    <el-input
      v-model="reason"
      aria-label="隐私操作原因"
      class="operation-reason"
    />
    <el-tabs
      :model-value="section"
      @update:model-value="switchSection(String($event))"
    >
      <el-tab-pane
        v-for="item in sections.filter((value) => auth.hasPermission(value[2]))"
        :key="item[0]"
        :name="item[0]"
        :label="item[1]"
      />
    </el-tabs>

    <div
      v-if="section === 'dashboard' && dashboard"
      class="metric-grid"
      aria-label="隐私总览"
    >
      <el-card><strong>{{ dashboard.blocked_erasures }}</strong><span>受阻删除</span></el-card>
      <el-card><strong>{{ dashboard.active_holds }}</strong><span>有效留置</span></el-card>
      <el-card><strong>{{ dashboard.break_glass_pending }}</strong><span>待批紧急访问</span></el-card>
      <el-card><strong>{{ dashboard.retention_due }}</strong><span>到期保留实例</span></el-card>
      <el-card
        v-for="item in dashboard.requests"
        :key="`${item.request_type}-${item.status}`"
      >
        <strong>{{ item.count }}</strong><span>{{ item.request_type }} · {{ item.status }}</span>
      </el-card>
    </div>

    <div v-else>
      <el-button
        v-if="section === 'retention' && auth.hasPermission('privacy.retention.execute')"
        @click="retentionRun"
      >
        执行到期评估
      </el-button>
      <el-table
        :data="rows"
        empty-text="暂无记录"
      >
        <el-table-column
          prop="request_number"
          label="编号"
        />
        <el-table-column
          prop="consent_code"
          label="Consent Code"
        />
        <el-table-column
          prop="asset_code"
          label="Data Asset"
        />
        <el-table-column
          prop="policy_code"
          label="Policy"
        />
        <el-table-column
          prop="event_type"
          label="事件"
        />
        <el-table-column
          prop="user_anonymous_id"
          label="匿名用户"
        />
        <el-table-column
          prop="request_type"
          label="类型"
        />
        <el-table-column
          prop="module_code"
          label="模块"
        />
        <el-table-column
          prop="sensitivity"
          label="敏感级别"
        />
        <el-table-column
          prop="status"
          label="状态"
        />
        <el-table-column
          label="操作"
          min-width="260"
        >
          <template #default="scope">
            <template v-if="section === 'requests' && auth.hasPermission('privacy.requests.approve')">
              <el-button
                size="small"
                @click="requestAction(scope.row, 'approve')"
              >
                批准
              </el-button><el-button
                size="small"
                @click="requestAction(scope.row, 'reject')"
              >
                拒绝
              </el-button>
            </template>
            <template v-if="section === 'corrections' && auth.hasPermission('privacy.corrections.review') && scope.row.status === 'review_required'">
              <el-button
                size="small"
                @click="correctionAction(scope.row, 'approve')"
              >
                批准更正
              </el-button><el-button
                size="small"
                @click="correctionAction(scope.row, 'reject')"
              >
                拒绝
              </el-button>
            </template>
            <template v-if="section === 'erasures'">
              <el-button
                v-if="auth.hasPermission('privacy.erasures.plan')"
                size="small"
                @click="erasureAction(scope.row, 'replan')"
              >
                重新规划
              </el-button><el-button
                v-if="auth.hasPermission('privacy.erasures.approve')"
                size="small"
                @click="erasureAction(scope.row, 'approve')"
              >
                批准
              </el-button><el-button
                v-if="auth.hasPermission('privacy.erasures.execute')"
                size="small"
                @click="erasureAction(scope.row, 'execute')"
              >
                执行
              </el-button>
            </template>
            <template v-if="section === 'break-glass'">
              <el-button
                v-if="auth.hasPermission('privacy.break_glass.approve') && scope.row.status === 'requested'"
                size="small"
                @click="breakGlassAction(scope.row, 'approve')"
              >
                独立批准
              </el-button><el-button
                v-if="auth.hasPermission('privacy.break_glass.use') && scope.row.status === 'approved'"
                size="small"
                @click="breakGlassAction(scope.row, 'use')"
              >
                使用授权
              </el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <p>基线策略已有限期，但司法辖区法律文本、正式保留期限和生产审批仍是外部门禁，当前不作认证声明。</p>
  </section>
</template>

<style scoped>
.operation-reason { margin: 1rem 0; max-width: 720px; }
.metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1rem; }
.metric-grid :deep(.el-card__body) { display: grid; gap: .4rem; }
.metric-grid strong { font-size: 1.8rem; }
</style>
