import { computed, ref } from "vue";

import { postEventApiClient } from "@/features/post-event/api";
import type {
  CandidateBoard,
  SelectionPayload,
  SelectionState
} from "@/features/post-event/types";

/**
 * Mutual-selection state for one activity (MUT-002).
 *
 * The ceiling, the minimum and the allowed pass reasons all come from the
 * server's board payload. The composable mirrors those rules locally only to
 * disable a control before the user clicks — every rule is re-enforced
 * server-side, and a local check is never the thing that protects the
 * invariant.
 */
export function useMutualSelection() {
  const board = ref<CandidateBoard | null>(null);
  const selection = ref<SelectionState | null>(null);
  const selectedIds = ref<string[]>([]);
  const reasonCode = ref<string | null>(null);
  const reasonNote = ref("");
  const loading = ref(false);
  const saving = ref(false);
  const error = ref<string | null>(null);
  const errorCode = ref<string | null>(null);
  const notice = ref<string | null>(null);

  const maxSelections = computed(() => board.value?.max_selections ?? 0);
  const minSelections = computed(() => board.value?.min_selections ?? 0);
  const remaining = computed(() => Math.max(0, maxSelections.value - selectedIds.value.length));
  const hasSelection = computed(() => selectedIds.value.length > 0);

  /** Selecting nobody is a valid outcome, but it needs a configured reason. */
  const requiresReason = computed(
    () => !hasSelection.value && (board.value?.pass_reasons.length ?? 0) > 0
  );

  const selectedReason = computed(
    () => board.value?.pass_reasons.find((item) => item.reason_code === reasonCode.value) ?? null
  );

  const requiresNote = computed(() => selectedReason.value?.requires_note ?? false);

  const isSubmitted = computed(() => selection.value?.status === "submitted");

  const editableUntil = computed(() =>
    selection.value?.editable_until ? new Date(selection.value.editable_until) : null
  );

  /** Mirrors the server's edit window so a doomed submit is disabled early. */
  const editWindowClosed = computed(() => {
    if (!isSubmitted.value || !editableUntil.value) return false;
    return Date.now() > editableUntil.value.getTime();
  });

  const canSubmit = computed(() => {
    if (saving.value || editWindowClosed.value) return false;
    if (selectedIds.value.length > maxSelections.value) return false;
    if (selectedIds.value.length < minSelections.value) return false;
    if (requiresReason.value && !reasonCode.value) return false;
    if (requiresNote.value && !reasonNote.value.trim()) return false;
    return true;
  });

  function isSelected(userId: string): boolean {
    return selectedIds.value.includes(userId);
  }

  /** Returns false when the pick was refused so the caller can explain why. */
  function toggle(userId: string): boolean {
    if (isSelected(userId)) {
      selectedIds.value = selectedIds.value.filter((item) => item !== userId);
      return true;
    }
    if (selectedIds.value.length >= maxSelections.value) return false;
    selectedIds.value = [...selectedIds.value, userId];
    // Choosing someone makes a "chose nobody" reason meaningless; the server
    // rejects a payload carrying both.
    reasonCode.value = null;
    reasonNote.value = "";
    return true;
  }

  function applyState(next: SelectionState) {
    selection.value = next;
    selectedIds.value = [...next.selected_user_ids];
    reasonCode.value = next.no_selection_reason_code ?? null;
    reasonNote.value = next.no_selection_reason_note ?? "";
  }

  async function load(activityId: string) {
    loading.value = true;
    error.value = null;
    errorCode.value = null;
    try {
      const [boardResult, selectionResult] = await Promise.all([
        postEventApiClient.candidates(activityId),
        postEventApiClient.selection(activityId)
      ]);
      board.value = boardResult;
      applyState(selectionResult);
    } catch (caught) {
      error.value = (caught as Error).message;
      errorCode.value = (caught as Error & { code?: string }).code ?? null;
    } finally {
      loading.value = false;
    }
  }

  async function save(activityId: string, status: "draft" | "submitted") {
    saving.value = true;
    error.value = null;
    errorCode.value = null;
    notice.value = null;
    const payload: SelectionPayload = {
      selected_user_ids: selectedIds.value,
      no_selection_reason_code: hasSelection.value ? null : reasonCode.value,
      no_selection_reason_note: hasSelection.value ? null : reasonNote.value.trim() || null,
      status
    };
    try {
      applyState(await postEventApiClient.saveSelection(activityId, payload));
      notice.value = status;
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
    board,
    selection,
    selectedIds,
    reasonCode,
    reasonNote,
    loading,
    saving,
    error,
    errorCode,
    notice,
    maxSelections,
    minSelections,
    remaining,
    hasSelection,
    requiresReason,
    requiresNote,
    isSubmitted,
    editableUntil,
    editWindowClosed,
    canSubmit,
    isSelected,
    toggle,
    load,
    save
  };
}
