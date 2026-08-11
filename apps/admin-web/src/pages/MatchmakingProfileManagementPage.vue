<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { localizeAdminLabel, localizeAdminValue } from "@vav/ui-admin";

import { catalogApi } from "@/features/catalog/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

type Row = Record<string, unknown> & { id?: string; status?: string };
type CaseDetail = Row & {
  items?: Row[];
  dating_profile_id?: string;
  profile_version_id?: string;
  version?: number;
  sensitive_access_granted?: boolean;
};
type Diff = {
  left_version: number;
  right_version: number;
  added_fields: string[];
  removed_fields: string[];
  changed_fields: string[];
  photo_changed: boolean;
  privacy_changed: boolean;
  preference_criteria_changed: boolean;
  requires_full_review: boolean;
};

const PHOTO_REASON_CODES = [
  "photo_not_clear",
  "photo_not_personal",
  "photo_contains_contact_information",
  "photo_contains_third_party_without_basis",
  "photo_inappropriate_content",
  "photo_suspected_impersonation",
  "photo_duplicate",
  "photo_quality_too_low",
  "manual_review_required"
] as const;

const sections = [
  ["profiles", "婚恋档案", "matchmaking.profiles.read"],
  ["reviews", "审核队列", "matchmaking.reviews.read"],
  ["photo-reviews", "照片审核", "matchmaking.photos.read"],
  ["schema-releases", "档案 Schema", "matchmaking.schemas.read"],
  ["taxonomies", "字典管理", "matchmaking.taxonomies.read"],
  ["projections", "推荐投影", "matchmaking.projections.read"],
  ["audit", "档案审计", "matchmaking.audit.read"]
] as const;

const endpointBySection: Record<string, string> = {
  profiles: "/admin/dating-profiles",
  reviews: "/admin/dating-profile-reviews",
  "photo-reviews": "/admin/dating-profile-photo-reviews",
  "schema-releases": "/admin/dating-schema-releases",
  taxonomies: "/admin/dating-taxonomies",
  projections: "/admin/dating-projections",
  audit: "/admin/dating-profile-audit"
};

const route = useRoute();
const auth = useAdminAuthStore();
const section = ref(String(route.meta.matchmakingSection ?? "reviews"));
const rows = ref<Row[]>([]);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const activeCase = ref<CaseDetail>();
const diff = ref<Diff>();
const userMessage = ref("请补充这一部分的说明，以便我们完成审核。");
const internalNote = ref("");
const reasonCode = ref("manual_review_required");

const visibleSections = computed(() => sections.filter((item) => auth.hasPermission(item[2])));
const canDecide = computed(() => auth.hasPermission("matchmaking.reviews.decide"));
const canReviewPhotos = computed(() => auth.hasPermission("matchmaking.photos.review"));
const canSuspend = computed(() => auth.hasPermission("matchmaking.profiles.suspend"));

async function load() {
  busy.value = true;
  error.value = "";
  rows.value = [];
  try {
    await auth.bootstrap();
    const result = await catalogApi<{ items: Row[] }>(endpointBySection[section.value]);
    rows.value = result.items ?? [];
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "婚恋档案运营中心加载失败";
  } finally {
    busy.value = false;
  }
}

async function switchSection(value: string) {
  section.value = value;
  notice.value = "";
  activeCase.value = undefined;
  diff.value = undefined;
  await load();
}

async function openCase(row: Row) {
  activeCase.value = await catalogApi<CaseDetail>(`/admin/dating-profile-reviews/${row.id}`);
  diff.value = undefined;
  const versionNumber = Number(row.version_number ?? 1);
  if (versionNumber > 1) {
    try {
      diff.value = await catalogApi<Diff>(
        `/admin/dating-profile-versions/${versionNumber - 1}/diff/${versionNumber}?profile_id=${String(row.dating_profile_id)}`
      );
    } catch {
      diff.value = undefined;
    }
  }
}

async function caseAction(
  action: "start" | "approve" | "request-changes" | "reject" | "escalate"
) {
  if (!activeCase.value) return;
  const body: Record<string, unknown> = { expected_version: activeCase.value.version };
  if (action === "approve") {
    body.user_message = userMessage.value;
    body.internal_summary = internalNote.value || null;
  }
  if (action === "request-changes") {
    body.user_message = userMessage.value;
    body.internal_summary = internalNote.value || null;
  }
  if (action === "reject") {
    body.reason_code = reasonCode.value;
    body.user_message = userMessage.value;
    body.internal_summary = internalNote.value || null;
  }
  if (action === "escalate") body.reason = internalNote.value || "需要更高权限复核。";
  try {
    await catalogApi(`/admin/dating-profile-reviews/${activeCase.value.id}/${action}`, {
      method: "POST",
      body: JSON.stringify(body)
    });
    notice.value = "审核决定已记录，用户只会看到安全说明，内部备注保持加密。";
    activeCase.value = undefined;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "审核操作失败";
  }
}

async function fieldDecision(fieldCode: string, decision: "approve" | "changes_required") {
  if (!activeCase.value) return;
  await catalogApi(`/admin/dating-profile-reviews/${activeCase.value.id}/items`, {
    method: "POST",
    body: JSON.stringify({
      item_type: "field",
      field_code: fieldCode,
      decision,
      reason_code: decision === "approve" ? null : reasonCode.value,
      user_message_safe: decision === "approve" ? null : userMessage.value,
      internal_note: internalNote.value || null
    })
  });
  notice.value = `字段 ${fieldCode} 的审核结果已记录。`;
  activeCase.value = await catalogApi<CaseDetail>(
    `/admin/dating-profile-reviews/${activeCase.value.id}`
  );
}

async function photoDecision(row: Row, decision: "approve" | "reject") {
  const caseId = window.prompt("请输入该照片所属的审核案件 ID");
  if (!caseId) return;
  await catalogApi(`/admin/dating-profile-reviews/${caseId}/items`, {
    method: "POST",
    body: JSON.stringify({
      item_type: "photo",
      photo_id: row.photo_id,
      decision,
      reason_code: decision === "approve" ? null : reasonCode.value,
      user_message_safe: decision === "approve" ? null : userMessage.value,
      internal_note: internalNote.value || null
    })
  });
  notice.value =
    decision === "approve"
      ? "照片已批准。自动检测结果仅作为辅助，不构成身份认定。"
      : "照片已拒绝，现有查看链接立即失效。";
  await load();
}

async function suspendProfile(row: Row) {
  await catalogApi(`/admin/dating-profiles/${row.id}/suspend`, {
    method: "POST",
    body: JSON.stringify({ reason_code: reasonCode.value })
  });
  notice.value = "档案已暂停并立即退出推荐池。";
  await load();
}

async function restoreProfile(row: Row) {
  await catalogApi(`/admin/dating-profiles/${row.id}/restore`, {
    method: "POST",
    body: JSON.stringify({ reason: internalNote.value || null })
  });
  notice.value = "档案已恢复展示。";
  await load();
}

async function rebuildProjection(row: Row) {
  await catalogApi(`/admin/dating-projections/${row.dating_profile_id}/rebuild`, {
    method: "POST"
  });
  notice.value = "推荐投影已按批准版本重建。";
  await load();
}

async function processJobs() {
  const result = await catalogApi<{ processed: number; failed: number }>(
    "/admin/dating-projections/process-jobs",
    { method: "POST" }
  );
  notice.value = `已处理 ${result.processed} 个投影任务，${result.failed} 个待重试。`;
  await load();
}

onMounted(() => void load());
</script>

<template>
  <section class="admin-page matchmaking-admin-page">
    <div class="page-heading">
      <div>
        <p class="admin-kicker">
          BATCH 13 · DATING PROFILE REVIEW
        </p>
        <h2>婚恋档案运营中心</h2>
        <p>审核档案版本、字段与照片，管理 Schema、字典与推荐投影。</p>
      </div>
      <el-button
        :loading="busy"
        @click="load"
      >
        刷新
      </el-button>
    </div>

    <el-alert
      title="审核员默认看不到联系方式、AI 对话、辅导记录与支付资料。查看原始照片需要独立权限并记录敏感访问。"
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

    <el-tabs
      :model-value="section"
      @update:model-value="switchSection(String($event))"
    >
      <el-tab-pane
        v-for="item in visibleSections"
        :key="item[0]"
        :name="item[0]"
        :label="item[1]"
      />
    </el-tabs>

    <div class="operation-inputs">
      <el-select
        v-model="reasonCode"
        aria-label="原因代码"
        class="reason-code"
      >
        <el-option
          v-for="code in PHOTO_REASON_CODES"
          :key="code"
          :label="localizeAdminValue(code, 'reason_code')"
          :value="code"
        />
      </el-select>
      <el-input
        v-model="userMessage"
        aria-label="用户可见说明"
        placeholder="用户可见说明"
      />
      <el-input
        v-model="internalNote"
        aria-label="内部备注"
        placeholder="内部备注（加密保存，用户不可见）"
      />
    </div>

    <el-button
      v-if="section === 'projections' && auth.hasPermission('matchmaking.projections.rebuild')"
      @click="processJobs"
    >
      处理投影任务队列
    </el-button>

    <el-table
      :data="rows"
      class="admin-table"
    >
      <el-table-column
        v-for="key in Object.keys(rows[0] ?? {})"
        :key="key"
        :prop="key"
        :label="localizeAdminLabel(key)"
        show-overflow-tooltip
      >
        <template #default="{ row }">
          {{ localizeAdminValue(row[key], key) }}
        </template>
      </el-table-column>
      <el-table-column
        label="操作"
        width="260"
      >
        <template #default="scope">
          <el-button
            v-if="section === 'reviews'"
            size="small"
            @click="openCase(scope.row)"
          >
            打开审核
          </el-button>
          <el-button
            v-if="section === 'photo-reviews' && canReviewPhotos"
            size="small"
            @click="photoDecision(scope.row, 'approve')"
          >
            批准照片
          </el-button>
          <el-button
            v-if="section === 'photo-reviews' && canReviewPhotos"
            size="small"
            type="danger"
            @click="photoDecision(scope.row, 'reject')"
          >
            拒绝照片
          </el-button>
          <el-button
            v-if="section === 'profiles' && canSuspend"
            size="small"
            type="danger"
            @click="suspendProfile(scope.row)"
          >
            暂停
          </el-button>
          <el-button
            v-if="section === 'profiles' && canSuspend"
            size="small"
            @click="restoreProfile(scope.row)"
          >
            恢复
          </el-button>
          <el-button
            v-if="section === 'projections' && auth.hasPermission('matchmaking.projections.rebuild')"
            size="small"
            @click="rebuildProjection(scope.row)"
          >
            重建投影
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-card
      v-if="activeCase"
      class="review-workbench"
    >
      <h3>审核案件 {{ activeCase.id }}</h3>
      <p>
        状态 {{ localizeAdminValue(activeCase.status, "status") }} · 乐观锁版本 {{ activeCase.version }} ·
        敏感字段权限：{{ activeCase.sensitive_access_granted ? "已授予" : "未授予" }}
      </p>

      <div
        v-if="diff"
        class="diff-panel"
      >
        <h4>版本差异 v{{ diff.left_version }} → v{{ diff.right_version }}</h4>
        <p>新增：{{ diff.added_fields.join("、") || "无" }}</p>
        <p>修改：{{ diff.changed_fields.join("、") || "无" }}</p>
        <p>删除：{{ diff.removed_fields.join("、") || "无" }}</p>
        <p>
          照片变化 {{ diff.photo_changed ? "是" : "否" }} ·
          隐私变化 {{ diff.privacy_changed ? "是" : "否" }} ·
          择偶条件变化 {{ diff.preference_criteria_changed ? "是" : "否" }}
        </p>
        <el-alert
          v-if="diff.requires_full_review"
          title="修改范围较大，建议执行全量复核。"
          type="warning"
          :closable="false"
        />
        <div class="field-actions">
          <div
            v-for="field in diff.changed_fields"
            :key="field"
            class="field-row"
          >
            <span>{{ field }}</span>
            <el-button
              v-if="canDecide"
              size="small"
              @click="fieldDecision(field, 'approve')"
            >
              通过
            </el-button>
            <el-button
              v-if="canDecide"
              size="small"
              type="warning"
              @click="fieldDecision(field, 'changes_required')"
            >
              要求修改
            </el-button>
          </div>
        </div>
      </div>

      <ul class="review-items">
        <li
          v-for="item in activeCase.items ?? []"
          :key="String(item.id)"
        >
          {{ item.item_type }} · {{ item.field_code ?? item.photo_id }} · {{ item.decision }}
          <span v-if="item.reason_code">（{{ item.reason_code }}）</span>
        </li>
      </ul>

      <div class="case-actions">
        <el-button
          v-if="canDecide"
          @click="caseAction('start')"
        >
          开始审核
        </el-button>
        <el-button
          v-if="canDecide"
          type="success"
          @click="caseAction('approve')"
        >
          批准
        </el-button>
        <el-button
          v-if="canDecide"
          type="warning"
          @click="caseAction('request-changes')"
        >
          要求修改
        </el-button>
        <el-button
          v-if="canDecide"
          type="danger"
          @click="caseAction('reject')"
        >
          拒绝
        </el-button>
        <el-button
          v-if="auth.hasPermission('matchmaking.reviews.escalate')"
          @click="caseAction('escalate')"
        >
          升级处理
        </el-button>
      </div>
      <p class="admin-hint">
        审核员不能代替用户修改档案内容；拒绝与暂停必须填写原因；所有决定都会写入审计。
      </p>
    </el-card>
  </section>
</template>

<style scoped>
.matchmaking-admin-page { display: flex; flex-direction: column; gap: 1rem; }
.operation-inputs { display: grid; grid-template-columns: 12rem 1fr 1fr; gap: 0.5rem; }
.review-workbench { display: flex; flex-direction: column; gap: 0.75rem; }
.diff-panel { padding: 0.75rem; border: 1px solid var(--el-border-color); border-radius: 0.5rem; }
.field-actions { display: flex; flex-direction: column; gap: 0.35rem; margin-top: 0.5rem; }
.field-row { display: flex; align-items: center; gap: 0.5rem; }
.review-items { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.25rem; }
.case-actions { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.admin-hint { font-size: 0.85rem; opacity: 0.75; }
</style>
