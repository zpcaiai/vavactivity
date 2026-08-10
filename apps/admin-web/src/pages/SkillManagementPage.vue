<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { skillsAdminApi, type SkillRow } from "@/features/skills/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();
const section = computed(() => String(route.meta.skillSection ?? "dashboard"));
const rows = ref<SkillRow[]>([]);
const busy = ref(false);
const error = ref("");
const notice = ref("");

const sections = [
  ["dashboard", "概览", "skills.analytics.read"],
  ["catalog", "Skill 目录", "skills.registry.read"],
  ["installations", "安装", "skills.installations.read"],
  ["executions", "执行", "skills.executions.read"],
  ["dependencies", "依赖", "skills.registry.read"],
  ["permissions", "权限", "skills.permissions.read"],
  ["configurations", "配置", "skills.installations.read"],
  ["publishers", "发布者", "skills.publishers.read"],
  ["reviews", "审核", "skills.marketplace.review"],
  ["marketplace", "Marketplace", "skills.marketplace.read"],
  ["incidents", "安全事件", "skills.incidents.read"],
  ["audit", "审计", "skills.audit.read"]
] as const;
const visibleSections = computed(() => sections.filter((item) => auth.hasPermission(item[2])));
const columns = computed(() => {
  const keys = new Set<string>();
  for (const row of rows.value.slice(0, 30)) {
    Object.keys(row).forEach((key) => {
      if (!/(encrypted|secret|credential|input|output|configuration)/iu.test(key)) keys.add(key);
    });
  }
  return [...keys].slice(0, 9);
});
const metrics = computed(() => ({
  registered: rows.value.filter((row) => row.skill_name).length,
  active: rows.value.filter((row) => row.status === "active").length,
  quarantined: rows.value.filter((row) => row.status === "quarantined").length,
  failed: rows.value.filter((row) => row.status === "failed").length
}));

function display(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    await auth.bootstrap();
    if (section.value === "catalog" || section.value === "dependencies" || section.value === "permissions") {
      rows.value = await skillsAdminApi.catalog();
    } else if (section.value === "executions" || section.value === "incidents" || section.value === "audit") {
      rows.value = await skillsAdminApi.executions();
    } else if (section.value === "marketplace" || section.value === "reviews" || section.value === "publishers") {
      rows.value = await skillsAdminApi.marketplace();
    } else if (section.value === "dashboard") {
      const [catalog, installations, executions, marketplace] = await Promise.all([
        skillsAdminApi.catalog(),
        skillsAdminApi.installations(),
        skillsAdminApi.executions(),
        skillsAdminApi.marketplace()
      ]);
      rows.value = [...catalog, ...installations, ...executions, ...marketplace];
    } else {
      rows.value = await skillsAdminApi.installations();
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "Skill 控制面加载失败";
  } finally {
    busy.value = false;
  }
}

async function installationAction(row: SkillRow, action: "approve" | "activate" | "disable") {
  if (!row.id || !window.confirm(`${action} 会改变 Skill 运行状态，确认继续？`)) return;
  if (action === "approve") await skillsAdminApi.approveInstallation(row.id);
  if (action === "activate") await skillsAdminApi.activateInstallation(row.id);
  if (action === "disable") await skillsAdminApi.disableInstallation(row.id);
  notice.value = "状态已更新；签名、安全、兼容和职责分离门禁仍由服务端强制执行。";
  await load();
}

async function listingAction(row: SkillRow, action: "approve" | "changes" | "publish") {
  if (!row.id || !window.confirm("Marketplace 操作会影响公开可见性，确认继续？")) return;
  if (action === "publish") await skillsAdminApi.publishListing(row.id);
  else await skillsAdminApi.reviewListing(row.id, action === "approve" ? "approved" : "changes_required");
  notice.value = "Marketplace 审核状态已更新并记录审计。";
  await load();
}

watch(() => route.fullPath, load);
onMounted(load);
</script>

<template>
  <section class="skills-console">
    <header>
      <div>
        <p class="eyebrow">
          BATCH 20 · GOVERNED SKILL PLATFORM
        </p><h1>Skill 控制台</h1>
      </div>
      <p>第三方代码不进入 API 主进程；高风险权限、签名、SBOM、兼容性和 Marketplace 人工审核均为服务端 fail-closed 门禁。</p>
    </header>
    <nav>
      <RouterLink
        v-for="item in visibleSections"
        :key="item[0]"
        :to="`/admin/skills/${item[0]}`"
      >
        {{ item[1] }}
      </RouterLink>
    </nav>
    <p
      v-if="busy"
      role="status"
    >
      正在读取 Skill 控制面…
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
      v-if="section === 'dashboard'"
      class="metrics"
    >
      <div
        v-for="(value, key) in metrics"
        :key="key"
      >
        <strong>{{ key }}</strong><span>{{ value }}</span>
      </div>
    </article>
    <article class="panel">
      <p
        v-if="section === 'permissions'"
        class="warning"
      >
        高风险权限不会隐藏：任何新增权限都要求重新生成安装计划并重新审批。
      </p>
      <table v-if="rows.length">
        <thead>
          <tr>
            <th
              v-for="column in columns"
              :key="column"
            >
              {{ column }}
            </th><th>受控操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="String(row.id ?? row.skill_name ?? JSON.stringify(row))"
          >
            <td
              v-for="column in columns"
              :key="column"
            >
              {{ display(row[column]) }}
            </td>
            <td class="actions">
              <template v-if="section === 'installations'">
                <button
                  v-if="row.status === 'approval_required'"
                  :disabled="!auth.hasPermission('skills.installations.approve')"
                  @click="installationAction(row, 'approve')"
                >
                  独立审批
                </button>
                <button
                  v-if="row.status === 'validating'"
                  :disabled="!auth.hasPermission('skills.installations.activate')"
                  @click="installationAction(row, 'activate')"
                >
                  激活
                </button>
                <button
                  v-if="row.status === 'active'"
                  :disabled="!auth.hasPermission('skills.installations.disable')"
                  @click="installationAction(row, 'disable')"
                >
                  停用
                </button>
              </template>
              <template v-else-if="section === 'reviews' || section === 'marketplace'">
                <button
                  v-if="row.listing_status === 'human_review'"
                  :disabled="!auth.hasPermission('skills.marketplace.review')"
                  @click="listingAction(row, 'approve')"
                >
                  批准
                </button>
                <button
                  v-if="row.listing_status === 'human_review'"
                  :disabled="!auth.hasPermission('skills.marketplace.review')"
                  @click="listingAction(row, 'changes')"
                >
                  要求修改
                </button>
                <button
                  v-if="row.listing_status === 'approved'"
                  :disabled="!auth.hasPermission('skills.marketplace.approve')"
                  @click="listingAction(row, 'publish')"
                >
                  发布
                </button>
              </template>
              <span v-else>只读</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="!busy">
        暂无记录。
      </p>
    </article>
  </section>
</template>

<style scoped>
.skills-console{display:grid;gap:1rem}header{display:flex;justify-content:space-between;gap:2rem;align-items:end}header>p{max-width:680px}.eyebrow{letter-spacing:.12em;color:#24535b}nav{display:flex;gap:.5rem;flex-wrap:wrap}nav a{padding:.5rem .8rem;border-radius:999px;background:#eaf1f1;color:#263d40;text-decoration:none}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem}.metrics div,.panel{padding:1rem;border:1px solid #d8e1e1;border-radius:12px;background:#fff}.metrics div{display:grid;gap:.35rem}.metrics span{font-size:1.7rem}.panel{overflow:auto}.warning{padding:.8rem;background:#fff3cd;border-left:4px solid #b7791f}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.65rem;border-bottom:1px solid #edf0f0;max-width:250px;overflow-wrap:anywhere}.actions{display:flex;gap:.4rem;flex-wrap:wrap}button{padding:.5rem .75rem;border:0;border-radius:999px;background:#24535b;color:#fff}button:disabled{opacity:.45}.alert{padding:.8rem}.error{background:#fde8e7}.notice{background:#e8f5ed}@media(max-width:700px){header{align-items:start;flex-direction:column}}
</style>
