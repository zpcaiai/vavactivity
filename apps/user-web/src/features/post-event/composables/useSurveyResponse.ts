import { computed, ref } from "vue";

import { postEventApiClient } from "@/features/post-event/api";
import type {
  SurveyAnswer,
  SurveyDetail,
  SurveyQuestion
} from "@/features/post-event/types";

/** Answers are keyed by question plus subject; `-` is the event-level subject. */
function answerKey(questionCode: string, subjectUserId?: string | null): string {
  return `${questionCode}::${subjectUserId ?? "-"}`;
}

/**
 * Post-event survey answering (SUR-001).
 *
 * Drafts autosave without validation so a member is never blocked mid-thought;
 * a real submit runs the full rule set on the server. The deadline is compared
 * against the server's `deadline_at`, and rendered in the activity's
 * `display_timezone` — display and enforcement are deliberately separate.
 */
export function useSurveyResponse() {
  const detail = ref<SurveyDetail | null>(null);
  const answers = ref<Map<string, SurveyAnswer>>(new Map());
  const loading = ref(false);
  const saving = ref(false);
  const error = ref<string | null>(null);
  const errorCode = ref<string | null>(null);
  const savedAt = ref<Date | null>(null);

  const questions = computed<SurveyQuestion[]>(
    () => detail.value?.definition.questions ?? []
  );
  const subjects = computed(() => detail.value?.subjects ?? []);
  const isSubmitted = computed(() => detail.value?.response?.status === "submitted");

  const deadline = computed(() =>
    detail.value?.deadline_at ? new Date(detail.value.deadline_at) : null
  );

  const deadlinePassed = computed(() => {
    if (!deadline.value) return false;
    return Date.now() > deadline.value.getTime();
  });

  const notYetOpen = computed(() => {
    if (!detail.value?.opens_at) return false;
    return Date.now() < new Date(detail.value.opens_at).getTime();
  });

  const editable = computed(() => !deadlinePassed.value && !notYetOpen.value);

  /** Which answers a submit still needs. Empty means the form is complete. */
  const missingRequired = computed(() => {
    const missing: { questionCode: string; subjectUserId: string | null }[] = [];
    for (const question of questions.value) {
      if (!question.is_required) continue;
      const targets = question.per_subject
        ? subjects.value.map((subject) => subject.user_id)
        : [null];
      for (const subject of targets) {
        const answer = answers.value.get(answerKey(question.question_code, subject));
        if (!answer || isBlank(question, answer)) {
          missing.push({ questionCode: question.question_code, subjectUserId: subject });
        }
      }
    }
    return missing;
  });

  const canSubmit = computed(
    () => editable.value && !saving.value && missingRequired.value.length === 0
  );

  function isBlank(question: SurveyQuestion, answer: SurveyAnswer): boolean {
    switch (question.question_type) {
      case "rating":
      case "segment_rating":
        return answer.rating_value === null || answer.rating_value === undefined;
      case "single_choice":
      case "multi_choice":
        return (answer.choice_values?.length ?? 0) === 0;
      case "open_text":
        return !(answer.text_value ?? "").trim();
      case "boolean":
        return answer.boolean_value === null || answer.boolean_value === undefined;
      default:
        return true;
    }
  }

  function get(questionCode: string, subjectUserId?: string | null): SurveyAnswer | undefined {
    return answers.value.get(answerKey(questionCode, subjectUserId));
  }

  function set(next: SurveyAnswer) {
    const map = new Map(answers.value);
    map.set(answerKey(next.question_code, next.subject_user_id), next);
    answers.value = map;
  }

  function hydrate(next: SurveyDetail) {
    detail.value = next;
    const map = new Map<string, SurveyAnswer>();
    for (const answer of next.response?.answers ?? []) {
      map.set(answerKey(answer.question_code, answer.subject_user_id), answer);
    }
    answers.value = map;
  }

  async function load(assignmentId: string) {
    loading.value = true;
    error.value = null;
    errorCode.value = null;
    try {
      hydrate(await postEventApiClient.survey(assignmentId));
    } catch (caught) {
      error.value = (caught as Error).message;
      errorCode.value = (caught as Error & { code?: string }).code ?? null;
    } finally {
      loading.value = false;
    }
  }

  /** Drops answers that are still blank so a draft never trips validation. */
  function payloadAnswers(): SurveyAnswer[] {
    const byCode = new Map(questions.value.map((item) => [item.question_code, item]));
    return [...answers.value.values()].filter((answer) => {
      const question = byCode.get(answer.question_code);
      return question ? !isBlank(question, answer) : false;
    });
  }

  async function save(assignmentId: string, status: "draft" | "submitted") {
    saving.value = true;
    error.value = null;
    errorCode.value = null;
    try {
      hydrate(
        await postEventApiClient.saveSurvey(assignmentId, {
          answers: payloadAnswers(),
          status
        })
      );
      savedAt.value = new Date();
      return true;
    } catch (caught) {
      error.value = (caught as Error).message;
      errorCode.value = (caught as Error & { code?: string }).code ?? null;
      return false;
    } finally {
      saving.value = false;
    }
  }

  return {
    detail,
    questions,
    subjects,
    loading,
    saving,
    error,
    errorCode,
    savedAt,
    isSubmitted,
    deadline,
    deadlinePassed,
    notYetOpen,
    editable,
    missingRequired,
    canSubmit,
    get,
    set,
    load,
    save
  };
}
