<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  LETTER_TRANSITIONS,
  postEventAdminApi,
  surveyAdminApi,
  type CandidateEntry,
  type CandidateSnapshot,
  type LetterDetail,
  type LetterSummary,
  type SurveyAggregate,
  type SurveyDefinition,
  type SurveyQuestionDraft,
  type SurveyQuestionType
} from "@/features/post-event/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();

const section = computed(() => String(route.meta.postEventSection ?? "candidates"));

const activityId = ref("");
const snapshotId = ref("");
const busy = ref(false);
const error = ref("");
const notice = ref("");

// --- candidate freeze -------------------------------------------------------
const snapshot = ref<CandidateSnapshot | null>(null);
const freezeNote = ref("");
const supersede = ref(false);
const exclusionReasons = ref<Record<string, string>>({});
const matchCount = ref<number | null>(null);

// --- letters ----------------------------------------------------------------
const letters = ref<LetterSummary[]>([]);
const statusFilter = ref("");
const openLetter = ref<LetterDetail | null>(null);
const reviewComment = ref("");
const revokeReason = ref("");
const generateLocale = ref("zh-CN");
const regenerate = ref(false);

const entries = computed<CandidateEntry[]>(() => snapshot.value?.entries ?? []);
const eligible = computed(() => entries.value.filter((item) => item.eligibility === "eligible"));
const excluded = computed(() => entries.value.filter((item) => item.eligibility === "excluded"));

function can(permission: string): boolean {
  return auth.permissions.includes(permission);
}

/** Only a manual exclusion can be undone: a no-show is a fact, not a decision. */
function reversible(entry: CandidateEntry): boolean {
  return entry.exclusion_kind === "manual";
}

// --- survey authoring (B10) -------------------------------------------------
const definitionId = ref("");
const assignmentId = ref("");
const surveyDefinition = ref<SurveyDefinition | null>(null);
const surveyAggregate = ref<SurveyAggregate | null>(null);
const surveyCode = ref("");
const surveyVersion = ref("1.0.0");
const surveyTitle = ref("");
const surveyDescription = ref("");
const surveyQuestions = ref<SurveyQuestionDraft[]>([]);
const assignDeadline = ref("");
const assignOpensAt = ref("");
const assignReminders = ref("48,12");
const assignSnapshotId = ref("");
const reopenUserId = ref("");
const reopenReason = ref("");

const QUESTION_TYPES: SurveyQuestionType[] = [
  "rating",
  "segment_rating",
  "single_choice",
  "multi_choice",
  "open_text",
  "boolean"
];

/**
 * A published definition is frozen: the item set a member answered must stay
 * exactly what they answered. Editing means cutting a new version, so the form
 * goes read-only rather than silently writing to a live questionnaire.
 */
const definitionIsFrozen = computed(() => surveyDefinition.value?.status === "published");

function addQuestion() {
  surveyQuestions.value = [
    ...surveyQuestions.value,
    {
      question_code: "",
      question_type: "rating",
      prompt: "",
      help_text: null,
      is_required: true,
      per_subject: false,
      position: surveyQuestions.value.length + 1,
      config: {}
    }
  ];
}

function removeQuestion(index: number) {
  surveyQuestions.value = surveyQuestions.value
    .filter((_, at) => at !== index)
    .map((question, at) => ({ ...question, position: at + 1 }));
}

async function createDefinition() {
  await run(async () => {
    const created = await surveyAdminApi.createDefinition({
      survey_code: surveyCode.value.trim(),
      semantic_version: surveyVersion.value.trim(),
      title: surveyTitle.value.trim(),
      description: surveyDescription.value.trim() || null,
      questions: surveyQuestions.value
    });
    surveyDefinition.value = created;
    definitionId.value = String(created.definition_id ?? created.id ?? "");
  }, "问卷草稿已创建");
}

async function loadDefinition() {
  await run(async () => {
    surveyDefinition.value = await surveyAdminApi.definition(definitionId.value.trim());
    surveyQuestions.value = surveyDefinition.value.questions ?? [];
  }, "已载入问卷");
}

async function publishDefinition() {
  await run(async () => {
    surveyDefinition.value = await surveyAdminApi.publishDefinition(definitionId.value.trim());
  }, "问卷已发布，题目已冻结");
}

async function assignSurvey() {
  await run(async () => {
    const assignment = await surveyAdminApi.assign(activityId.value.trim(), {
      definition_id: definitionId.value.trim(),
      deadline_at: new Date(assignDeadline.value).toISOString(),
      opens_at: assignOpensAt.value ? new Date(assignOpensAt.value).toISOString() : null,
      reminder_offsets_hours: assignReminders.value
        .split(",")
        .map((part) => Number(part.trim()))
        .filter((value) => Number.isFinite(value)),
      snapshot_id: assignSnapshotId.value.trim() || null
    });
    assignmentId.value = String(assignment.assignment_id ?? assignment.id ?? "");
  }, "问卷已下发");
}

async function generateTasks() {
  await run(
    () => surveyAdminApi.generateTasks(assignmentId.value.trim()),
    "任务已生成（重复调用不会重复发放）"
  );
}

async function sendReminders() {
  await run(() => surveyAdminApi.sendReminders(assignmentId.value.trim()), "提醒已排队");
}

async function loadAggregate() {
  await run(async () => {
    surveyAggregate.value = await surveyAdminApi.aggregate(assignmentId.value.trim());
  }, "已载入统计");
}

async function reopenResponse() {
  await run(
    () =>
      surveyAdminApi.reopen(
        assignmentId.value.trim(),
        reopenUserId.value.trim(),
        reopenReason.value.trim()
      ),
    "已重新开放该成员的问卷"
  );
}

const availableTransitions = computed(() =>
  openLetter.value?.status ? (LETTER_TRANSITIONS[openLetter.value.status] ?? []) : []
);

async function run(action: () => Promise<unknown>, successMessage: string) {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    await action();
    notice.value = successMessage;
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    busy.value = false;
  }
}

async function freeze() {
  if (!activityId.value) return;
  await run(async () => {
    const result = await postEventAdminApi.freeze(activityId.value, {
      freeze_note: freezeNote.value.trim() || null,
      supersede_existing: supersede.value
    });
    snapshot.value = result;
    snapshotId.value = String(result.id ?? "");
  }, "候选人名单已冻结");
}

async function loadSnapshot() {
  if (!snapshotId.value) return;
  await run(async () => {
    snapshot.value = await postEventAdminApi.snapshot(snapshotId.value, true);
  }, "已刷新");
}

async function exclude(entry: CandidateEntry) {
  const reason = (exclusionReasons.value[entry.user_id] ?? "").trim();
  // The server enforces this too; refusing here avoids a pointless round trip
  // and, more importantly, keeps the operator from thinking it worked.
  if (reason.length < 4) {
    error.value = "请填写至少 4 个字的排除原因";
    return;
  }
  await run(async () => {
    await postEventAdminApi.exclude(snapshotId.value, entry.user_id, reason);
    exclusionReasons.value = { ...exclusionReasons.value, [entry.user_id]: "" };
    snapshot.value = await postEventAdminApi.snapshot(snapshotId.value, true);
  }, "已排除并记录原因");
}

async function restore(entry: CandidateEntry) {
  const reason = (exclusionReasons.value[entry.user_id] ?? "").trim();
  if (reason.length < 4) {
    error.value = "请填写至少 4 个字的恢复原因";
    return;
  }
  await run(async () => {
    await postEventAdminApi.restore(snapshotId.value, entry.user_id, reason);
    exclusionReasons.value = { ...exclusionReasons.value, [entry.user_id]: "" };
    snapshot.value = await postEventAdminApi.snapshot(snapshotId.value, true);
  }, "已恢复为可选");
}

async function loadMatches() {
  if (!snapshotId.value) return;
  await run(async () => {
    matchCount.value = (await postEventAdminApi.matches(snapshotId.value)).count;
  }, "已统计互选结果");
}

async function loadLetters() {
  if (!activityId.value) return;
  await run(async () => {
    letters.value = (
      await postEventAdminApi.letters(activityId.value, statusFilter.value || undefined)
    ).items;
  }, "已刷新结果信列表");
}

async function generate() {
  if (!activityId.value || !snapshotId.value) return;
  await run(async () => {
    await postEventAdminApi.generateLetters(
      activityId.value,
      snapshotId.value,
      generateLocale.value,
      regenerate.value
    );
    letters.value = (await postEventAdminApi.letters(activityId.value)).items;
  }, "已生成草稿");
}

async function open(letterId: string) {
  await run(async () => {
    openLetter.value = await postEventAdminApi.letter(letterId);
    reviewComment.value = "";
  }, "已打开");
}

async function decide(decision: "approved" | "rejected" | "changes_requested") {
  const letter = openLetter.value;
  if (!letter) return;
  if (decision !== "approved" && !reviewComment.value.trim()) {
    error.value = "驳回或要求修改必须写明理由";
    return;
  }
  await run(async () => {
    // Send back the hash we were given. If the draft changed since it was
    // opened the server refuses, which is exactly what should happen.
    await postEventAdminApi.review(
      String(letter.id),
      decision,
      letter.content_hash,
      reviewComment.value.trim() || undefined
    );
    openLetter.value = await postEventAdminApi.letter(String(letter.id));
    letters.value = (await postEventAdminApi.letters(activityId.value)).items;
  }, "审核结果已记录");
}

async function submitForReview() {
  const letter = openLetter.value;
  if (!letter) return;
  await run(async () => {
    await postEventAdminApi.submitForReview(String(letter.id));
    openLetter.value = await postEventAdminApi.letter(String(letter.id));
  }, "已提交审核");
}

async function publish() {
  const letter = openLetter.value;
  if (!letter) return;
  await run(async () => {
    await postEventAdminApi.publish(String(letter.id), true);
    openLetter.value = await postEventAdminApi.letter(String(letter.id));
    letters.value = (await postEventAdminApi.letters(activityId.value)).items;
  }, "已发布并通知");
}

async function revoke() {
  const letter = openLetter.value;
  if (!letter) return;
  if (revokeReason.value.trim().length < 4) {
    error.value = "撤回必须写明原因";
    return;
  }
  await run(async () => {
    await postEventAdminApi.revoke(String(letter.id), revokeReason.value.trim());
    revokeReason.value = "";
    openLetter.value = await postEventAdminApi.letter(String(letter.id));
    letters.value = (await postEventAdminApi.letters(activityId.value)).items;
  }, "已撤回");
}

watch(section, () => {
  error.value = "";
  notice.value = "";
});

onMounted(() => auth.bootstrap());
</script>

<template>
  <section class="post-event-admin">
    <header class="post-event-admin__header">
      <h1>活动后闭环</h1>
      <p>候选人冻结、互选结果与结果信审核。</p>
    </header>

    <div class="post-event-admin__context">
      <label>
        活动 ID
        <input
          v-model="activityId"
          type="text"
          placeholder="activity uuid"
        >
      </label>
      <label>
        快照 ID
        <input
          v-model="snapshotId"
          type="text"
          placeholder="snapshot uuid"
        >
      </label>
    </div>

    <p
      v-if="error"
      class="post-event-admin__error"
      role="alert"
    >
      {{ error }}
    </p>
    <p
      v-else-if="notice"
      class="post-event-admin__notice"
      role="status"
    >
      {{ notice }}
    </p>

    <!-- Candidate freeze -->
    <template v-if="section === 'candidates'">
      <section class="post-event-admin__panel">
        <h2>冻结候选人名单</h2>
        <p class="post-event-admin__hint">
          冻结后的名单不可就地修改。需要更正时勾选「取代现有快照」，系统会生成新版本并保留旧版本。
        </p>
        <label>
          冻结备注
          <input
            v-model="freezeNote"
            type="text"
            maxlength="1000"
          >
        </label>
        <label class="post-event-admin__checkbox">
          <input
            v-model="supersede"
            type="checkbox"
          >
          取代现有快照（生成新版本）
        </label>
        <div class="post-event-admin__actions">
          <button
            type="button"
            :disabled="busy || !activityId || !can('activities.candidates.freeze')"
            @click="freeze"
          >
            冻结名单
          </button>
          <button
            type="button"
            :disabled="busy || !snapshotId"
            @click="loadSnapshot"
          >
            读取快照
          </button>
          <button
            type="button"
            :disabled="busy || !snapshotId"
            @click="loadMatches"
          >
            统计互选结果
          </button>
        </div>
        <p v-if="matchCount !== null">
          互选成功 {{ matchCount }} 对。
        </p>
      </section>

      <section
        v-if="snapshot"
        class="post-event-admin__panel"
      >
        <h2>
          快照 v{{ snapshot.snapshot_version }} · 可选 {{ eligible.length }} · 已排除
          {{ excluded.length }}
        </h2>

        <table class="post-event-admin__table">
          <thead>
            <tr>
              <th scope="col">
                成员
              </th>
              <th scope="col">
                状态
              </th>
              <th scope="col">
                原因
              </th>
              <th scope="col">
                操作
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="entry in entries"
              :key="entry.user_id"
            >
              <td>{{ entry.display_name }}</td>
              <td>{{ entry.eligibility === "eligible" ? "可选" : entry.exclusion_kind }}</td>
              <td>{{ entry.exclusion_reason ?? "—" }}</td>
              <td>
                <input
                  v-model="exclusionReasons[entry.user_id]"
                  type="text"
                  placeholder="填写原因（至少 4 字）"
                  maxlength="1000"
                >
                <button
                  v-if="entry.eligibility === 'eligible'"
                  type="button"
                  :disabled="busy || !can('activities.candidates.exclude')"
                  @click="exclude(entry)"
                >
                  排除
                </button>
                <button
                  v-else-if="reversible(entry)"
                  type="button"
                  :disabled="busy || !can('activities.candidates.exclude')"
                  @click="restore(entry)"
                >
                  恢复
                </button>
                <span v-else>不可恢复</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>

    <!-- Survey authoring -->
    <template v-else-if="section === 'surveys'">
      <section class="post-event-admin__panel">
        <h2>问卷定义</h2>
        <p class="post-event-admin__hint">
          平台不预置任何题目，问卷内容全部由运营撰写。发布后题目冻结，需要修改就发新版本。
        </p>

        <div class="post-event-admin__context">
          <label>
            问卷定义 ID
            <input
              v-model="definitionId"
              type="text"
              placeholder="definition uuid"
            >
          </label>
          <button
            type="button"
            :disabled="busy || !definitionId.trim()"
            @click="loadDefinition"
          >
            载入
          </button>
        </div>

        <p
          v-if="definitionIsFrozen"
          class="post-event-admin__hint"
        >
          这份问卷已发布，题目不可再修改。
        </p>

        <label>
          问卷代码
          <input
            v-model="surveyCode"
            type="text"
            placeholder="post_event_feedback"
            :disabled="definitionIsFrozen"
          >
        </label>
        <label>
          语义版本
          <input
            v-model="surveyVersion"
            type="text"
            :disabled="definitionIsFrozen"
          >
        </label>
        <label>
          标题
          <input
            v-model="surveyTitle"
            type="text"
            maxlength="300"
            :disabled="definitionIsFrozen"
          >
        </label>
        <label>
          说明
          <textarea
            v-model="surveyDescription"
            rows="2"
            maxlength="4000"
            :disabled="definitionIsFrozen"
          />
        </label>

        <h3>题目</h3>
        <table class="post-event-admin__table">
          <thead>
            <tr>
              <th>序号</th>
              <th>代码</th>
              <th>类型</th>
              <th>题干</th>
              <th>必答</th>
              <th>逐人作答</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(question, index) in surveyQuestions"
              :key="index"
            >
              <td>{{ question.position }}</td>
              <td>
                <input
                  v-model="question.question_code"
                  type="text"
                  :disabled="definitionIsFrozen"
                >
              </td>
              <td>
                <select
                  v-model="question.question_type"
                  :disabled="definitionIsFrozen"
                >
                  <option
                    v-for="type in QUESTION_TYPES"
                    :key="type"
                    :value="type"
                  >
                    {{ type }}
                  </option>
                </select>
              </td>
              <td>
                <input
                  v-model="question.prompt"
                  type="text"
                  maxlength="2000"
                  :disabled="definitionIsFrozen"
                >
              </td>
              <td>
                <input
                  v-model="question.is_required"
                  type="checkbox"
                  :disabled="definitionIsFrozen"
                >
              </td>
              <td>
                <input
                  v-model="question.per_subject"
                  type="checkbox"
                  :disabled="definitionIsFrozen"
                >
              </td>
              <td>
                <button
                  type="button"
                  :disabled="busy || definitionIsFrozen"
                  @click="removeQuestion(index)"
                >
                  删除
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        <div class="post-event-admin__actions">
          <button
            type="button"
            :disabled="busy || definitionIsFrozen"
            @click="addQuestion"
          >
            新增题目
          </button>
          <button
            type="button"
            :disabled="busy || definitionIsFrozen || !surveyQuestions.length || !can('surveys.definitions.manage')"
            @click="createDefinition"
          >
            创建草稿
          </button>
          <button
            type="button"
            :disabled="busy || !definitionId.trim() || definitionIsFrozen || !can('surveys.definitions.manage')"
            @click="publishDefinition"
          >
            发布并冻结
          </button>
        </div>
      </section>

      <section class="post-event-admin__panel">
        <h2>下发与提醒</h2>
        <p class="post-event-admin__hint">
          绑定快照后，逐人作答的题目只会出现名单里的人。生成任务可以重复调用，不会重复发放。
        </p>

        <label>
          截止时间
          <input
            v-model="assignDeadline"
            type="datetime-local"
          >
        </label>
        <label>
          开放时间（选填）
          <input
            v-model="assignOpensAt"
            type="datetime-local"
          >
        </label>
        <label>
          提醒提前量（小时，逗号分隔）
          <input
            v-model="assignReminders"
            type="text"
          >
        </label>
        <label>
          绑定的候选人快照 ID（选填）
          <input
            v-model="assignSnapshotId"
            type="text"
            placeholder="snapshot uuid"
          >
        </label>

        <div class="post-event-admin__actions">
          <button
            type="button"
            :disabled="busy || !activityId.trim() || !definitionId.trim() || !assignDeadline || !can('surveys.assignments.manage')"
            @click="assignSurvey"
          >
            下发问卷
          </button>
          <button
            type="button"
            :disabled="busy || !assignmentId.trim() || !can('surveys.assignments.manage')"
            @click="generateTasks"
          >
            生成任务
          </button>
          <button
            type="button"
            :disabled="busy || !assignmentId.trim() || !can('surveys.assignments.manage')"
            @click="sendReminders"
          >
            发送提醒
          </button>
        </div>

        <label>
          下发记录 ID
          <input
            v-model="assignmentId"
            type="text"
            placeholder="assignment uuid"
          >
        </label>
      </section>

      <section class="post-event-admin__panel">
        <h2>统计</h2>
        <button
          type="button"
          :disabled="busy || !assignmentId.trim()"
          @click="loadAggregate"
        >
          载入统计
        </button>

        <template v-if="surveyAggregate">
          <!--
            低于 k 匿名阈值时服务端会拒绝返回明细。这里如实说明，不用零或空列表
            冒充「没有数据」。
          -->
          <p
            v-if="surveyAggregate.suppressed"
            class="post-event-admin__hint"
          >
            回收量低于匿名阈值，明细已被服务端抑制（{{ surveyAggregate.suppression_reason }}）。
          </p>
          <p v-else>
            回收 {{ surveyAggregate.response_count }} 份 · 完成率
            {{ ((surveyAggregate.completion_rate_bps ?? 0) / 100).toFixed(2) }}%
          </p>
        </template>

        <h3>重新开放个别成员</h3>
        <label>
          成员 ID
          <input
            v-model="reopenUserId"
            type="text"
          >
        </label>
        <label>
          原因（会写入审计）
          <input
            v-model="reopenReason"
            type="text"
            maxlength="1000"
          >
        </label>
        <button
          type="button"
          :disabled="busy || !assignmentId.trim() || !reopenUserId.trim() || reopenReason.trim().length < 4 || !can('surveys.assignments.manage')"
          @click="reopenResponse"
        >
          重新开放
        </button>
      </section>
    </template>

    <!-- Result letters -->
    <template v-else-if="section === 'letters'">
      <section class="post-event-admin__panel">
        <h2>生成与筛选</h2>
        <div class="post-event-admin__actions">
          <label>
            语言
            <input
              v-model="generateLocale"
              type="text"
            >
          </label>
          <label class="post-event-admin__checkbox">
            <input
              v-model="regenerate"
              type="checkbox"
            >
            重新生成（已发布的信会新建版本，原文不变）
          </label>
          <button
            type="button"
            :disabled="busy || !activityId || !snapshotId || !can('result_letters.generate')"
            @click="generate"
          >
            生成草稿
          </button>
        </div>
        <div class="post-event-admin__actions">
          <label>
            状态
            <select v-model="statusFilter">
              <option value="">
                全部
              </option>
              <option value="draft">
                草稿
              </option>
              <option value="pending_review">
                待审核
              </option>
              <option value="approved">
                已通过
              </option>
              <option value="published">
                已发布
              </option>
              <option value="rejected">
                已驳回
              </option>
              <option value="revoked">
                已撤回
              </option>
            </select>
          </label>
          <button
            type="button"
            :disabled="busy || !activityId"
            @click="loadLetters"
          >
            刷新列表
          </button>
        </div>
      </section>

      <section class="post-event-admin__panel">
        <h2>结果信（{{ letters.length }}）</h2>
        <table class="post-event-admin__table">
          <thead>
            <tr>
              <th scope="col">
                收信人
              </th>
              <th scope="col">
                结果
              </th>
              <th scope="col">
                状态
              </th>
              <th scope="col">
                版本
              </th>
              <th scope="col">
                操作
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="letter in letters"
              :key="String(letter.id)"
            >
              <td>{{ letter.recipient_user_id }}</td>
              <td>{{ letter.outcome }}</td>
              <td>{{ letter.status }}</td>
              <td>{{ letter.version }}</td>
              <td>
                <button
                  type="button"
                  :disabled="busy || !can('result_letters.review')"
                  @click="open(String(letter.id))"
                >
                  查看
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section
        v-if="openLetter"
        class="post-event-admin__panel"
      >
        <h2>{{ openLetter.subject }}</h2>
        <p class="post-event-admin__hint">
          当前状态 {{ openLetter.status }} · 内容指纹
          {{ openLetter.content_hash.slice(0, 12) }}…（审核会带上这个指纹，草稿若已变动服务端会拒绝）
        </p>
        <pre class="post-event-admin__body">{{ openLetter.body }}</pre>

        <label>
          审核意见
          <textarea
            v-model="reviewComment"
            rows="3"
            maxlength="2000"
          />
        </label>

        <div class="post-event-admin__actions">
          <button
            v-if="availableTransitions.includes('pending_review')"
            type="button"
            :disabled="busy || !can('result_letters.generate')"
            @click="submitForReview"
          >
            提交审核
          </button>
          <button
            v-if="availableTransitions.includes('approved')"
            type="button"
            :disabled="busy || !can('result_letters.review')"
            @click="decide('approved')"
          >
            通过
          </button>
          <button
            v-if="availableTransitions.includes('rejected')"
            type="button"
            :disabled="busy || !can('result_letters.review')"
            @click="decide('rejected')"
          >
            驳回
          </button>
          <button
            v-if="availableTransitions.includes('published')"
            type="button"
            :disabled="busy || !can('result_letters.publish')"
            @click="publish"
          >
            发布并通知
          </button>
        </div>

        <div
          v-if="availableTransitions.includes('revoked')"
          class="post-event-admin__actions"
        >
          <label>
            撤回原因
            <input
              v-model="revokeReason"
              type="text"
              maxlength="1000"
            >
          </label>
          <button
            type="button"
            :disabled="busy || !can('result_letters.revoke')"
            @click="revoke"
          >
            撤回
          </button>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.post-event-admin {
  display: grid;
  gap: var(--vav-space-5);
}

.post-event-admin__header p,
.post-event-admin__hint {
  color: var(--vav-color-text-secondary);
}

.post-event-admin__context,
.post-event-admin__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--vav-space-3);
}

.post-event-admin__panel {
  display: grid;
  gap: var(--vav-space-3);
  padding: var(--vav-space-4);
  border: var(--vav-border-width) solid var(--vav-color-border-default);
  border-radius: var(--vav-radius-md);
  background: var(--vav-color-surface-default);
}

.post-event-admin__checkbox {
  display: flex;
  align-items: center;
  gap: var(--vav-space-2);
}

.post-event-admin__error {
  color: var(--vav-color-danger-text);
}

.post-event-admin__notice {
  color: var(--vav-color-success-text);
}

.post-event-admin__table {
  width: 100%;
  border-collapse: collapse;
}

.post-event-admin__table th,
.post-event-admin__table td {
  padding: var(--vav-space-2);
  border-bottom: var(--vav-border-width) solid var(--vav-color-border-subtle);
  text-align: left;
  vertical-align: top;
}

.post-event-admin__body {
  padding: var(--vav-space-3);
  border-radius: var(--vav-radius-sm);
  background: var(--vav-color-surface-subtle);
  color: var(--vav-color-text-primary);
  font: inherit;
  white-space: pre-wrap;
}
</style>
