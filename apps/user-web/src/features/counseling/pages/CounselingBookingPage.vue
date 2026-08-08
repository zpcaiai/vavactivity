<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { counselingApi, type CounselingService } from "../api";

const route = useRoute();
const router = useRouter();
const service = ref<CounselingService>();
const slots = ref<Array<{ starts_at: string; ends_at: string }>>([]);
const selected = ref("");
const intake = ref("");
const error = ref("");
const submitting = ref(false);

function dateValue(offset: number) {
  const value = new Date();
  value.setDate(value.getDate() + offset);
  return value.toISOString().slice(0, 10);
}

onMounted(async () => {
  try {
    service.value = await counselingApi.service(
      String(route.params.slug),
      String(route.params.locale)
    );
    const mentorId = service.value.mentor_ids[0];
    if (!mentorId) throw new Error("当前没有可预约导师");
    slots.value = (
      await counselingApi.availability(mentorId, service.value.id, dateValue(1), dateValue(14))
    ).items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "可预约时间加载失败";
  }
});

async function submit() {
  if (!service.value || !selected.value || !intake.value.trim()) return;
  submitting.value = true;
  error.value = "";
  try {
    const mentorId = service.value.mentor_ids[0];
    const hold = await counselingApi.hold(mentorId, service.value.id, selected.value);
    const appointment = await counselingApi.book(
      service.value.id,
      mentorId,
      hold.id,
      intake.value
    );
    await router.push(`/${String(route.params.locale)}/account/counseling/${appointment.id}`);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "预约提交失败";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <section class="content-page counseling-booking">
    <p class="eyebrow">
      PRIVATE BOOKING
    </p>
    <h1>预约{{ service?.name ?? "真人辅导" }}</h1>
    <p>可见时段不等于已预约；提交时系统会再次锁定并确认名额。</p>
    <p
      v-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
    <fieldset>
      <legend>选择时间</legend>
      <label
        v-for="slot in slots"
        :key="slot.starts_at"
      >
        <input
          v-model="selected"
          type="radio"
          name="slot"
          :value="slot.starts_at"
        >
        {{ new Date(slot.starts_at).toLocaleString() }}
      </label>
    </fieldset>
    <label>
      本次希望讨论的目标
      <textarea
        v-model="intake"
        rows="5"
        required
      />
    </label>
    <p class="scope-notice">
      若处于即时危险或危机，请联系当地紧急服务；本平台不是紧急服务。
    </p>
    <button
      type="button"
      :disabled="submitting || !selected || !intake.trim()"
      @click="submit"
    >
      {{ submitting ? "正在确认…" : "确认预约" }}
    </button>
  </section>
</template>
