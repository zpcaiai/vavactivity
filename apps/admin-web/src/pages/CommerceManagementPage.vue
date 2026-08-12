<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { localizeAdminLabel, localizeAdminValue } from "@vav/ui-admin";

import PaginationBar from "@/components/PaginationBar.vue";
import { catalogApi } from "@/features/catalog/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

type CommerceRow = Record<string, unknown> & { id: string; status?: string };
type Pagination = { page: number; page_size: number; total: number; pages: number };

type RowAction = {
  key: string;
  label: string;
  type?: "primary" | "success" | "warning" | "danger";
  permission: string;
  /** Confirmation copy shown above the mandatory reason field. */
  intent: string;
  available: (row: CommerceRow) => boolean;
  path: (row: CommerceRow) => string;
};

const route = useRoute();
const auth = useAdminAuthStore();
const section = computed(() => String(route.meta.commerceSection ?? "orders"));
const rows = ref<CommerceRow[]>([]);
const page = ref(1);
const pageSize = ref(50);
const total = ref(0);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const notice = ref("");

const reasonDialog = ref<{ open: boolean; action?: RowAction; row?: CommerceRow; reason: string }>({
  open: false,
  reason: ""
});
const refundDialog = ref({
  open: false,
  order_id: "",
  order_number: "",
  amount_minor: 0,
  maximum_minor: 0,
  currency: "",
  reason_code: "customer_request",
  reason: ""
});

const labels: Record<string, string> = {
  orders: "订单",
  payments: "支付尝试",
  subscriptions: "订阅",
  refunds: "退款",
  webhooks: "Webhook",
  reconciliation: "对账差异",
  entitlements: "权益"
};

const REFUND_REASON_CODES = [
  { value: "customer_request", label: "客户申请" },
  { value: "duplicate_charge", label: "重复扣款" },
  { value: "service_not_delivered", label: "服务未交付" },
  { value: "operational_error", label: "运营操作失误" },
  { value: "goodwill", label: "善意补偿" }
];

const rowActions: Record<string, RowAction[]> = {
  orders: [],
  refunds: [
    {
      key: "approve",
      label: "批准",
      permission: "commerce.refunds.approve",
      intent: "批准该退款申请，进入待提交状态。",
      available: (row) => row.status === "approval_required",
      path: (row) => `/admin/commerce/refunds/${row.id}/approve`
    },
    {
      key: "submit",
      label: "提交 Provider",
      type: "primary",
      permission: "commerce.refunds.submit",
      intent: "向支付渠道提交退款，资金将真实退回，操作不可撤销。",
      available: (row) => row.status === "approved",
      path: (row) => `/admin/commerce/refunds/${row.id}/submit`
    }
  ],
  webhooks: [
    {
      key: "replay",
      label: "重放",
      permission: "commerce.webhooks.replay",
      intent: "重放该 Webhook 事件；处理是幂等的，不会重复入账。",
      available: (row) => row.processing_status !== "processed",
      path: (row) => `/admin/commerce/webhooks/${row.id}/replay`
    }
  ],
  reconciliation: [
    {
      key: "resolve",
      label: "标记已解决",
      permission: "commerce.reconciliation.resolve",
      intent: "标记该对账差异已处理完毕，请写明差异原因与处理动作。",
      available: (row) => row.status === "open",
      path: (row) => `/admin/commerce/reconciliation/${row.id}/resolve`
    }
  ],
  entitlements: [
    {
      key: "revoke",
      label: "撤销",
      type: "danger",
      permission: "commerce.entitlements.revoke",
      intent: "撤销该权益，用户将立即失去对应访问能力。",
      available: (row) => row.status === "active",
      path: (row) => `/admin/commerce/entitlements/${row.id}/revoke`
    }
  ]
};

const canRequestRefund = computed(() => auth.hasPermission("commerce.refunds.request"));
const canScan = computed(() => auth.hasPermission("commerce.payments.reconcile"));

const availableActions = computed(() =>
  (rowActions[section.value] ?? []).filter((action) => auth.hasPermission(action.permission))
);
const showActionColumn = computed(
  () => availableActions.value.length > 0 || (section.value === "orders" && canRequestRefund.value)
);

const columns = computed(() => {
  const keys = new Set<string>();
  for (const row of rows.value) {
    for (const key of Object.keys(row)) {
      if (!["payload", "expected", "actual", "client_action", "id"].includes(key)) keys.add(key);
    }
  }
  return [...keys].slice(0, 8);
});

function displayValue(row: CommerceRow, key: string) {
  const value = row[key];
  if (key.endsWith("_minor") && typeof value === "number") {
    const currency = typeof row.currency === "string" ? row.currency.toUpperCase() : "";
    return `${(value / 100).toFixed(2)}${currency ? ` ${currency}` : ""}`;
  }
  return localizeAdminValue(value, key);
}

function outstandingMinor(row: CommerceRow) {
  const totalMinor = typeof row.total_minor === "number" ? row.total_minor : 0;
  const refunded = typeof row.refunded_total_minor === "number" ? row.refunded_total_minor : 0;
  return Math.max(totalMinor - refunded, 0);
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const params = new URLSearchParams({
      page: String(page.value),
      page_size: String(pageSize.value)
    });
    const result = await catalogApi<{ items: CommerceRow[]; pagination?: Pagination }>(
      `/admin/commerce/${section.value}?${params.toString()}`
    );
    rows.value = result.items;
    total.value = result.pagination?.total ?? result.items.length;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

function openAction(action: RowAction, row: CommerceRow) {
  notice.value = "";
  error.value = "";
  reasonDialog.value = { open: true, action, row, reason: "" };
}

async function confirmAction() {
  const { action, row, reason } = reasonDialog.value;
  if (!action || !row) return;
  if (reason.trim().length < 10) {
    error.value = "请填写至少 10 个字符的操作原因，原因会写入交易审计记录。";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await catalogApi(action.path(row), {
      method: "POST",
      body: JSON.stringify({ reason: reason.trim() })
    });
    notice.value = `${action.label}已完成。`;
    reasonDialog.value = { open: false, reason: "" };
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : `${action.label}失败`;
  } finally {
    saving.value = false;
  }
}

function openRefund(row?: CommerceRow) {
  notice.value = "";
  error.value = "";
  const maximum = row ? outstandingMinor(row) : 0;
  refundDialog.value = {
    open: true,
    order_id: row ? String(row.id) : "",
    order_number: row && typeof row.order_number === "string" ? row.order_number : "",
    amount_minor: maximum,
    maximum_minor: maximum,
    currency: row && typeof row.currency === "string" ? row.currency.toUpperCase() : "",
    reason_code: "customer_request",
    reason: ""
  };
}

async function submitRefund() {
  const form = refundDialog.value;
  if (!form.order_id.trim()) {
    error.value = "请填写要退款的订单编号。";
    return;
  }
  if (!Number.isInteger(form.amount_minor) || form.amount_minor <= 0) {
    error.value = "退款金额必须是大于 0 的最小货币单位整数（例如 1 元填 100）。";
    return;
  }
  if (form.maximum_minor && form.amount_minor > form.maximum_minor) {
    error.value = "退款金额不能超过该订单尚未退款的余额。";
    return;
  }
  if (form.reason.trim().length < 10) {
    error.value = "请填写至少 10 个字符的退款原因，原因会写入交易审计记录。";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await catalogApi("/admin/commerce/refunds", {
      method: "POST",
      // The backend requires an idempotency key so a double click can never
      // create two refunds against the same order.
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        order_id: form.order_id.trim(),
        amount_minor: form.amount_minor,
        reason_code: form.reason_code,
        reason: form.reason.trim()
      })
    });
    notice.value = "退款申请已创建，等待审批后才会提交支付渠道。";
    refundDialog.value.open = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "发起退款失败";
  } finally {
    saving.value = false;
  }
}

async function scan() {
  saving.value = true;
  error.value = "";
  try {
    await catalogApi("/admin/commerce/reconciliation/scan", { method: "POST" });
    notice.value = "对账扫描已执行。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "对账扫描失败";
  } finally {
    saving.value = false;
  }
}

onMounted(() => void load());
watch(section, () => {
  page.value = 1;
  rows.value = [];
  notice.value = "";
  void load();
});
watch([page, pageSize], () => void load());
</script>

<template>
  <section
    v-loading="loading"
    class="admin-module commerce-admin"
  >
    <header class="module-heading">
      <div>
        <p class="admin-kicker">
          交易运营控制台
        </p>
        <h2>{{ labels[section] }}</h2>
        <p>金额均为最小货币单位；支付成功只来自已验签 Webhook，退款必须先申请再审批后提交渠道。</p>
      </div>
      <div class="heading-actions">
        <el-button
          v-if="section === 'reconciliation' && canScan"
          type="primary"
          :loading="saving"
          @click="scan"
        >
          执行对账扫描
        </el-button>
        <el-button
          v-if="section === 'refunds' && canRequestRefund"
          type="primary"
          @click="openRefund()"
        >
          发起退款
        </el-button>
        <el-button
          :loading="loading"
          @click="load"
        >
          刷新
        </el-button>
      </div>
    </header>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
    />
    <el-alert
      v-if="notice"
      :title="notice"
      type="success"
      :closable="false"
      show-icon
    />

    <el-table
      :data="rows"
      stripe
    >
      <el-table-column
        v-for="column in columns"
        :key="column"
        :prop="column"
        :label="localizeAdminLabel(column)"
        min-width="150"
      >
        <template #default="{ row }">
          {{ displayValue(row, column) }}
        </template>
      </el-table-column>
      <el-table-column
        v-if="showActionColumn"
        label="操作"
        fixed="right"
        width="220"
      >
        <template #default="{ row }">
          <el-button
            v-if="section === 'orders' && canRequestRefund && outstandingMinor(row) > 0"
            size="small"
            @click="openRefund(row)"
          >
            发起退款
          </el-button>
          <el-button
            v-for="action in availableActions"
            v-show="action.available(row)"
            :key="action.key"
            size="small"
            :type="action.type"
            @click="openAction(action, row)"
          >
            {{ action.label }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty
      v-if="!loading && !rows.length"
      description="暂无记录"
    />
    <PaginationBar
      v-if="total > pageSize || page > 1"
      v-model:page="page"
      v-model:page-size="pageSize"
      :total="total"
    />

    <el-dialog
      v-model="reasonDialog.open"
      :title="reasonDialog.action?.label"
      width="520px"
    >
      <p class="dialog-intent">
        {{ reasonDialog.action?.intent }}
      </p>
      <el-form label-position="top">
        <el-form-item label="操作原因（至少 10 个字符）">
          <el-input
            v-model="reasonDialog.reason"
            type="textarea"
            :rows="3"
            placeholder="写明为什么执行该操作，以及依据的工单或沟通记录。"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reasonDialog.open = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="saving"
          @click="confirmAction"
        >
          确认执行
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="refundDialog.open"
      title="发起退款"
      width="560px"
    >
      <el-form label-position="top">
        <el-form-item label="订单编号（UUID）">
          <el-input
            v-model="refundDialog.order_id"
            :disabled="Boolean(refundDialog.order_number)"
            placeholder="从订单列表点「发起退款」可自动带入"
          />
        </el-form-item>
        <el-form-item
          v-if="refundDialog.order_number"
          label="订单号"
        >
          <el-input
            :model-value="refundDialog.order_number"
            disabled
          />
        </el-form-item>
        <el-form-item
          :label="refundDialog.maximum_minor
            ? `退款金额（最小货币单位，可退上限 ${refundDialog.maximum_minor}）`
            : '退款金额（最小货币单位，例如 1 元填 100）'"
        >
          <el-input-number
            v-model="refundDialog.amount_minor"
            :min="1"
            :max="refundDialog.maximum_minor || undefined"
            :step="100"
            :precision="0"
          />
          <span
            v-if="refundDialog.currency"
            class="currency-hint"
          >{{ refundDialog.currency }}</span>
        </el-form-item>
        <el-form-item label="退款原因分类">
          <el-select v-model="refundDialog.reason_code">
            <el-option
              v-for="option in REFUND_REASON_CODES"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="退款说明（至少 10 个字符）">
          <el-input
            v-model="refundDialog.reason"
            type="textarea"
            :rows="3"
            placeholder="写明客户诉求、核实结论与责任归属。"
          />
        </el-form-item>
      </el-form>
      <p class="dialog-intent">
        创建后进入待审批状态，需另一位具备审批权限的运营批准并提交渠道，资金才会真正退回。
      </p>
      <template #footer>
        <el-button @click="refundDialog.open = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="saving"
          @click="submitRefund"
        >
          创建退款申请
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.module-heading,.heading-actions{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.module-heading{justify-content:space-between;margin-bottom:16px}.dialog-intent{color:var(--el-text-color-secondary);margin:0 0 12px}.currency-hint{margin-left:10px;color:var(--el-text-color-secondary)}
</style>
