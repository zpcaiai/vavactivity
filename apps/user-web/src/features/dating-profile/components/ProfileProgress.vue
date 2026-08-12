<script setup lang="ts">
import { VCard, VChip, VProgress } from "@vav/ui-core";

import type { Completeness, DatingProfile } from "@/features/dating-profile/api";

defineProps<{
  profile?: DatingProfile;
  completeness?: Completeness;
  percent: number;
  missingCount: number;
  measureNote: string;
  missingLabel: string;
  numberLabel: string;
  statusLabel: string;
  reviewLabel: string;
  approvedLabel: string;
  progressLabel: string;
}>();
</script>

<template>
  <VCard
    tone="soft"
    padding="compact"
  >
    <div class="profile-progress__chips">
      <VChip
        v-if="profile?.profile_number"
        tone="neutral"
        :label="`${numberLabel} ${profile.profile_number}`"
      />
      <VChip
        tone="brand"
        :label="`${statusLabel} ${profile?.status ?? '-'}`"
      />
      <VChip
        tone="info"
        :label="`${reviewLabel} ${profile?.review_status ?? '-'}`"
      />
      <VChip
        v-if="profile?.approved_version_number"
        tone="success"
        :label="`${approvedLabel} v${profile.approved_version_number}`"
      />
    </div>
    <VProgress
      :value="percent"
      :max="100"
      :label="progressLabel"
      :show-value="false"
    />
    <p>
      {{ percent }}% · {{ measureNote }}
      <span v-if="missingCount"> · {{ missingLabel }} {{ missingCount }}</span>
    </p>
  </VCard>
</template>

<style scoped>
.profile-progress__chips { display: flex; flex-wrap: wrap; gap: var(--vav-space-2); }
p { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); margin: 0; }
</style>
