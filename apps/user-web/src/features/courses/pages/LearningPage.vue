<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import {
  courseApi,
  type CourseLesson,
  type Enrollment,
  type ExerciseAttempt
} from "../api";

const route = useRoute();
const dashboard = ref<Enrollment>();
const selected = ref<CourseLesson>();
const lessonBody = ref<Awaited<ReturnType<typeof courseApi.lesson>>>();
const playbackSession = ref("");
const heartbeatSequence = ref(0);
const playedSeconds = ref(0);
const attempt = ref<ExerciseAttempt>();
const responses = ref<Record<string, unknown>>({});
const attemptResult = ref<{
  status: string;
  score_basis_points?: number | null;
  passed?: boolean | null;
}>();
const loading = ref(true);
const error = ref("");
const draftSaved = ref(false);
const lessons = computed(
  () => dashboard.value?.course?.modules?.flatMap((module) => module.lessons) ?? []
);

async function load() {
  try {
    dashboard.value = await courseApi.dashboard(String(route.params.enrollmentId));
    const requestedLesson = lessons.value.find(
      (lesson) => lesson.id === String(route.params.lessonId ?? "")
    );
    if (requestedLesson) await openLesson(requestedLesson);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "学习中心加载失败";
  } finally {
    loading.value = false;
  }
}

async function openLesson(lesson: CourseLesson) {
  error.value = "";
  try {
    selected.value = lesson;
    attempt.value = undefined;
    attemptResult.value = undefined;
    responses.value = {};
    lessonBody.value = await courseApi.lesson(String(route.params.enrollmentId), lesson.id);
    await courseApi.event(String(route.params.enrollmentId), lesson.id, "lesson_opened");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "课时暂不可访问";
  }
}

async function completeManual() {
  if (!selected.value) return;
  await courseApi.event(
    String(route.params.enrollmentId),
    selected.value.id,
    "manual_completed"
  );
  await load();
}

async function startPlayback() {
  if (!selected.value) return;
  const playback = await courseApi.playback(
    String(route.params.enrollmentId),
    selected.value.id
  );
  playbackSession.value = playback.session_id;
  heartbeatSequence.value = 0;
  playedSeconds.value = 0;
}

async function sendHeartbeat() {
  if (!playbackSession.value) return;
  heartbeatSequence.value += 1;
  playedSeconds.value += 15;
  await courseApi.heartbeat(
    playbackSession.value,
    heartbeatSequence.value,
    playedSeconds.value,
    15
  );
  await load();
}

async function startExercise() {
  if (!lessonBody.value?.exercise_id) return;
  error.value = "";
  try {
    attempt.value = await courseApi.startAttempt(
      String(route.params.enrollmentId),
      lessonBody.value.exercise_id
    );
    responses.value = Object.fromEntries(
      attempt.value.questions
        .filter((question) => question.question_type === "multiple_choice")
        .map((question) => [question.id, []])
    );
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "练习暂时无法开始";
  }
}

async function submitExercise() {
  if (!attempt.value) return;
  error.value = "";
  try {
    attemptResult.value = await courseApi.submitAttempt(
      attempt.value.id,
      responses.value
    );
    attempt.value = undefined;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "练习提交失败";
  }
}

async function saveExerciseDraft() {
  if (!attempt.value) return;
  await courseApi.saveAttempt(attempt.value.id, responses.value);
  draftSaved.value = true;
}

function promptText(question: ExerciseAttempt["questions"][number]) {
  return question.prompt_blocks.map((block) => block.text).filter(Boolean).join("\n");
}

function setResponse(questionId: string, value: unknown) {
  responses.value[questionId] = value;
}

function toggleResponse(questionId: string, value: unknown, checked: boolean) {
  const current = Array.isArray(responses.value[questionId])
    ? [...(responses.value[questionId] as unknown[])]
    : [];
  responses.value[questionId] = checked
    ? [...current, value]
    : current.filter((item) => item !== value);
}

onMounted(() => void load());
</script>

<template>
  <section class="catalog-page learning-page">
    <p class="eyebrow">
      MY LEARNING
    </p>
    <h1>{{ dashboard?.course?.title ?? "我的课程" }}</h1>
    <p
      v-if="loading"
      role="status"
    >
      正在加载学习进度…
    </p>
    <p
      v-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
    <div
      v-if="dashboard"
      class="learning-grid"
    >
      <nav
        class="commerce-card"
        aria-label="课程课时"
      >
        <button
          v-for="lesson in lessons"
          :key="lesson.id"
          type="button"
          @click="openLesson(lesson)"
        >
          {{ lesson.title }}
        </button>
      </nav>
      <article
        v-if="lessonBody"
        class="commerce-card"
      >
        <p class="eyebrow">
          {{ lessonBody.lesson_type }}
        </p>
        <h2>{{ lessonBody.title }}</h2>
        <p
          v-for="(block, index) in lessonBody.content_blocks"
          :key="index"
        >
          {{ block.text }}
        </p>
        <button
          v-if="lessonBody.completion_mode === 'manual'"
          type="button"
          @click="completeManual"
        >
          标记完成
        </button>
        <template v-if="lessonBody.completion_mode === 'video_watch'">
          <button
            v-if="!playbackSession"
            type="button"
            @click="startPlayback"
          >
            开始安全播放
          </button>
          <button
            v-else
            type="button"
            @click="sendHeartbeat"
          >
            记录 15 秒有效观看（{{ playedSeconds }} 秒）
          </button>
          <p class="privacy-note">
            跳转到结尾不会计为完成；有效观看时间由服务端验证。
          </p>
        </template>
        <section
          v-if="lessonBody.exercise_id"
          class="exercise-panel"
          aria-label="课时练习"
        >
          <h3>课时练习</h3>
          <button
            v-if="!attempt && !attemptResult"
            type="button"
            @click="startExercise"
          >
            开始练习
          </button>
          <form
            v-if="attempt"
            @submit.prevent="submitExercise"
          >
            <fieldset
              v-for="question in attempt.questions"
              :key="question.id"
            >
              <legend>{{ promptText(question) }}</legend>
              <template
                v-if="['single_choice', 'true_false'].includes(question.question_type)"
              >
                <label
                  v-for="option in question.options"
                  :key="String(option.value)"
                >
                  <input
                    type="radio"
                    :name="question.id"
                    :value="String(option.value)"
                    :checked="responses[question.id] === option.value"
                    :required="question.required"
                    @change="setResponse(question.id, option.value)"
                  >
                  {{ option.label }}
                </label>
              </template>
              <template v-else-if="question.question_type === 'multiple_choice'">
                <label
                  v-for="option in question.options"
                  :key="String(option.value)"
                >
                  <input
                    type="checkbox"
                    :value="String(option.value)"
                    :checked="Array.isArray(responses[question.id]) && (responses[question.id] as unknown[]).includes(option.value)"
                    @change="toggleResponse(question.id, option.value, ($event.target as HTMLInputElement).checked)"
                  >
                  {{ option.label }}
                </label>
              </template>
              <textarea
                v-else
                :value="String(responses[question.id] ?? '')"
                :required="question.required"
                rows="4"
                @input="setResponse(question.id, ($event.target as HTMLTextAreaElement).value)"
              />
            </fieldset>
            <button type="submit">
              提交练习
            </button>
            <button
              type="button"
              @click="saveExerciseDraft"
            >
              保存草稿
            </button>
            <span
              v-if="draftSaved"
              role="status"
            >已保存</span>
          </form>
          <p
            v-if="attemptResult"
            role="status"
          >
            <template v-if="attemptResult.status === 'pending_manual_grade'">
              作业已提交，等待人工评分。
            </template>
            <template v-else>
              {{ attemptResult.passed ? "练习已通过" : "练习未通过" }}
              <span v-if="attemptResult.score_basis_points != null">
                （{{ attemptResult.score_basis_points / 100 }} 分）
              </span>
            </template>
          </p>
        </section>
      </article>
      <p v-else>
        请选择一个课时开始学习。
      </p>
    </div>
  </section>
</template>
