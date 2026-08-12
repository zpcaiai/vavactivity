<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { localizeAdminLabel, localizeAdminValue } from "@vav/ui-admin";

import { usabilitySectionPermissions } from "@/navigation/admin-nav";
import {
  ASSERTED_DIMENSIONS,
  DERIVED_DIMENSIONS,
  DIMENSION_STATUSES,
  ENVIRONMENTS,
  RUN_OUTCOMES,
  STEP_STATUSES,
  certificationStatus,
  deriveDimension,
  parseCsv,
  scenarioDevices,
  scenarioLocales,
  scenarioSteps,
  usabilityApi,
  type UatStepResult,
  type UsabilityRow
} from "@/features/usability/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();
const section = computed(() => String(route.meta.usabilitySection ?? "dashboard"));

const rows = ref<UsabilityRow[]>([]);
const summary = ref<Record<string, unknown> | null>(null);
const scenarios = ref<UsabilityRow[]>([]);
const busy = ref(false);
const error = ref("");
const notice = ref("");

const sectionLabels: Record<string, string> = {
  dashboard: "概览",
  scenarios: "UAT 场景",
  runs: "UAT 执行",
  "synthetic-data": "合成数据",
  demo: "演示环境",
  compatibility: "兼容性",
  localization: "本地化",
  drafts: "草稿恢复",
  notifications: "通知用例",
  imports: "导入作业",
  studies: "可用性研究",
  support: "支持预案",
  certifications: "认证评估",
  release: "发布认证"
};

const visibleSections = computed(() =>
  Object.keys(usabilitySectionPermissions).filter((key) =>
    auth.hasPermission(usabilitySectionPermissions[key])
  )
);

const columns = computed(() => {
  const keys = new Set<string>();
  for (const row of rows.value.slice(0, 30)) {
    Object.keys(row).forEach((key) => {
      if (!/(encrypted|checksum|secret|payload)/iu.test(key)) keys.add(key);
    });
  }
  return [...keys].slice(0, 9);
});

function display(value: unknown, field = "") {
  return localizeAdminValue(value, field);
}

async function ensureScenarios() {
  if (scenarios.value.length) return;
  scenarios.value = await usabilityApi.section("scenarios");
}

function scenarioFor(code: string) {
  return scenarios.value.find((item) => String(item.scenario_code) === code);
}

async function load() {
  busy.value = true;
  error.value = "";
  rows.value = [];
  summary.value = null;
  try {
    await auth.bootstrap();
    if (section.value === "dashboard") summary.value = await usabilityApi.dashboard();
    else rows.value = await usabilityApi.section(section.value);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "可用性控制面加载失败";
  } finally {
    busy.value = false;
  }
}

/* ---------------------------------------------------------------- UAT start */

const uatDialog = ref({
  open: false,
  scenario_code: "",
  environment: "",
  release_version: "",
  locale: "",
  device_profile: ""
});

const uatScenario = computed(() => scenarioFor(uatDialog.value.scenario_code));
const uatLocales = computed(() => scenarioLocales(uatScenario.value));
const uatDevices = computed(() => scenarioDevices(uatScenario.value));

async function openUat(row: UsabilityRow) {
  await ensureScenarios();
  uatDialog.value = {
    open: true,
    scenario_code: String(row.scenario_code ?? ""),
    environment: "",
    release_version: "",
    locale: "",
    device_profile: ""
  };
}

const uatReady = computed(() => {
  const form = uatDialog.value;
  return Boolean(
    form.scenario_code && form.environment && form.release_version.trim() && form.locale && form.device_profile
  );
});

async function submitUat() {
  const form = uatDialog.value;
  if (!uatReady.value) return;
  busy.value = true;
  error.value = "";
  try {
    await usabilityApi.startUat({
      scenario_code: form.scenario_code,
      environment: form.environment,
      release_version: form.release_version.trim(),
      locale: form.locale,
      device_profile: form.device_profile
    });
    uatDialog.value.open = false;
    notice.value = "UAT 执行已创建，状态为 running；结果需在「UAT 执行」中逐步登记。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "UAT 发起失败";
  } finally {
    busy.value = false;
  }
}

/* ------------------------------------------------------------- UAT complete */

const completeDialog = ref({
  open: false,
  run_id: "",
  scenario_code: "",
  status: "",
  evidence: "",
  steps: [] as UatStepResult[],
  definition: [] as Record<string, unknown>[]
});

async function openComplete(row: UsabilityRow) {
  await ensureScenarios();
  const scenario = scenarioFor(String(row.scenario_code ?? ""));
  const definition = scenarioSteps(scenario);
  completeDialog.value = {
    open: true,
    run_id: String(row.id ?? ""),
    scenario_code: String(row.scenario_code ?? ""),
    status: "",
    evidence: "",
    definition,
    // The backend rejects a result list whose length differs from the scenario
    // definition, so the form is seeded with exactly one entry per step.
    steps: definition.map(() => ({ status: "not_run", observation: "", error_code: "", duration_ms: null }))
  };
}

function stepLabel(step: Record<string, unknown>, index: number) {
  const text = step.text ?? step.action ?? step.description ?? step.title;
  return `${index + 1}. ${text ? String(text) : "步骤"}`;
}

const completeReady = computed(() => Boolean(completeDialog.value.status));

async function submitComplete() {
  const form = completeDialog.value;
  if (!completeReady.value) return;
  busy.value = true;
  error.value = "";
  try {
    await usabilityApi.completeUat(form.run_id, {
      status: form.status,
      step_results: form.steps.map((step) => ({
        status: step.status,
        observation: String(step.observation ?? "").slice(0, 2000),
        error_code: String(step.error_code ?? "").trim() || null,
        duration_ms: step.duration_ms === null || step.duration_ms === undefined || String(step.duration_ms) === "" ? null : Number(step.duration_ms)
      })),
      evidence_refs: form.evidence
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean)
    });
    completeDialog.value.open = false;
    notice.value = "执行结果已登记，逐步结果已写入审计表。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "结果登记失败";
  } finally {
    busy.value = false;
  }
}

/* ---------------------------------------------------------------- 导入预览 */

const importForm = ref({
  import_code: "",
  file_name: "",
  idempotency_key: "",
  rows: [] as Record<string, unknown>[],
  parse_error: ""
});
const importResult = ref<UsabilityRow | null>(null);

async function onImportFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  importResult.value = null;
  if (!file) {
    importForm.value = { ...importForm.value, file_name: "", rows: [], idempotency_key: "", parse_error: "" };
    return;
  }
  try {
    const parsed = parseCsv(await file.text());
    importForm.value = {
      ...importForm.value,
      file_name: file.name,
      rows: parsed,
      // One key per chosen file: re-previewing the same file returns the same
      // job instead of creating a duplicate, which is what the backend's
      // idempotency check is for.
      idempotency_key: crypto.randomUUID(),
      parse_error: parsed.length ? "" : "未解析出数据行：请确认首行是表头且至少有一行数据。"
    };
  } catch (cause) {
    importForm.value = { ...importForm.value, file_name: file.name, rows: [], idempotency_key: "", parse_error: cause instanceof Error ? cause.message : "文件读取失败" };
  }
}

const importReady = computed(
  () => Boolean(importForm.value.import_code.trim()) && importForm.value.rows.length > 0
);

async function submitImport() {
  if (!importReady.value) return;
  busy.value = true;
  error.value = "";
  try {
    importResult.value = await usabilityApi.previewImport({
      import_code: importForm.value.import_code.trim(),
      source_file_ref: importForm.value.file_name,
      rows: importForm.value.rows,
      idempotency_key: importForm.value.idempotency_key,
      dry_run: true
    });
    notice.value = "预览完成。这一步只做校验，不写入业务数据。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "导入预览失败";
  } finally {
    busy.value = false;
  }
}

/* ------------------------------------------------------------ 认证评估 */

const certForm = ref({
  business_domain: "",
  release_version: "",
  environment: "",
  findings: "",
  evidence: "",
  asserted: { draft: "not_run", notification: "not_run", import_export: "not_run" } as Record<string, string>
});
const derived = ref<Record<string, { status: string; matched: number; failed: number; blocked: number; pending: number }> | null>(null);

const certIdentified = computed(() => {
  const form = certForm.value;
  return Boolean(form.business_domain.trim() && form.release_version.trim() && form.environment);
});

async function loadEvidence() {
  if (!certIdentified.value) return;
  busy.value = true;
  error.value = "";
  derived.value = null;
  try {
    await ensureScenarios();
    const domain = certForm.value.business_domain.trim();
    const release = certForm.value.release_version.trim();
    const environment = certForm.value.environment;
    const [runs, compatibility, localization] = await Promise.all([
      usabilityApi.section("runs"),
      usabilityApi.section("compatibility"),
      usabilityApi.section("localization")
    ]);
    const domainScenarios = new Set(
      scenarios.value
        .filter((item) => String(item.business_domain ?? "") === domain)
        .map((item) => String(item.scenario_code))
    );
    const domainRuns = domainScenarios.size
      ? runs.filter((item) => domainScenarios.has(String(item.scenario_code ?? "")))
      : [];
    derived.value = {
      uat: deriveDimension(domainRuns, release, environment),
      compatibility: deriveDimension(compatibility, release, environment),
      localization: deriveDimension(localization, release, environment)
    };
    if (!domainScenarios.size) {
      notice.value = `业务域「${domain}」下没有任何 UAT 场景，UAT 维度按 not_run 计。`;
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "证据读取失败";
  } finally {
    busy.value = false;
  }
}

const certResults = computed<Record<string, string>>(() => {
  const result: Record<string, string> = {};
  for (const key of DERIVED_DIMENSIONS) result[key] = derived.value?.[key]?.status ?? "not_run";
  for (const key of ASSERTED_DIMENSIONS) result[key] = certForm.value.asserted[key] ?? "not_run";
  return result;
});

const findingsValue = computed(() => {
  const raw = certForm.value.findings.trim();
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
});

const certPreview = computed(() =>
  findingsValue.value === null ? "" : certificationStatus(certResults.value, findingsValue.value)
);

/** Asserting `passed` without a linked run is a claim, so it needs evidence. */
const assertedPassWithoutEvidence = computed(
  () =>
    ASSERTED_DIMENSIONS.some((key) => certForm.value.asserted[key] === "passed") &&
    !certForm.value.evidence.trim()
);

const certReady = computed(
  () =>
    certIdentified.value &&
    derived.value !== null &&
    findingsValue.value !== null &&
    !assertedPassWithoutEvidence.value
);

async function submitCertification() {
  if (!certReady.value || findingsValue.value === null) return;
  busy.value = true;
  error.value = "";
  try {
    await usabilityApi.evaluateCertification({
      business_domain: certForm.value.business_domain.trim(),
      release_version: certForm.value.release_version.trim(),
      environment: certForm.value.environment,
      results: certResults.value,
      unresolved_critical_findings: findingsValue.value,
      evidence_refs: certForm.value.evidence
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean)
    });
    notice.value = "评估已记录。该端点为 upsert，同一业务域/版本/环境的既有评估已被覆盖，签署人字段已重置。";
    derived.value = null;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "认证评估失败";
  } finally {
    busy.value = false;
  }
}

watch(() => route.fullPath, load);
onMounted(load);
</script>

<template>
  <section class="usability">
    <header>
      <div>
        <p class="eyebrow">
          第 27 批 · 功能可用性
        </p><h1>可用性控制台</h1>
      </div>
      <p>UAT 矩阵、兼容性与本地化执行、草稿恢复、导入校验与发布认证。认证维度中可由本模块数据证明的部分为只读派生，其余必须显式声明。</p>
    </header>

    <nav>
      <RouterLink
        v-for="key in visibleSections"
        :key="key"
        :to="`/admin/usability/${key}`"
      >
        {{ sectionLabels[key] ?? key }}
      </RouterLink>
    </nav>

    <p
      v-if="busy"
      role="status"
    >
      正在读取可用性控制面…
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
      v-if="section === 'dashboard' && summary"
      class="panel metrics"
    >
      <div
        v-for="(value, key) in summary"
        :key="key"
      >
        <strong>{{ localizeAdminLabel(key) }}</strong><span>{{ display(value, key) }}</span>
      </div>
    </article>

    <article
      v-if="section === 'drafts'"
      class="panel note"
    >
      <p>草稿由业务端在编辑过程中自动保存，不是管理端可以代填的对象，因此这里只提供恢复视图。</p>
      <p>后端 <code>discard_draft</code> 已实现但未在 admin 路由暴露，所以暂时无法在这里作废过期草稿。</p>
    </article>

    <article
      v-if="section === 'notifications'"
      class="panel note"
    >
      <p>这里是通知 QA 用例的定义清单。后端没有对应的执行结果表，所以用例只有定义、没有通过与否的记录。</p>
    </article>

    <article
      v-if="section === 'imports'"
      class="panel controls"
    >
      <h2>导入预览（Dry Run）</h2>
      <p class="warning">
        后端只提供预览端点，没有提交端点：这一步做的是逐行校验并生成预览作业，<strong>不会把数据写进业务表</strong>。
      </p>
      <label>
        导入定义代码
        <input
          v-model="importForm.import_code"
          placeholder="例如 members.bulk_invite"
        >
      </label>
      <p class="hint">
        后端没有导入定义的列表端点，代码需要手工填写；填错会返回 USABILITY_IMPORT_NOT_REGISTERED。
      </p>
      <label>
        CSV 文件
        <input
          type="file"
          accept=".csv,text/csv"
          @change="onImportFile"
        >
      </label>
      <p
        v-if="importForm.parse_error"
        class="alert error"
      >
        {{ importForm.parse_error }}
      </p>
      <p v-else-if="importForm.rows.length">
        已解析 {{ importForm.rows.length }} 行，字段：{{ Object.keys(importForm.rows[0]).join("、") }}
      </p>
      <button
        :disabled="!importReady || !auth.hasPermission('usability.imports.preview')"
        @click="submitImport"
      >
        提交预览
      </button>
      <div
        v-if="importResult"
        class="result"
      >
        <span>总行数 {{ display(importResult.total_rows) }}</span>
        <span>有效 {{ display(importResult.valid_rows) }}</span>
        <span>无效 {{ display(importResult.invalid_rows) }}</span>
        <span>状态 {{ display(importResult.status, "status") }}</span>
      </div>
    </article>

    <article
      v-if="section === 'certifications' || section === 'release'"
      class="panel controls"
    >
      <h2>发布认证评估</h2>
      <p class="warning">
        该端点是 upsert：同一「业务域 + 版本 + 环境」的既有评估会被本次结果覆盖，并清空签署人。
      </p>
      <label>
        业务域
        <input v-model="certForm.business_domain">
      </label>
      <label>
        发布版本
        <input v-model="certForm.release_version">
      </label>
      <label>
        环境
        <select v-model="certForm.environment">
          <option value="">
            请选择
          </option>
          <option
            v-for="item in ENVIRONMENTS"
            :key="item"
            :value="item"
          >
            {{ item }}
          </option>
        </select>
      </label>
      <button
        :disabled="!certIdentified"
        @click="loadEvidence"
      >
        读取证据
      </button>

      <template v-if="derived">
        <h3>可派生维度（只读）</h3>
        <table class="dimensions">
          <thead>
            <tr>
              <th>维度</th><th>判定</th><th>匹配执行</th><th>失败</th><th>受阻</th><th>未完成</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="key in DERIVED_DIMENSIONS"
              :key="key"
            >
              <td>{{ key }}</td>
              <td>{{ derived[key].status }}</td>
              <td>{{ derived[key].matched }}</td>
              <td>{{ derived[key].failed }}</td>
              <td>{{ derived[key].blocked }}</td>
              <td>{{ derived[key].pending }}</td>
            </tr>
          </tbody>
        </table>
        <p class="hint">
          这三项来自本模块 uat / compatibility / localization 三张执行表中与上述版本、环境匹配的记录，不可在界面上改写。
        </p>

        <h3>需显式声明的维度</h3>
        <p class="hint">
          草稿、通知用例和导入作业三张表都不带发布版本与环境，无法按版本判定，因此下面三项是你本人的声明而非系统证据；默认 not_run。
        </p>
        <label
          v-for="key in ASSERTED_DIMENSIONS"
          :key="key"
        >
          {{ key }}
          <select v-model="certForm.asserted[key]">
            <option
              v-for="status in DIMENSION_STATUSES"
              :key="status"
              :value="status"
            >
              {{ status }}
            </option>
          </select>
        </label>

        <label>
          未解决的严重问题数
          <input
            v-model="certForm.findings"
            inputmode="numeric"
            placeholder="必填，非负整数"
          >
        </label>
        <label class="wide">
          证据引用（每行一条）
          <textarea
            v-model="certForm.evidence"
            rows="3"
          />
        </label>
        <p
          v-if="assertedPassWithoutEvidence"
          class="alert error"
        >
          有维度被声明为 passed，但没有填写任何证据引用。
        </p>
        <p
          v-if="certPreview"
          class="preview"
        >
          按当前取值，后端将记录为：<strong>{{ certPreview }}</strong>
        </p>
        <button
          :disabled="!certReady"
          @click="submitCertification"
        >
          提交评估
        </button>
      </template>
    </article>

    <article
      v-if="section !== 'dashboard'"
      class="panel table-wrap"
    >
      <table v-if="rows.length">
        <thead>
          <tr>
            <th
              v-for="column in columns"
              :key="column"
            >
              {{ localizeAdminLabel(column) }}
            </th><th v-if="section === 'scenarios' || section === 'runs'">
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
            <td v-if="section === 'scenarios'">
              <button
                :disabled="!auth.hasPermission('uat.runs.execute')"
                @click="openUat(row)"
              >
                发起执行
              </button>
            </td>
            <td v-else-if="section === 'runs'">
              <button
                v-if="row.status === 'running'"
                :disabled="!auth.hasPermission('uat.runs.execute')"
                @click="openComplete(row)"
              >
                登记结果
              </button>
              <span v-else>只读</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="!busy">
        暂无记录。
      </p>
    </article>

    <div
      v-if="uatDialog.open"
      class="dialog"
      role="dialog"
      aria-label="发起 UAT 执行"
    >
      <div class="dialog-body">
        <h2>发起 UAT 执行 · {{ uatDialog.scenario_code }}</h2>
        <p class="hint">
          语言与设备只能从该场景声明的矩阵中选择，超出矩阵后端会以 USABILITY_UAT_MATRIX_MISMATCH 拒绝。
        </p>
        <label>
          环境
          <select v-model="uatDialog.environment">
            <option value="">
              请选择
            </option>
            <option
              v-for="item in ENVIRONMENTS"
              :key="item"
              :value="item"
            >
              {{ item }}
            </option>
          </select>
        </label>
        <label>
          发布版本
          <input v-model="uatDialog.release_version">
        </label>
        <label>
          语言
          <select v-model="uatDialog.locale">
            <option value="">
              请选择
            </option>
            <option
              v-for="item in uatLocales"
              :key="item"
              :value="item"
            >
              {{ item }}
            </option>
          </select>
        </label>
        <label>
          设备档位
          <select v-model="uatDialog.device_profile">
            <option value="">
              请选择
            </option>
            <option
              v-for="item in uatDevices"
              :key="item"
              :value="item"
            >
              {{ item }}
            </option>
          </select>
        </label>
        <p
          v-if="!uatLocales.length || !uatDevices.length"
          class="alert error"
        >
          该场景未声明语言或设备矩阵，无法发起执行。
        </p>
        <footer>
          <button
            class="ghost"
            @click="uatDialog.open = false"
          >
            取消
          </button>
          <button
            :disabled="!uatReady"
            @click="submitUat"
          >
            创建执行
          </button>
        </footer>
      </div>
    </div>

    <div
      v-if="completeDialog.open"
      class="dialog"
      role="dialog"
      aria-label="登记 UAT 结果"
    >
      <div class="dialog-body wide-dialog">
        <h2>登记执行结果 · {{ completeDialog.scenario_code }}</h2>
        <p
          v-if="!completeDialog.definition.length"
          class="alert error"
        >
          未能读取到该场景的步骤定义，将以空步骤列表提交；请确认场景是否仍为 active。
        </p>
        <p
          v-else
          class="hint"
        >
          共 {{ completeDialog.definition.length }} 个步骤，后端要求逐步结果数量与场景定义完全一致。
        </p>
        <div
          v-for="(step, index) in completeDialog.definition"
          :key="index"
          class="step"
        >
          <strong>{{ stepLabel(step, index) }}</strong>
          <div class="step-fields">
            <select v-model="completeDialog.steps[index].status">
              <option
                v-for="status in STEP_STATUSES"
                :key="status"
                :value="status"
              >
                {{ status }}
              </option>
            </select>
            <input
              v-model="completeDialog.steps[index].error_code"
              placeholder="错误码（可空）"
            >
            <input
              v-model="completeDialog.steps[index].duration_ms"
              inputmode="numeric"
              placeholder="耗时 ms（可空）"
            >
          </div>
          <textarea
            v-model="completeDialog.steps[index].observation"
            maxlength="2000"
            rows="2"
            placeholder="观察记录，最多 2000 字，服务端会截断"
          />
        </div>
        <label>
          整体结论
          <select v-model="completeDialog.status">
            <option value="">
              请选择
            </option>
            <option
              v-for="item in RUN_OUTCOMES"
              :key="item"
              :value="item"
            >
              {{ item }}
            </option>
          </select>
        </label>
        <label>
          证据引用（每行一条）
          <textarea
            v-model="completeDialog.evidence"
            rows="2"
          />
        </label>
        <footer>
          <button
            class="ghost"
            @click="completeDialog.open = false"
          >
            取消
          </button>
          <button
            :disabled="!completeReady"
            @click="submitComplete"
          >
            提交结果
          </button>
        </footer>
      </div>
    </div>
  </section>
</template>

<style scoped>
.usability{display:grid;gap:1rem}header{display:flex;justify-content:space-between;gap:2rem;align-items:end}header>p{max-width:680px}.eyebrow{letter-spacing:.12em;color:var(--vav-color-focus)}nav{display:flex;gap:.5rem;flex-wrap:wrap}nav a{padding:.5rem .8rem;border-radius:999px;background:var(--vav-color-surface-info);color:var(--vav-color-text);text-decoration:none}.panel{padding:1rem;border:1px solid var(--vav-color-border);border-radius:12px;background:var(--vav-color-surface-raised)}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1rem}.metrics div{display:grid;gap:.35rem}.metrics span{font-size:1.6rem}.controls{display:flex;gap:.8rem;align-items:end;flex-wrap:wrap}.controls h2,.controls h3,.controls>p,.controls .result,.controls table{flex-basis:100%;margin:.2rem 0}.controls label{display:grid;gap:.3rem;min-width:220px}.controls label.wide{flex-basis:100%}input,select,textarea{padding:.55rem;border:1px solid var(--vav-color-border);border-radius:8px;font:inherit;width:100%}.note p{margin:.3rem 0}.hint{font-size:.85rem;opacity:.75}.warning{padding:.7rem;background:var(--vav-color-surface-warning);border-left:4px solid var(--vav-color-warning)}.preview{padding:.7rem;background:var(--vav-color-surface-info)}.result{display:flex;gap:1rem;flex-wrap:wrap}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.65rem;border-bottom:1px solid var(--vav-color-surface-soft);max-width:250px;overflow-wrap:anywhere}.table-wrap{overflow:auto}button{padding:.55rem .85rem;border:0;border-radius:999px;background:var(--vav-color-focus);color:var(--vav-color-surface-raised)}button:disabled{opacity:.45}button.ghost{background:var(--vav-color-surface-soft);color:var(--vav-color-text)}.alert{padding:.8rem}.error{background:var(--vav-color-surface-danger)}.notice{background:var(--vav-color-surface-success)}.dialog{position:fixed;inset:0;background:rgba(0,0,0,.45);display:grid;place-items:center;padding:1rem;z-index:40}.dialog-body{background:var(--vav-color-surface-raised);border-radius:14px;padding:1.25rem;display:grid;gap:.7rem;max-width:520px;width:100%;max-height:86vh;overflow:auto}.wide-dialog{max-width:760px}.dialog-body footer{display:flex;justify-content:flex-end;gap:.6rem}.step{display:grid;gap:.4rem;padding:.6rem;border:1px solid var(--vav-color-surface-soft);border-radius:10px}.step-fields{display:flex;gap:.5rem;flex-wrap:wrap}.step-fields>*{flex:1 1 140px}@media(max-width:700px){header{align-items:start;flex-direction:column}}
</style>
