<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "vue-i18n";

import {
  activityApi,
  type ActivityGroup,
  type ActivityMatch,
  type ActivityParticipant,
  type PublicActivity
} from "../api";

const route = useRoute();
const { t } = useI18n();
const activityId = String(route.params.activityId);
const activity = ref<PublicActivity>();
const participants = ref<ActivityParticipant[]>([]);
const choices = ref(new Map<string, string>());
const group = ref<ActivityGroup>();
const matches = ref<ActivityMatch[]>([]);
const credential = ref("");
const error = ref("");
const postEventStatus = ref("");
const profile = reactive({ display_name: "", brief_introduction: "", consent: false });

async function load() {
  error.value = "";
  try {
    activity.value = await activityApi.access(activityId);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "活动通行信息加载失败";
    return;
  }
  const [participantResult, choiceResult, groupResult, matchResult] = await Promise.allSettled([
    activityApi.participants(activityId),
    activityApi.choices(activityId),
    activityApi.group(activityId),
    activityApi.matches()
  ]);
  if (participantResult.status === "fulfilled") participants.value = participantResult.value.items;
  if (choiceResult.status === "fulfilled") {
    choices.value = new Map(
      choiceResult.value.items.map((item) => [item.chosen_user_id, item.choice])
    );
  }
  if (groupResult.status === "fulfilled") group.value = groupResult.value;
  if (matchResult.status === "fulfilled") {
    matches.value = matchResult.value.items.filter((item) => item.activity_id === activityId);
  }
  if (participantResult.status === "rejected") {
    postEventStatus.value = "活动后参与者目录会在活动完成、互选窗口开放且已签到后显示。";
  }
}

async function issueCredential() {
  try {
    credential.value = (await activityApi.credential(activityId)).token;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "签到码生成失败";
  }
}

async function saveProfile() {
  try {
    await activityApi.saveParticipantProfile(activityId, {
      ...profile,
      visibility_status: "visible"
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "参与者资料保存失败";
  }
}

async function choose(participantId: string, value: "interested" | "pass") {
  try {
    await activityApi.choose(activityId, participantId, value);
    choices.value.set(participantId, value);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "选择提交失败";
  }
}

async function withdraw(participantId: string) {
  try {
    await activityApi.withdrawChoice(activityId, participantId);
    choices.value.delete(participantId);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "撤回失败";
  }
}

onMounted(() => void load());
</script>

<template>
  <section class="commerce-page activity-experience">
    <p class="eyebrow">
      ACTIVITY ACCESS
    </p>
    <h1>{{ activity?.title ?? t("activities.participantAccess") }}</h1>
    <p
      v-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>

    <section
      v-if="activity"
      class="commerce-card"
    >
      <h2>{{ t("activities.accessInfo") }}</h2>
      <p>{{ new Date(activity.starts_at).toLocaleString() }} · {{ activity.timezone }}</p>
      <p
        v-for="location in activity.locations"
        :key="String(location.id)"
      >
        {{ location.venue_name }} {{ location.address_line_1 }}
        <a
          v-if="location.online_join_url"
          :href="String(location.online_join_url)"
        >
          进入线上会议
        </a>
      </p>
      <button
        type="button"
        @click="issueCredential"
      >
        {{ t("activities.checkinPass") }}
      </button>
      <code v-if="credential">{{ credential }}</code>
    </section>

    <section
      v-if="group"
      class="commerce-card"
    >
      <h2>{{ t("activities.myGroup") }} · {{ group.display_name ?? group.group_code }}</h2>
      <p
        v-for="member in group.members"
        :key="member.display_name"
      >
        <strong>{{ member.display_name }}</strong> {{ member.brief_introduction }}
      </p>
    </section>

    <section class="commerce-card">
      <h2>{{ t("activities.profile") }}</h2>
      <p>{{ t("activities.profileBoundary") }}</p>
      <label>{{ t("activities.displayName") }} <input v-model="profile.display_name"></label>
      <label>{{ t("activities.introduction") }} <textarea v-model="profile.brief_introduction" /></label>
      <label><input
        v-model="profile.consent"
        type="checkbox"
      > {{ t("activities.profileConsent") }}</label>
      <button
        type="button"
        :disabled="!profile.consent || !profile.display_name"
        @click="saveProfile"
      >
        {{ t("activities.saveProfile") }}
      </button>
      <p v-if="postEventStatus">
        {{ postEventStatus }}
      </p>
    </section>

    <section
      v-if="participants.length"
      class="product-grid"
    >
      <article
        v-for="participant in participants"
        :key="participant.user_id"
        class="product-card"
      >
        <h2>{{ participant.display_name }}</h2>
        <p>{{ participant.brief_introduction }}</p>
        <p>{{ t("activities.choicePrivacy") }}</p>
        <button
          type="button"
          @click="choose(participant.user_id, 'interested')"
        >
          {{ t("activities.interested") }}
        </button>
        <button
          type="button"
          @click="choose(participant.user_id, 'pass')"
        >
          {{ t("activities.pass") }}
        </button>
        <button
          v-if="choices.has(participant.user_id)"
          type="button"
          @click="withdraw(participant.user_id)"
        >
          {{ t("activities.withdraw") }}
        </button>
      </article>
    </section>

    <section
      v-if="matches.length"
      class="commerce-card"
    >
      <h2>{{ t("activities.privateMatches") }}</h2>
      <p
        v-for="match in matches"
        :key="match.id"
      >
        {{ new Date(match.matched_at).toLocaleString() }} · 联系方式仍保持私密，等待认识邀请政策确认。
      </p>
    </section>
  </section>
</template>
