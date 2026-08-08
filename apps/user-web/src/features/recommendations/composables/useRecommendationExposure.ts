import { onBeforeUnmount } from "vue";

import { recommendationsApi } from "@/features/recommendations/api";
import type { ExposurePayload, ExposureType } from "@/features/recommendations/types";

/**
 * A rendered card is not a seen card.
 *
 * `card_impression` is reported when the card mounts. `card_visible` is only
 * reported once the card has been *continuously* visible for at least this
 * many milliseconds, and always carries the measured duration.
 */
export const VISIBLE_THRESHOLD_MS = 1000;

/** Fraction of the card that must be on screen before the timer starts. */
export const VISIBLE_INTERSECTION_RATIO = 0.5;

export type ExposureSender = (itemId: string, payload: ExposurePayload) => unknown;

export type ExposureTrackerOptions = {
  send: ExposureSender;
  source?: string;
  thresholdMs?: number;
  now?: () => number;
};

/**
 * Clock-injectable exposure bookkeeping shared by the composable and tests.
 *
 * Every event is de-duplicated per item + exposure type, so a card scrolling
 * in and out of view reports at most one impression and one visible event.
 */
export function createExposureTracker(options: ExposureTrackerOptions) {
  const thresholdMs = options.thresholdMs ?? VISIBLE_THRESHOLD_MS;
  const source = options.source ?? "recommendation_list";
  const clock = options.now ?? (() => Date.now());
  const sent = new Set<string>();
  const visibleSince = new Map<string, number>();

  function key(itemId: string, exposureType: ExposureType) {
    return `${itemId}:${exposureType}`;
  }

  function record(itemId: string, exposureType: ExposureType, durationMs?: number) {
    const eventKey = key(itemId, exposureType);
    if (sent.has(eventKey)) return false;
    sent.add(eventKey);
    options.send(itemId, {
      exposure_type: exposureType,
      duration_ms: durationMs ?? null,
      source
    });
    return true;
  }

  return {
    thresholdMs,
    /** Card mounted and rendered. Reported once per item. */
    impression(itemId: string) {
      return record(itemId, "card_impression");
    },
    /** The card entered the viewport; starts (or restarts) the continuous timer. */
    enter(itemId: string, at: number = clock()) {
      if (sent.has(key(itemId, "card_visible"))) return;
      visibleSince.set(itemId, at);
    },
    /**
     * The card left the viewport. Reports `card_visible` when the uninterrupted
     * visible time already reached the threshold, otherwise the timer resets and
     * nothing is reported — partial visibility never accumulates.
     */
    leave(itemId: string, at: number = clock()) {
      const startedAt = visibleSince.get(itemId);
      visibleSince.delete(itemId);
      if (startedAt === undefined) return false;
      const durationMs = at - startedAt;
      if (durationMs < thresholdMs) return false;
      return record(itemId, "card_visible", durationMs);
    },
    /** Reports every still-visible card that has now passed the threshold. */
    tick(at: number = clock()) {
      const reported: string[] = [];
      for (const [itemId, startedAt] of visibleSince) {
        const durationMs = at - startedAt;
        if (durationMs < thresholdMs) continue;
        if (record(itemId, "card_visible", durationMs)) reported.push(itemId);
      }
      return reported;
    },
    /** The member opened the full recommendation. */
    profileOpened(itemId: string, opts: { source?: string } = {}) {
      const eventKey = key(itemId, "profile_opened");
      if (sent.has(eventKey)) return false;
      sent.add(eventKey);
      options.send(itemId, {
        exposure_type: "profile_opened",
        duration_ms: null,
        source: opts.source ?? source
      });
      return true;
    },
    hasSent(itemId: string, exposureType: ExposureType) {
      return sent.has(key(itemId, exposureType));
    },
    isTiming(itemId: string) {
      return visibleSince.has(itemId);
    },
    reset() {
      sent.clear();
      visibleSince.clear();
    }
  };
}

export type ExposureTracker = ReturnType<typeof createExposureTracker>;

export function useRecommendationExposure(options: { source?: string } = {}) {
  const failures = new Set<string>();
  const tracker = createExposureTracker({
    source: options.source,
    send: (itemId, payload) => {
      void recommendationsApi.recordExposure(itemId, payload).catch(() => {
        // Exposure telemetry must never interrupt the member's browsing.
        failures.add(itemId);
      });
    }
  });

  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  const observed = new WeakMap<Element, string>();
  let observer: IntersectionObserver | undefined;

  function clearTimer(itemId: string) {
    const timer = timers.get(itemId);
    if (timer !== undefined) {
      clearTimeout(timer);
      timers.delete(itemId);
    }
  }

  function startTimer(itemId: string) {
    clearTimer(itemId);
    timers.set(
      itemId,
      setTimeout(() => {
        timers.delete(itemId);
        tracker.tick();
      }, tracker.thresholdMs)
    );
  }

  function ensureObserver() {
    if (observer || typeof IntersectionObserver === "undefined") return observer;
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const itemId = observed.get(entry.target);
          if (!itemId) continue;
          if (entry.isIntersecting && entry.intersectionRatio >= VISIBLE_INTERSECTION_RATIO) {
            tracker.enter(itemId);
            startTimer(itemId);
          } else {
            clearTimer(itemId);
            tracker.leave(itemId);
          }
        }
      },
      { threshold: [0, VISIBLE_INTERSECTION_RATIO, 1] }
    );
    return observer;
  }

  /** Attach a card element; reports the impression immediately, then watches visibility. */
  function observeCard(element: Element | null | undefined, itemId: string) {
    if (!element) return;
    tracker.impression(itemId);
    observed.set(element, itemId);
    ensureObserver()?.observe(element);
  }

  function unobserveCard(element: Element | null | undefined) {
    if (!element) return;
    const itemId = observed.get(element);
    if (itemId) {
      clearTimer(itemId);
      tracker.leave(itemId);
      observed.delete(element);
    }
    observer?.unobserve(element);
  }

  function reportProfileOpened(itemId: string, source?: string) {
    tracker.profileOpened(itemId, { source });
  }

  function disconnect() {
    for (const itemId of timers.keys()) clearTimeout(timers.get(itemId)!);
    timers.clear();
    observer?.disconnect();
    observer = undefined;
  }

  onBeforeUnmount(disconnect);

  return {
    tracker,
    observeCard,
    unobserveCard,
    reportProfileOpened,
    disconnect,
    thresholdMs: tracker.thresholdMs
  };
}
