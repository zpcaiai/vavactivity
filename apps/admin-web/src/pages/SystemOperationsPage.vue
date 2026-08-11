<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { localizeAdminLabel, localizeAdminValue } from "@vav/ui-admin";

import { systemAdminApi, type SystemAdminRow } from "@/features/system/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();
const section = computed(() => String(route.meta.systemSection ?? "status"));
const rows = ref<SystemAdminRow[]>([]);
const summary = ref<SystemAdminRow | null>(null);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const newFlagCode = ref("");
const sections = [
  ["status", "运行状态", "system.status.read"],
  ["releases", "发布记录", "system.releases.read"],
  ["jobs", "迁移与回填", "system.jobs.read"],
  ["integrations", "集成状态", "system.status.read"],
  ["dead-letters", "死信队列", "system.dead_letters.read"],
  ["feature-flags", "功能开关", "system.feature_flags.read"],
  ["maintenance", "维护模式", "system.maintenance.read"],
  ["backups", "备份", "system.backups.read"],
  ["restore-drills", "恢复演练", "system.restore_drills.read"],
  ["capacity", "容量基线", "system.capacity.read"]
] as const;
const visible = computed(() => sections.filter((item) => auth.hasPermission(item[2])));
const columns = computed(() => {
  const keys = new Set<string>();
  for (const row of rows.value.slice(0, 20)) {
    Object.keys(row).forEach((key) => {
      if (!/(secret|token|password|credential|evidence_manifest)/iu.test(key)) keys.add(key);
    });
  }
  return [...keys].slice(0, 8);
});

function display(value: unknown, field = "") {
  return localizeAdminValue(value, field);
}

async function load() {
  busy.value = true;
  error.value = "";
  rows.value = [];
  summary.value = null;
  try {
    await auth.bootstrap();
    const payload = await systemAdminApi.view(section.value);
    if (Array.isArray(payload)) rows.value = payload;
    else summary.value = payload;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "系统运维视图加载失败";
  } finally {
    busy.value = false;
  }
}

async function createFlag() {
  const code = newFlagCode.value.trim();
  if (!code) return;
  await systemAdminApi.createFlag({
    flag_code: code,
    default_value: { enabled: false },
    targeting_policy: {},
    description: "由系统运维中心创建；启用前需要另一位管理员审批。"
  });
  newFlagCode.value = "";
  notice.value = "草稿已创建；创建人不能自我审批。";
  await load();
}

async function flagAction(row: SystemAdminRow) {
  const id = String(row.id);
  if (row.status === "draft") await systemAdminApi.approveFlag(id);
  else if (row.status === "approved") await systemAdminApi.activateFlag(id);
  notice.value = "状态已更新并追加审计记录。";
  await load();
}

async function maintenance(enabled: boolean) {
  if (!window.confirm(`${enabled ? "启用" : "停用"}维护模式会改变写入可用性，确认继续？`)) return;
  await systemAdminApi.changeMaintenance(enabled, {
    reason_code: "operator_confirmed_change",
    public_message: enabled ? "系统正在维护，请稍后重试。" : null,
    write_scope: enabled ? { all: false } : {}
  });
  notice.value = "维护状态已更新并审计。生产环境仍要求独立审批人。";
  await load();
}

watch(() => route.fullPath, load);
onMounted(load);
</script>

<template>
  <section class="system-operations">
    <header>
      <div>
        <p class="eyebrow">
          第 19 批 · 生产运维
        </p><h1>系统运维中心</h1>
      </div>
      <p>仅展示脱敏运行信息。发布使用不可变镜像摘要；生产维护、功能开关激活和恢复操作都保留独立审批与审计边界。</p>
    </header>
    <nav>
      <RouterLink
        v-for="item in visible"
        :key="item[0]"
        :to="`/admin/system/${item[0]}`"
      >
        {{ item[1] }}
      </RouterLink>
    </nav>
    <p
      v-if="busy"
      role="status"
    >
      正在读取运行控制面…
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

    <article
      v-if="section === 'status' && summary"
      class="panel summary"
    >
      <div
        v-for="(value, key) in summary"
        :key="key"
      >
        <strong>{{ localizeAdminLabel(key) }}</strong><span>{{ display(value, key) }}</span>
      </div>
    </article>
    <article
      v-if="section === 'feature-flags'"
      class="panel controls"
    >
      <h2>创建受控功能开关</h2>
      <input
        v-model="newFlagCode"
        aria-label="功能开关代码"
        placeholder="experience.new_onboarding"
      >
      <button
        :disabled="!auth.hasPermission('system.feature_flags.manage')"
        @click="createFlag"
      >
        创建禁用草稿
      </button>
      <p>启用前需要另一位管理员审批；创建人不能自我审批。</p>
      <p>安全、隐私、支付、授权及加密强制控制不能被功能开关绕过。</p>
    </article>
    <article
      v-if="section === 'maintenance'"
      class="panel controls"
    >
      <h2>维护模式</h2>
      <button
        :disabled="!auth.hasPermission('system.maintenance.enable')"
        @click="maintenance(true)"
      >
        启用维护模式
      </button>
      <button
        :disabled="!auth.hasPermission('system.maintenance.disable')"
        @click="maintenance(false)"
      >
        停用维护模式
      </button>
    </article>
    <article
      v-if="section !== 'status'"
      class="panel table-wrap"
    >
      <table>
        <thead>
          <tr>
            <th
              v-for="column in columns"
              :key="column"
            >
              {{ localizeAdminLabel(column) }}
            </th><th v-if="section === 'feature-flags'">
              受控操作
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="String(row.id ?? JSON.stringify(row))"
          >
            <td
              v-for="column in columns"
              :key="column"
            >
              {{ display(row[column], column) }}
            </td>
            <td v-if="section === 'feature-flags'">
              <button
                v-if="row.status === 'draft'"
                :disabled="!auth.hasPermission('system.feature_flags.approve')"
                @click="flagAction(row)"
              >
                独立审批
              </button>
              <button
                v-else-if="row.status === 'approved'"
                :disabled="!auth.hasPermission('system.feature_flags.manage')"
                @click="flagAction(row)"
              >
                激活
              </button>
              <span v-else>只读</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!rows.length && !busy">
        暂无记录。
      </p>
    </article>
  </section>
</template>

<style scoped>
.system-operations{display:grid;gap:1rem}header{display:flex;justify-content:space-between;gap:2rem;align-items:end}header>p{max-width:680px}.eyebrow{letter-spacing:.12em;color:#24535b}nav{display:flex;gap:.55rem;flex-wrap:wrap}nav a{padding:.5rem .8rem;border-radius:999px;background:#eaf1f1;color:#263d40;text-decoration:none}.panel{padding:1rem;border:1px solid #d8e1e1;border-radius:12px;background:#fff}.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem}.summary div{display:grid;gap:.4rem}.summary span{overflow-wrap:anywhere}.controls{display:flex;gap:.8rem;align-items:center;flex-wrap:wrap}.controls h2,.controls p{flex-basis:100%;margin:.2rem 0}.controls input{min-width:260px;padding:.65rem}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.7rem;border-bottom:1px solid #edf0f0;max-width:260px;overflow-wrap:anywhere}button{padding:.6rem .85rem;border:0;border-radius:999px;background:#24535b;color:white}button:disabled{opacity:.45}.alert{padding:.8rem}.error{background:#fde8e7}.notice{background:#e8f5ed}.table-wrap{overflow:auto}@media(max-width:700px){header{align-items:start;flex-direction:column}}
</style>
