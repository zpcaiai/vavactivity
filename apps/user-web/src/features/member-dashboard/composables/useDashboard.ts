import { computed, ref } from "vue";

import { dashboardApiClient } from "@/features/member-dashboard/api";
import type {
  DashboardPreferences,
  DashboardSection,
  DashboardSectionKey,
  DashboardSectionOk,
  DashboardTask,
  DashboardView
} from "@/features/member-dashboard/types";
import { isSectionAvailable } from "@/features/member-dashboard/types";

/** Display order. The server returns an object, which has no ordering. */
export const SECTION_ORDER: DashboardSectionKey[] = [
  "survey_tasks",
  "mutual_selection",
  "result_letters",
  "registrations",
  "matchmaking",
  "notifications"
];

export function useDashboard() {
  const view = ref<DashboardView | null>(null);
  const preferences = ref<DashboardPreferences>({ hidden_sections: [], page_size: 20 });
  const loading = ref(false);
  const error = ref<string | null>(null);
  const errorCode = ref<string | null>(null);
  const busyTaskKey = ref<string | null>(null);

  /**
   * Sections in display order, skipping keys the server did not send.
   *
   * A missing key means the member is not eligible for that section. Rendering
   * a placeholder for it would tell them the feature exists and is merely
   * broken, which is exactly the disclosure the server took care to avoid.
   */
  const orderedSections = computed<{ key: DashboardSectionKey; section: DashboardSection }[]>(() => {
    const sections = view.value?.sections ?? {};
    return SECTION_ORDER.flatMap((key) => {
      const section = sections[key];
      return section ? [{ key, section }] : [];
    });
  });

  const visibleSections = computed(() =>
    orderedSections.value.filter(({ key }) => !preferences.value.hidden_sections.includes(key))
  );

  const hiddenCount = computed(
    () => orderedSections.value.length - visibleSections.value.length
  );

  const degraded = computed<DashboardSectionKey[]>(() => view.value?.degraded ?? []);

  /** Total across working sections only — a degraded section contributes none. */
  const totalOpenTasks = computed(() => view.value?.total_open_tasks ?? 0);

  const urgentTasks = computed<DashboardTask[]>(() =>
    orderedSections.value
      .map(({ section }) => section)
      .filter(isSectionAvailable)
      .flatMap((section: DashboardSectionOk) => section.items)
      .filter((task) => task.priority === "urgent")
  );

  async function load(locale?: string) {
    loading.value = true;
    error.value = null;
    errorCode.value = null;
    try {
      // Preferences are cosmetic; a failure there must not blank the board.
      const [dashboard, prefs] = await Promise.all([
        dashboardApiClient.dashboard({ locale, limit: preferences.value.page_size }),
        dashboardApiClient.preferences().catch(() => preferences.value)
      ]);
      view.value = dashboard;
      preferences.value = prefs;
    } catch (caught) {
      error.value = (caught as Error).message;
      errorCode.value = (caught as Error & { code?: string }).code ?? null;
    } finally {
      loading.value = false;
    }
  }

  /** Load the next page of one section and append it in place. */
  async function loadMore(key: DashboardSectionKey, locale?: string) {
    const current = view.value?.sections[key];
    if (!current || !isSectionAvailable(current) || !current.has_more) return;
    const next = await dashboardApiClient.section(key, {
      locale,
      limit: current.limit,
      offset: current.offset + current.items.length
    });
    if (!view.value || !isSectionAvailable(next)) return;
    view.value = {
      ...view.value,
      sections: {
        ...view.value.sections,
        [key]: { ...next, items: [...current.items, ...next.items] }
      }
    };
  }

  async function toggleSection(key: DashboardSectionKey) {
    const hidden = preferences.value.hidden_sections.includes(key)
      ? preferences.value.hidden_sections.filter((item) => item !== key)
      : [...preferences.value.hidden_sections, key];
    const previous = preferences.value;
    preferences.value = { ...preferences.value, hidden_sections: hidden };
    try {
      preferences.value = await dashboardApiClient.savePreferences(preferences.value);
    } catch (caught) {
      // Roll the optimistic change back rather than leaving the UI claiming a
      // preference the server never stored.
      preferences.value = previous;
      error.value = (caught as Error).message;
      errorCode.value = (caught as Error & { code?: string }).code ?? null;
    }
  }

  async function dismiss(task: DashboardTask, locale?: string) {
    busyTaskKey.value = task.task_key;
    try {
      await dashboardApiClient.dismiss({ task_type: task.task_type, task_key: task.task_key });
      await load(locale);
    } catch (caught) {
      error.value = (caught as Error).message;
      errorCode.value = (caught as Error & { code?: string }).code ?? null;
    } finally {
      busyTaskKey.value = null;
    }
  }

  return {
    view,
    preferences,
    loading,
    error,
    errorCode,
    busyTaskKey,
    orderedSections,
    visibleSections,
    hiddenCount,
    degraded,
    totalOpenTasks,
    urgentTasks,
    load,
    loadMore,
    toggleSection,
    dismiss
  };
}
