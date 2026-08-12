<script setup lang="ts">
import { onMounted, ref } from "vue";
import { formatAdminTableCell } from "@vav/ui-admin";

import { catalogApi } from "@/features/catalog/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

type Conversation = {
  id: string;
  conversation_number: string;
  user_anonymous_id: string;
  status: string;
  primary_topic?: string | null;
  risk_level?: string | null;
  created_at: string;
};
type Referral = {
  id: string;
  referral_number: string;
  priority: string;
  risk_category?: string | null;
  risk_level?: string | null;
  status: string;
  assigned_team?: string | null;
};
type Prompt = {
  release_id: string;
  prompt_code: string;
  purpose: string;
  semantic_version: string;
  locale: string;
  status: string;
  safety_policy_version: string;
  tool_registry_version: string;
  checksum_sha256: string;
};
type Model = {
  id: string;
  profile_code: string;
  provider: string;
  model_name: string;
  model_revision: string;
  task_type: string;
  status: string;
};
type Tool = {
  id: string;
  tool_code: string;
  semantic_version: string;
  risk_level: string;
  confirmation_required: boolean;
  timeout_seconds: number;
  status: string;
};
type EvaluationRun = {
  id: string;
  graph_version: string;
  status: string;
  metrics?: Record<string, unknown> | null;
  serious_failures: string[];
  started_at: string;
};
type Audit = {
  id: string;
  event_type: string;
  subject_type: string;
  subject_id: string;
  reason?: string | null;
  created_at: string;
};

const auth = useAdminAuthStore();
const conversations = ref<Conversation[]>([]);
const referrals = ref<Referral[]>([]);
const prompts = ref<Prompt[]>([]);
const models = ref<Model[]>([]);
const tools = ref<Tool[]>([]);
const runs = ref<EvaluationRun[]>([]);
const audits = ref<Audit[]>([]);
const sensitiveMessages = ref<Array<{ id: string; role: string; content: string }>>([]);
const accessReason = ref("");
const selectedConversationId = ref("");
const error = ref("");
const notice = ref("");
const busy = ref(false);

async function load() {
  busy.value = true;
  error.value = "";
  try {
    const [conversationResult, referralResult, promptResult, modelResult, toolResult, runResult, auditResult] = await Promise.all([
      catalogApi<{ items: Conversation[] }>("/admin/ai/conversations"),
      catalogApi<{ items: Referral[] }>("/admin/ai/referrals"),
      catalogApi<{ items: Prompt[] }>("/admin/ai/prompts"),
      catalogApi<{ profiles: Model[] }>("/admin/ai/models"),
      catalogApi<{ items: Tool[] }>("/admin/ai/tools"),
      catalogApi<{ items: EvaluationRun[] }>("/admin/ai/evaluation-runs"),
      catalogApi<{ items: Audit[] }>("/admin/ai/audit")
    ]);
    conversations.value = conversationResult.items;
    referrals.value = referralResult.items;
    prompts.value = promptResult.items;
    models.value = modelResult.profiles;
    tools.value = toolResult.items;
    runs.value = runResult.items;
    audits.value = auditResult.items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "AI 运营中心加载失败";
  } finally {
    busy.value = false;
  }
}

async function inspectSensitive() {
  if (!selectedConversationId.value || accessReason.value.trim().length < 8) return;
  const result = await catalogApi<{ messages: Array<{ id: string; role: string; content: string }> }>(
    `/admin/ai/conversations/${selectedConversationId.value}/sensitive-view`,
    { method: "POST", body: JSON.stringify({ access_reason: accessReason.value }) }
  );
  sensitiveMessages.value = result.messages;
  notice.value = "敏感会话访问已记录到 AI 审计日志。";
  await load();
}

async function setToolStatus(tool: Tool) {
  await catalogApi(`/admin/ai/tools/${tool.id}`, {
    method: "PATCH",
    body: JSON.stringify({ status: tool.status === "active" ? "disabled" : "active" })
  });
  await load();
}

async function activatePrompt(prompt: Prompt) {
  await catalogApi(`/admin/ai/prompts/${prompt.release_id}/activate`, { method: "POST" });
  await load();
}

/**
 * A referral used to be a one-way street: an operator could acknowledge it and
 * then the ticket had nowhere to go. Assign and resolve close the loop.
 */
const referralDialog = ref<{
  open: boolean;
  referral?: Referral;
  action: "assign" | "resolve";
  assigned_to: string;
  resolution: string;
}>({ open: false, action: "assign", assigned_to: "", resolution: "" });

async function referralAction(referral: Referral, action: "acknowledge") {
  error.value = "";
  try {
    await catalogApi(`/admin/ai/referrals/${referral.id}/actions`, {
      method: "POST",
      body: JSON.stringify({ action })
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "转介操作失败";
  }
}

async function acknowledgeReferral(referral: Referral) {
  await referralAction(referral, "acknowledge");
}

function openReferralDialog(referral: Referral, action: "assign" | "resolve") {
  error.value = "";
  referralDialog.value = { open: true, referral, action, assigned_to: "", resolution: "" };
}

async function submitReferralAction() {
  const form = referralDialog.value;
  if (!form.referral) return;
  if (form.action === "assign" && !form.assigned_to.trim()) {
    error.value = "请填写要指派的责任人用户编号。";
    return;
  }
  if (form.action === "resolve" && form.resolution.trim().length < 10) {
    error.value = "请填写至少 10 个字符的处理结果；结果会加密留存并用于复核。";
    return;
  }
  try {
    await catalogApi(`/admin/ai/referrals/${form.referral.id}/actions`, {
      method: "POST",
      body: JSON.stringify(
        form.action === "assign"
          ? { action: "assign", assigned_to: form.assigned_to.trim() }
          : { action: "resolve", resolution: form.resolution.trim() }
      )
    });
    referralDialog.value = { open: false, action: "assign", assigned_to: "", resolution: "" };
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "转介操作失败";
  }
}

onMounted(() => void load());
</script>

<template>
  <section class="admin-module ai-admin">
    <div class="module-heading">
      <div>
        <p class="admin-kicker">
          受控智能助手运营
        </p>
        <h2>AI 运营与安全中心</h2>
        <p>默认只显示匿名摘要；完整会话需要单独权限、访问原因和追加式审计。</p>
      </div>
      <el-button
        :loading="busy"
        @click="load"
      >
        刷新
      </el-button>
    </div>
    <el-alert
      title="模型与 Prompt 发布不等于生产认证；离线评测、真实提供商和人工安全流程必须分别过门禁。"
      type="warning"
      :closable="false"
      show-icon
    />
    <el-alert
      v-if="notice"
      :title="notice"
      type="success"
      :closable="false"
    />
    <p
      v-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>

    <el-tabs>
      <el-tab-pane label="会话摘要">
        <el-table :data="conversations">
          <el-table-column
            prop="conversation_number"
            label="会话号"
          />
          <el-table-column
            prop="user_anonymous_id"
            label="匿名用户"
          />
          <el-table-column
            prop="primary_topic"
            label="主题"
          />
          <el-table-column
            prop="risk_level"
            label="风险"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
        </el-table>
        <template v-if="auth.hasPermission('ai.conversations.sensitive.read')">
          <h3>受审计的敏感查看</h3>
          <el-select
            v-model="selectedConversationId"
            placeholder="选择会话"
          >
            <el-option
              v-for="item in conversations"
              :key="item.id"
              :label="item.conversation_number"
              :value="item.id"
            />
          </el-select>
          <el-input
            v-model="accessReason"
            placeholder="访问原因（至少 8 个字符）"
          />
          <el-button
            :disabled="!selectedConversationId || accessReason.trim().length < 8"
            @click="inspectSensitive"
          >
            查看并审计
          </el-button>
          <article
            v-for="message in sensitiveMessages"
            :key="message.id"
            class="sensitive-message"
          >
            <strong>{{ message.role }}</strong><p>{{ message.content }}</p>
          </article>
        </template>
      </el-tab-pane>

      <el-tab-pane label="安全转介">
        <el-table :data="referrals">
          <el-table-column
            prop="referral_number"
            label="转介号"
          />
          <el-table-column
            prop="priority"
            label="优先级"
          />
          <el-table-column
            prop="risk_category"
            label="风险类别"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
          <el-table-column
            prop="assigned_team"
            label="责任团队"
          />
          <el-table-column
            label="操作"
            min-width="280"
          >
            <template #default="scope">
              <el-button
                v-if="auth.hasPermission('ai.referrals.assign') && scope.row.status === 'open'"
                size="small"
                @click="acknowledgeReferral(scope.row)"
              >
                确认接收
              </el-button>
              <el-button
                v-if="auth.hasPermission('ai.referrals.assign') && scope.row.status !== 'resolved'"
                size="small"
                @click="openReferralDialog(scope.row, 'assign')"
              >
                指派责任人
              </el-button>
              <el-button
                v-if="auth.hasPermission('ai.referrals.resolve') && scope.row.status !== 'resolved'"
                size="small"
                type="primary"
                @click="openReferralDialog(scope.row, 'resolve')"
              >
                结案
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-dialog
          v-model="referralDialog.open"
          :title="referralDialog.action === 'assign' ? '指派转介责任人' : '转介结案'"
          width="520px"
        >
          <el-form label-position="top">
            <el-form-item
              v-if="referralDialog.action === 'assign'"
              label="责任人用户编号"
            >
              <el-input v-model="referralDialog.assigned_to" />
            </el-form-item>
            <el-form-item
              v-else
              label="处理结果（至少 10 个字符）"
            >
              <el-input
                v-model="referralDialog.resolution"
                type="textarea"
                :rows="3"
                placeholder="写明实际采取的干预、联系到的人与后续安排。"
              />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="referralDialog.open = false">
              取消
            </el-button>
            <el-button
              type="primary"
              @click="submitReferralAction"
            >
              提交
            </el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <el-tab-pane label="提示词发布">
        <el-table :data="prompts">
          <el-table-column
            prop="prompt_code"
            label="代码"
          />
          <el-table-column
            prop="semantic_version"
            label="版本"
          />
          <el-table-column
            prop="locale"
            label="语言"
          />
          <el-table-column
            prop="tool_registry_version"
            label="工具版本"
          />
          <el-table-column
            prop="safety_policy_version"
            label="安全政策"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
          <el-table-column label="操作">
            <template #default="scope">
              <el-button
                v-if="auth.hasPermission('ai.prompts.activate')"
                @click="activatePrompt(scope.row)"
              >
                激活
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="模型路由">
        <el-table :data="models">
          <el-table-column
            prop="profile_code"
            label="配置档"
          />
          <el-table-column
            prop="provider"
            label="服务商"
          />
          <el-table-column
            prop="model_name"
            label="模型"
          />
          <el-table-column
            prop="model_revision"
            label="修订"
          />
          <el-table-column
            prop="task_type"
            label="任务"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="受控工具">
        <el-table :data="tools">
          <el-table-column
            prop="tool_code"
            label="工具"
          />
          <el-table-column
            prop="semantic_version"
            label="版本"
          />
          <el-table-column
            prop="risk_level"
            label="风险"
          />
          <el-table-column
            prop="confirmation_required"
            label="需用户确认"
          />
          <el-table-column
            prop="timeout_seconds"
            label="超时（秒）"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
          <el-table-column label="操作">
            <template #default="scope">
              <el-button
                v-if="auth.hasPermission('ai.tools.manage')"
                @click="setToolStatus(scope.row)"
              >
                {{ scope.row.status === 'active' ? '停用' : '启用' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <p>管理端不允许创建任意代码 Tool；这里只能启停代码注册表中的版本。</p>
      </el-tab-pane>

      <el-tab-pane label="评测与审计">
        <el-table :data="runs">
          <el-table-column
            prop="graph_version"
            label="图版本"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
          <el-table-column label="用例">
            <template #default="scope">
              {{ scope.row.metrics?.passed ?? 0 }}/{{ scope.row.metrics?.total ?? 0 }}
            </template>
          </el-table-column>
          <el-table-column label="严重失败">
            <template #default="scope">
              {{ scope.row.serious_failures.length }}
            </template>
          </el-table-column>
          <el-table-column
            prop="started_at"
            :formatter="formatAdminTableCell"
            label="开始时间（UTC+8）"
          />
        </el-table>
        <el-table :data="audits">
          <el-table-column
            prop="event_type"
            label="审计事件"
          />
          <el-table-column
            prop="subject_type"
            label="对象"
          />
          <el-table-column
            prop="reason"
            label="原因"
          />
          <el-table-column
            prop="created_at"
            :formatter="formatAdminTableCell"
            label="时间（UTC+8）"
          />
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>
