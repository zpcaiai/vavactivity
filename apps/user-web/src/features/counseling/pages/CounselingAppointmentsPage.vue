<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { counselingApi, type CounselingAppointment } from "../api";

const route = useRoute();
const appointments = ref<CounselingAppointment[]>([]);
const detail = ref<CounselingAppointment>();
const error = ref("");

async function load() {
  try {
    if (route.params.appointmentId) {
      detail.value = await counselingApi.appointment(String(route.params.appointmentId));
    } else {
      appointments.value = (await counselingApi.appointments()).items;
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "预约记录加载失败";
  }
}

async function cancel(id: string) {
  await counselingApi.cancel(id);
  await load();
}

onMounted(() => void load());
</script>

<template>
  <section class="content-page counseling-account">
    <h1>我的辅导预约</h1>
    <p
      v-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
    <article
      v-if="detail"
      class="product-card"
    >
      <h2>{{ detail.appointment_number }}</h2>
      <p>状态：{{ detail.status }}</p>
      <p v-if="detail.scheduled_starts_at">
        时间：{{ new Date(detail.scheduled_starts_at).toLocaleString() }}
      </p>
      <p>会谈入口仅在预约窗口内签发，录音与转写默认关闭。</p>
      <button
        v-if="detail.status === 'confirmed'"
        type="button"
        @click="cancel(detail.id)"
      >
        取消预约
      </button>
    </article>
    <div
      v-else
      class="product-grid"
    >
      <article
        v-for="appointment in appointments"
        :key="appointment.id"
        class="product-card"
      >
        <h2>{{ appointment.appointment_number }}</h2>
        <p>状态：{{ appointment.status }}</p>
        <RouterLink
          :to="`/${String(route.params.locale)}/account/counseling/${appointment.id}`"
        >
          查看预约
        </RouterLink>
      </article>
    </div>
  </section>
</template>
