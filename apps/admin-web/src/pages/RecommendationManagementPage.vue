<script setup lang="ts">
/**
 * Recommendation operations centre.
 *
 * Operators supervise the engine. There is deliberately no control here to push
 * two specific members together, hand-edit a score, bypass a hard constraint or
 * read a member's private preference list. Diagnostics stay at code and count
 * level, and every state change carries a typed reason into the audit trail.
 */
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { localizeAdminLabel, localizeAdminValue } from "@vav/ui-admin";

import { recommendationApi } from "@/features/recommendations/api";
import type {
  BatchDetail,
  CandidateOverview,
  ColdStartSummary,
  ConstraintPolicy,
  DashboardSummary,
  ExposureReport,
  FeatureDefinition,
  FeedbackSummary,
  PairDiagnostics,
  Row,
  StrategyDetail,
  UserDiagnostics
} from "@/features/recommendations/api";
import { recommendationSections } from "@/features/recommendations/sections";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();

const section = ref(String(route.meta.recommendationSection ?? "dashboard"));
const detailId = ref(String(route.params.id ?? ""));
const busy = ref(false);
const error = ref("");
const notice = ref("");

const rows = ref<Row[]>([]);
const dashboard = ref<DashboardSummary>();
const features = ref<FeatureDefinition[]>([]);
const constraints = ref<ConstraintPolicy>();
const candidates = ref<CandidateOverview>();
const exposures = ref<ExposureReport>();
const coldStart = ref<ColdStartSummary>();
const feedback = ref<FeedbackSummary>();
const diagnostics = ref<UserDiagnostics>();
const pairDiagnostics = ref<PairDiagnostics>();
const strategyDetail = ref<StrategyDetail>();
const batchDetail = ref<BatchDetail>();

const reason = ref("");
const targetUserId = ref("");
const targetPairId = ref("");
const datasetCode = ref("");
const evaluationStrategyId = ref("");

const visibleSections = computed(() =>
  recommendationSections.filter((item) => auth.hasPermission(item[2]))
);
const reasonReady = computed(() => reason.value.trim().length >= 3);
const canApproveStrategy = computed(() => auth.hasPermission("recommendations.strategies.approve"));
const canActivateStrategy = computed(() =>
  auth.hasPermission("recommendations.strategies.activate")
);
const canRollbackStrategy = computed(() =>
  auth.hasPermission("recommendations.strategies.rollback")
);
const canInvalidateBatch = computed(() =>
  auth.hasPermission("recommendations.batches.invalidate")
);
const canRebuildBatch = computed(() => auth.hasPermission("recommendations.batches.rebuild"));
const canRunEvaluation = computed(() => auth.hasPermission("recommendations.evaluations.run"));
const canApproveExperiment = computed(() =>
  auth.hasPermission("recommendations.experiments.approve")
);
const canStartExperiment = computed(() => auth.hasPermission("recommendations.experiments.start"));
const canStopExperiment = computed(() => auth.hasPermission("recommendations.experiments.stop"));

function requireReason() {
  if (reasonReady.value) {
    return true;
  }
  error.value = "请先填写操作原因（至少 3 个字符）。原因会写入推荐审计，无法事后补填。";
  return false;
}

function reset() {
  rows.value = [];
  diagnostics.value = undefined;
  pairDiagnostics.value = undefined;
  strategyDetail.value = undefined;
  batchDetail.value = undefined;
}

async function load() {
  busy.value = true;
  error.value = "";
  reset();
  try {
    await auth.bootstrap();
    if (section.value === "dashboard") {
      dashboard.value = await recommendationApi.dashboard();
    } else if (section.value === "strategies") {
      rows.value = (await recommendationApi.listStrategies()).strategies ?? [];
      if (detailId.value) {
        strategyDetail.value = await recommendationApi.getStrategy(detailId.value);
      }
    } else if (section.value === "features") {
      features.value = (await recommendationApi.listFeatures()).features ?? [];
    } else if (section.value === "constraints") {
      constraints.value = await recommendationApi.constraints();
    } else if (section.value === "batches") {
      rows.value = (await recommendationApi.listBatches()).batches ?? [];
      if (detailId.value) {
        batchDetail.value = await recommendationApi.getBatch(detailId.value);
      }
    } else if (section.value === "candidates") {
      candidates.value = await recommendationApi.candidates();
    } else if (section.value === "exposures") {
      exposures.value = await recommendationApi.exposures();
    } else if (section.value === "cold-start") {
      coldStart.value = await recommendationApi.coldStart();
    } else if (section.value === "feedback") {
      feedback.value = await recommendationApi.feedback();
    } else if (section.value === "evaluations") {
      rows.value = (await recommendationApi.listEvaluations()).runs ?? [];
    } else if (section.value === "experiments") {
      const result = await recommendationApi.listExperiments();
      rows.value = detailId.value
        ? (result.experiments ?? []).filter((item) => String(item.id) === detailId.value)
        : (result.experiments ?? []);
    } else if (section.value === "incidents") {
      rows.value = (await recommendationApi.incidents()).incidents ?? [];
    } else if (section.value === "audit") {
      rows.value = (await recommendationApi.audit()).events ?? [];
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "推荐运营中心加载失败";
  } finally {
    busy.value = false;
  }
}

async function switchSection(value: string) {
  section.value = value;
  detailId.value = "";
  notice.value = "";
  await load();
}

async function run(task: () => Promise<string>) {
  error.value = "";
  try {
    notice.value = await task();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "推荐运营操作失败";
  }
}

async function openStrategy(row: Row) {
  await run(async () => {
    strategyDetail.value = await recommendationApi.getStrategy(String(row.id));
    return `已打开策略 ${String(row.strategy_code ?? row.id)} 的版本与评估记录。`;
  });
}

async function strategyAction(row: Row, action: "approve" | "activate" | "rollback") {
  if (!requireReason()) return;
  await run(async () => {
    const result = await recommendationApi.transitionStrategy(
      String(row.id),
      action,
      reason.value.trim()
    );
    await load();
    if (action === "activate") {
      return `策略状态已变更为 ${result.status}。上线由后端复核：必须有通过的离线评估，且审批人与上线人不能是同一人。`;
    }
    if (action === "rollback") {
      return `策略已回滚（当前状态 ${result.status}），上一版本 ${result.restored_strategy_id ?? "无"} 已恢复生效。`;
    }
    return `策略状态已变更为 ${result.status}。审批只是上线的前置条件之一。`;
  });
}

async function openBatch(row: Row) {
  await run(async () => {
    batchDetail.value = await recommendationApi.getBatch(String(row.id));
    return "已打开批次的排序结果：仅显示候选配对 ID、分数调整项与最终名次。";
  });
}

async function invalidateBatch(row: Row) {
  if (!requireReason()) return;
  await run(async () => {
    await recommendationApi.invalidateBatch(String(row.id), reason.value.trim());
    await load();
    return "批次已作废。作废只会让引擎重新生成，不会改动任何分数。";
  });
}

async function rebuildUser() {
  if (!targetUserId.value.trim()) {
    error.value = "请填写需要重建推荐的用户 ID。";
    return;
  }
  if (!requireReason()) return;
  await run(async () => {
    const result = await recommendationApi.rebuildUser(
      targetUserId.value.trim(),
      reason.value.trim()
    );
    await load();
    return `已按同一套流水线重建批次 ${result.batch_id}，生成 ${result.generated_size} 条推荐。重建不能指定候选人，也不能修改分数。`;
  });
}

async function runDiagnostics() {
  if (!targetUserId.value.trim()) {
    error.value = "请填写需要诊断的用户 ID。";
    return;
  }
  await run(async () => {
    diagnostics.value = await recommendationApi.userDiagnostics(targetUserId.value.trim());
    return "诊断已生成：仅包含聚合数量与条件代码，不包含任何候选人身份。";
  });
}

async function runPairDiagnostics() {
  if (!targetPairId.value.trim()) {
    error.value = "请填写需要诊断的候选配对 ID。";
    return;
  }
  await run(async () => {
    pairDiagnostics.value = await recommendationApi.pairDiagnostics(targetPairId.value.trim());
    return "配对诊断已记录敏感访问：仅显示特征代码、通过结果、调整项与版本号。";
  });
}

async function runEvaluation() {
  if (!datasetCode.value.trim() || !evaluationStrategyId.value.trim()) {
    error.value = "请填写评估数据集代码与策略 ID。";
    return;
  }
  await run(async () => {
    await recommendationApi.runEvaluation(
      datasetCode.value.trim(),
      evaluationStrategyId.value.trim()
    );
    await load();
    return "离线评估已执行。阻断项未通过的策略无法上线。";
  });
}

async function experimentAction(row: Row, action: "approve" | "start" | "stop") {
  if (!requireReason()) return;
  await run(async () => {
    const result = await recommendationApi.transitionExperiment(
      String(row.id),
      action,
      reason.value.trim()
    );
    await load();
    return `实验状态已变更为 ${result.status}。实验默认关闭，护栏指标越界会立即停止实验。`;
  });
}

async function checkGuardrails(row: Row) {
  await run(async () => {
    const result = await recommendationApi.checkGuardrails(String(row.id));
    await load();
    return `护栏检查完成：${result.stopped ? "已触发自动停止" : "未触发停止"}。`;
  });
}

onMounted(() => void load());
</script>

<template>
  <section class="admin-page recommendation-admin-page">
    <div class="page-heading">
      <div>
        <p class="admin-kicker">
          BATCH 14 · RECOMMENDATION OPERATIONS
        </p>
        <h2>推荐运营中心</h2>
        <p>监督策略版本、批次、候选漏斗、曝光公平、评估与实验。</p>
      </div>
      <el-button
        :loading="busy"
        @click="load"
      >
        刷新
      </el-button>
    </div>

    <el-alert
      title="运营人员只监督引擎：这里没有指定两个人配对、手工改分、绕过硬性条件或查看会员择偶条件原文的入口。"
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

    <el-input
      v-model="reason"
      aria-label="操作原因"
      class="operation-reason"
      placeholder="操作原因（重建、作废、策略与实验状态变更必填，至少 3 个字符，写入审计）"
    />

    <div
      v-if="section === 'dashboard' && dashboard"
      class="metric-grid"
      aria-label="推荐总览"
    >
      <el-card><strong>{{ dashboard.pool.eligible }}</strong><span>可推荐档案</span></el-card>
      <el-card><strong>{{ dashboard.pool.total }}</strong><span>推荐池总量</span></el-card>
      <el-card><strong>{{ dashboard.candidate_pairs.eligible }}</strong><span>有效候选配对</span></el-card>
      <el-card><strong>{{ dashboard.batches.active }}</strong><span>生效批次</span></el-card>
      <el-card><strong>{{ dashboard.batches.failed }}</strong><span>失败批次</span></el-card>
      <el-card><strong>{{ dashboard.batches.empty_batches }}</strong><span>空结果批次</span></el-card>
      <el-card><strong>{{ dashboard.exposure.coverage_ratio_bps }}</strong><span>曝光覆盖率 (bps)</span></el-card>
      <el-card><strong>{{ dashboard.exposure.never_exposed_profiles }}</strong><span>从未曝光档案</span></el-card>
      <el-card><strong>{{ dashboard.feedback.negative_events }}</strong><span>负向反馈（聚合）</span></el-card>
      <el-card><strong>{{ dashboard.cold_start_users }}</strong><span>冷启动会员</span></el-card>
    </div>

    <div
      v-else-if="section === 'strategies'"
      class="section-panel"
    >
      <el-alert
        title="上线前置条件：必须存在通过的离线评估，且审批人与上线人必须是不同的管理员。后端会再次校验，前端不提供跳过入口。"
        type="info"
        :closable="false"
      />
      <el-table
        :data="rows"
        class="admin-table"
        empty-text="暂无策略版本"
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
          min-width="300"
        >
          <template #default="scope">
            <el-button
              size="small"
              @click="openStrategy(scope.row)"
            >
              查看
            </el-button>
            <el-button
              v-if="canApproveStrategy"
              size="small"
              @click="strategyAction(scope.row, 'approve')"
            >
              审批
            </el-button>
            <el-button
              v-if="canActivateStrategy"
              size="small"
              type="success"
              @click="strategyAction(scope.row, 'activate')"
            >
              上线
            </el-button>
            <el-button
              v-if="canRollbackStrategy"
              size="small"
              type="danger"
              @click="strategyAction(scope.row, 'rollback')"
            >
              回滚
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-card
        v-if="strategyDetail"
        class="detail-panel"
      >
        <h3>策略 {{ strategyDetail.strategy.strategy_code }}</h3>
        <p>
          版本 {{ strategyDetail.strategy.semantic_version }} · 状态
          {{ localizeAdminValue(strategyDetail.strategy.status, "status") }}
        </p>
        <h4>评估记录</h4>
        <ul class="code-list">
          <li
            v-for="item in strategyDetail.evaluations"
            :key="String(item.id)"
          >
            {{ localizeAdminValue(item.status, "status") }} · 阻断项 {{ localizeAdminValue(item.blocking_failures) }} · 护栏
            {{ JSON.stringify(item.guardrail_failures) }}
          </li>
        </ul>
        <p
          v-if="!strategyDetail.evaluations.length"
          class="admin-hint"
        >
          尚无评估记录，该版本不可上线。
        </p>
      </el-card>
    </div>

    <div
      v-else-if="section === 'features'"
      class="section-panel"
    >
      <el-alert
        title="特征注册表是只读的：权重、评分函数与版本由策略版本决定，运营不能在此处改分。"
        type="info"
        :closable="false"
      />
      <el-table
        :data="features"
        class="admin-table"
        empty-text="暂无特征"
      >
        <el-table-column
          prop="feature_code"
          label="特征代码"
        />
        <el-table-column
          prop="feature_group"
          label="分组"
        />
        <el-table-column
          prop="semantic_version"
          label="版本"
        />
        <el-table-column
          prop="scoring_function_code"
          label="评分函数"
        />
        <el-table-column
          prop="sensitivity"
          label="敏感级别"
        />
        <el-table-column
          prop="default_weight"
          label="默认权重"
        />
        <el-table-column
          prop="explainable"
          label="可解释"
        />
      </el-table>
    </div>

    <div
      v-else-if="section === 'constraints' && constraints"
      class="section-panel"
    >
      <el-alert
        title="硬性条件只能由策略版本定义，运营无法为单次推荐绕过任何一条。"
        type="info"
        :closable="false"
      />
      <h4>支持的硬性条件代码</h4>
      <ul class="code-list">
        <li
          v-for="code in constraints.supported_criteria"
          :key="code"
        >
          {{ code }}
        </li>
      </ul>
      <h4>当前生效策略的硬性条件配置</h4>
      <pre class="policy-json">{{ JSON.stringify(constraints.policy, null, 2) }}</pre>
    </div>

    <div
      v-else-if="section === 'batches'"
      class="section-panel"
    >
      <div class="inline-form">
        <el-input
          v-model="targetUserId"
          aria-label="用户 ID"
          placeholder="用户 ID"
        />
        <el-button
          v-if="canRebuildBatch"
          :disabled="!reasonReady"
          @click="rebuildUser"
        >
          重建该会员的推荐
        </el-button>
      </div>
      <p class="admin-hint">
        重建只会用同一套流水线重跑一次，不能指定候选人，也不能修改任何分数；原因必填。
      </p>
      <el-table
        :data="rows"
        class="admin-table"
        empty-text="暂无批次"
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
          min-width="200"
        >
          <template #default="scope">
            <el-button
              size="small"
              @click="openBatch(scope.row)"
            >
              查看排序
            </el-button>
            <el-button
              v-if="canInvalidateBatch"
              size="small"
              type="danger"
              :disabled="!reasonReady"
              @click="invalidateBatch(scope.row)"
            >
              作废
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-card
        v-if="batchDetail"
        class="detail-panel"
      >
        <h3>批次 {{ batchDetail.batch.id }}</h3>
        <p>
          状态 {{ localizeAdminValue(batchDetail.batch.status, "status") }} · 生成 {{ batchDetail.batch.generated_size }} /
          请求 {{ batchDetail.batch.requested_size }}
        </p>
        <el-table
          :data="batchDetail.rank_results"
          class="admin-table"
          empty-text="暂无排序结果"
        >
          <el-table-column
            prop="final_rank"
            label="名次"
          />
          <el-table-column
            prop="candidate_pair_id"
            label="候选配对 ID"
          />
          <el-table-column
            prop="base_score_bps"
            label="基础分 (bps)"
          />
          <el-table-column
            prop="adjusted_score_bps"
            label="调整后 (bps)"
          />
          <el-table-column
            prop="novelty_adjustment_bps"
            label="新鲜度调整"
          />
          <el-table-column
            prop="diversity_adjustment_bps"
            label="多样性调整"
          />
          <el-table-column
            prop="exposure_adjustment_bps"
            label="曝光调整"
          />
          <el-table-column
            prop="exploration_adjustment_bps"
            label="探索调整"
          />
        </el-table>
        <p class="admin-hint">
          分数与调整项只读：引擎按策略版本计算，运营不能手工覆盖任何一项。
        </p>
      </el-card>
    </div>

    <div
      v-else-if="section === 'candidates' && candidates"
      class="section-panel"
    >
      <el-alert
        title="候选统计只显示聚合数量，不列出任何会员身份。"
        type="info"
        :closable="false"
      />
      <div class="metric-grid">
        <el-card
          v-for="(total, status) in candidates.pairs_by_status"
          :key="`status-${status}`"
        >
          <strong>{{ total }}</strong><span>配对状态 {{ localizeAdminValue(status, "status") }}</span>
        </el-card>
        <el-card
          v-for="(total, type) in candidates.active_exclusions"
          :key="`exclusion-${type}`"
        >
          <strong>{{ total }}</strong><span>生效排除 {{ localizeAdminValue(type, "type") }}</span>
        </el-card>
      </div>
    </div>

    <div
      v-else-if="section === 'diagnostics'"
      class="section-panel"
    >
      <el-alert
        title="漏斗诊断只返回聚合数量与条件代码：不会显示候选人身份，也不会显示会员填写的择偶条件原文。"
        type="info"
        :closable="false"
      />
      <div class="inline-form">
        <el-input
          v-model="targetUserId"
          aria-label="诊断用户 ID"
          placeholder="用户 ID"
        />
        <el-button @click="runDiagnostics">
          运行诊断
        </el-button>
      </div>
      <div
        v-if="diagnostics"
        class="detail-panel"
      >
        <h4>漏斗数量</h4>
        <pre class="policy-json">{{ JSON.stringify(diagnostics.generation_report, null, 2) }}</pre>
        <h4>冷启动判定</h4>
        <pre class="policy-json">{{ JSON.stringify(diagnostics.cold_start, null, 2) }}</pre>
        <h4>空结果说明</h4>
        <pre class="policy-json">{{ JSON.stringify(diagnostics.empty_result_report, null, 2) }}</pre>
      </div>
    </div>

    <div
      v-else-if="section === 'pair-diagnostics'"
      class="section-panel"
    >
      <el-alert
        title="配对诊断需要独立的敏感权限，每次查看都会记录敏感访问；只显示特征代码、通过结果、调整项与版本号，不显示任何档案内容。"
        type="warning"
        :closable="false"
      />
      <div class="inline-form">
        <el-input
          v-model="targetPairId"
          aria-label="候选配对 ID"
          placeholder="候选配对 ID"
        />
        <el-button @click="runPairDiagnostics">
          查看配对诊断
        </el-button>
      </div>
      <div
        v-if="pairDiagnostics"
        class="detail-panel"
      >
        <p>
          状态 {{ localizeAdminValue(pairDiagnostics.pair.status, "status") }} · 策略 {{ pairDiagnostics.pair.strategy_id }} ·
          投影版本 {{ pairDiagnostics.pair.low_profile_projection_version }} /
          {{ pairDiagnostics.pair.high_profile_projection_version }} ·
          条件版本 {{ pairDiagnostics.pair.low_preference_version }} /
          {{ pairDiagnostics.pair.high_preference_version }}
        </p>
        <h4>硬性条件结果</h4>
        <p>
          是否通过 {{ pairDiagnostics.hard_constraints.passed ? "通过" : "未通过" }} · 策略版本
          {{ pairDiagnostics.hard_constraints.policy_version }}
        </p>
        <p>阻断代码：{{ pairDiagnostics.hard_constraints.blocking_codes.join("、") || "无" }}</p>
        <p>未知代码：{{ pairDiagnostics.hard_constraints.unknown_codes.join("、") || "无" }}</p>
        <p>放宽代码：{{ pairDiagnostics.hard_constraints.relaxed_codes.join("、") || "无" }}</p>
        <h4>双向特征结果</h4>
        <div
          v-for="score in pairDiagnostics.directional_scores"
          :key="String(score.source_user_id)"
          class="direction-block"
        >
          <p>
            总分 {{ score.total_score_bps }} bps · 置信度 {{ score.confidence_bps }} bps ·
            未知特征 {{ score.unknown_feature_count }} · 评分策略
            {{ score.scoring_policy_version }} · 特征注册表 {{ score.feature_registry_version }}
          </p>
          <ul class="code-list">
            <li
              v-for="item in score.feature_scores"
              :key="item.feature_code"
            >
              {{ item.feature_code }} · 匹配 {{ item.raw_match_bps }} bps · 权重
              {{ item.importance_weight }} · 信息{{ item.information_available ? "已知" : "未知" }}
            </li>
          </ul>
        </div>
      </div>
    </div>

    <div
      v-else-if="section === 'exposures' && exposures"
      class="section-panel"
    >
      <div class="metric-grid">
        <el-card><strong>{{ exposures.overview.eligible_profiles }}</strong><span>可推荐档案</span></el-card>
        <el-card><strong>{{ exposures.overview.exposed_profiles }}</strong><span>已曝光档案</span></el-card>
        <el-card><strong>{{ exposures.overview.coverage_ratio_bps }}</strong><span>覆盖率 (bps)</span></el-card>
        <el-card><strong>{{ exposures.overview.exposure_gini_bps }}</strong><span>曝光基尼 (bps)</span></el-card>
        <el-card><strong>{{ exposures.overview.never_exposed_profiles }}</strong><span>从未曝光</span></el-card>
      </div>
      <h4>曝光最多的档案（仅数量，不含身份）</h4>
      <ul class="code-list">
        <li
          v-for="(item, index) in exposures.most_exposed_profiles"
          :key="index"
        >
          第 {{ index + 1 }} 名 · {{ item.total_exposures }} 次 · 最近 {{ item.last_exposed_at }}
        </li>
      </ul>
    </div>

    <div
      v-else-if="section === 'cold-start' && coldStart"
      class="metric-grid"
      aria-label="冷启动总览"
    >
      <el-card><strong>{{ coldStart.eligible_profiles }}</strong><span>可推荐档案</span></el-card>
      <el-card><strong>{{ coldStart.sparse_preference_members }}</strong><span>条件过少会员</span></el-card>
      <el-card><strong>{{ coldStart.new_profiles }}</strong><span>近 14 天新档案</span></el-card>
      <el-card><strong>{{ coldStart.never_exposed_profiles }}</strong><span>从未曝光档案</span></el-card>
    </div>

    <div
      v-else-if="section === 'feedback' && feedback"
      class="section-panel"
    >
      <el-alert
        title="只展示聚合计数。用户填写的自由文本理由保持加密私有，本页面从不请求，也没有查看入口。"
        type="info"
        :closable="false"
      />
      <div class="metric-grid">
        <el-card><strong>{{ feedback.total_events }}</strong><span>反馈总量</span></el-card>
        <el-card><strong>{{ feedback.negative_events }}</strong><span>负向反馈</span></el-card>
        <el-card><strong>{{ feedback.report_events }}</strong><span>举报</span></el-card>
        <el-card><strong>{{ feedback.block_events }}</strong><span>屏蔽</span></el-card>
        <el-card
          v-for="(total, type) in feedback.counts_by_type"
          :key="`feedback-${type}`"
        >
          <strong>{{ total }}</strong><span>{{ localizeAdminValue(type, "type") }}</span>
        </el-card>
      </div>
    </div>

    <div
      v-else-if="section === 'evaluations'"
      class="section-panel"
    >
      <el-alert
        title="离线评估是策略上线的前置条件：阻断项未通过的版本不能上线。"
        type="info"
        :closable="false"
      />
      <div
        v-if="canRunEvaluation"
        class="inline-form"
      >
        <el-input
          v-model="datasetCode"
          aria-label="评估数据集代码"
          placeholder="评估数据集代码"
        />
        <el-input
          v-model="evaluationStrategyId"
          aria-label="待评估策略 ID"
          placeholder="待评估策略 ID"
        />
        <el-button @click="runEvaluation">
          运行评估
        </el-button>
      </div>
      <el-table
        :data="rows"
        class="admin-table"
        empty-text="暂无评估记录"
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
      </el-table>
    </div>

    <div
      v-else-if="section === 'experiments'"
      class="section-panel"
    >
      <el-alert
        title="实验默认关闭：新建后必须先审批才能启动，护栏指标越界会立即停止实验并写入审计。"
        type="info"
        :closable="false"
      />
      <el-table
        :data="rows"
        class="admin-table"
        empty-text="暂无实验"
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
          min-width="320"
        >
          <template #default="scope">
            <el-button
              v-if="canApproveExperiment"
              size="small"
              @click="experimentAction(scope.row, 'approve')"
            >
              审批
            </el-button>
            <el-button
              v-if="canStartExperiment"
              size="small"
              type="success"
              @click="experimentAction(scope.row, 'start')"
            >
              启动
            </el-button>
            <el-button
              v-if="canStopExperiment"
              size="small"
              type="danger"
              @click="experimentAction(scope.row, 'stop')"
            >
              停止
            </el-button>
            <el-button
              v-if="canStopExperiment"
              size="small"
              @click="checkGuardrails(scope.row)"
            >
              护栏检查
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div
      v-else-if="section === 'incidents' || section === 'audit'"
      class="section-panel"
    >
      <el-table
        :data="rows"
        class="admin-table"
        empty-text="暂无记录"
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
      </el-table>
    </div>

    <p class="admin-hint">
      推荐结果由策略版本、特征注册表与硬性条件共同决定；运营的每一次干预都会带原因写入推荐审计，
      并且始终无法指定配对、修改分数或读取会员的择偶条件原文。
    </p>
  </section>
</template>

<style scoped>
.recommendation-admin-page { display: flex; flex-direction: column; gap: 1rem; }
.operation-reason { max-width: 720px; }
.section-panel { display: flex; flex-direction: column; gap: 0.75rem; }
.metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1rem; }
.metric-grid :deep(.el-card__body) { display: grid; gap: 0.4rem; }
.metric-grid strong { font-size: 1.8rem; }
.inline-form { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
.inline-form :deep(.el-input) { max-width: 24rem; }
.detail-panel { display: flex; flex-direction: column; gap: 0.5rem; }
.direction-block { padding: 0.5rem 0; border-top: 1px solid var(--el-border-color); }
.code-list { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.25rem; }
.policy-json { max-height: 20rem; overflow: auto; font-size: 0.8rem; }
.admin-hint { font-size: 0.85rem; opacity: 0.75; }
</style>
