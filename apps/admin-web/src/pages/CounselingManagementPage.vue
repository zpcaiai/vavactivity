<script setup lang="ts">
import { onMounted, ref } from "vue";

import { catalogApi } from "@/features/catalog/api";

type Mentor = { id: string; mentor_code: string; display_name: string; status: string; timezone: string };
type Service = { id: string; service_code: string; internal_name: string; status: string; booking_mode: string };
type Appointment = {
  id: string;
  appointment_number: string;
  status: string;
  scheduled_starts_at?: string | null;
  payment_status: string;
};

const mentors = ref<Mentor[]>([]);
const services = ref<Service[]>([]);
const appointments = ref<Appointment[]>([]);
const error = ref("");
const tab = ref("appointments");

async function load() {
  error.value = "";
  try {
    const [mentorResult, serviceResult, appointmentResult] = await Promise.all([
      catalogApi<{ items: Mentor[] }>("/admin/counseling/mentors"),
      catalogApi<{ items: Service[] }>("/admin/counseling/services"),
      catalogApi<{ items: Appointment[] }>("/admin/counseling/appointments")
    ]);
    mentors.value = mentorResult.items;
    services.value = serviceResult.items;
    appointments.value = appointmentResult.items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "辅导中心加载失败";
  }
}

async function transition(appointment: Appointment, target_status: string) {
  try {
    await catalogApi(`/admin/counseling/appointments/${appointment.id}/transition`, {
      method: "POST",
      body: JSON.stringify({
        target_status,
        reason: `Operator transition to ${target_status} from counseling center`
      })
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "预约状态变更失败";
  }
}

onMounted(() => void load());
</script>

<template>
  <section class="admin-module counseling-admin">
    <div class="module-heading">
      <div>
        <p class="admin-kicker">
          COUNSELING OPERATIONS
        </p>
        <h2>辅导中心</h2>
        <p>导师、服务、排班、预约、交付记录与安全转介按最小权限分层管理。</p>
      </div>
      <el-button @click="load">
        刷新
      </el-button>
    </div>
    <el-alert
      title="本模块不是心理治疗、医疗诊断、法律或紧急服务；录音与转写默认关闭。"
      type="warning"
      :closable="false"
      show-icon
    />
    <p
      v-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
    <el-tabs v-model="tab">
      <el-tab-pane
        label="预约队列"
        name="appointments"
      >
        <el-table
          :data="appointments"
          empty-text="暂无预约"
        >
          <el-table-column
            prop="appointment_number"
            label="预约号"
          />
          <el-table-column
            prop="status"
            label="状态"
          />
          <el-table-column
            prop="scheduled_starts_at"
            label="预约时间"
          />
          <el-table-column
            prop="payment_status"
            label="支付"
          />
          <el-table-column
            label="操作"
            min-width="280"
          >
            <template #default="scope">
              <el-button
                v-if="scope.row.status === 'pending_review'"
                size="small"
                @click="transition(scope.row, 'approved_pending_payment')"
              >
                批准
              </el-button>
              <el-button
                v-if="scope.row.status === 'pending_review'"
                size="small"
                type="danger"
                @click="transition(scope.row, 'rejected')"
              >
                拒绝
              </el-button>
              <el-button
                v-if="scope.row.status === 'confirmed'"
                size="small"
                @click="transition(scope.row, 'no_show')"
              >
                标记未到
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        label="导师"
        name="mentors"
      >
        <el-table
          :data="mentors"
          empty-text="暂无导师"
        >
          <el-table-column
            prop="mentor_code"
            label="代码"
          />
          <el-table-column
            prop="display_name"
            label="名称"
          />
          <el-table-column
            prop="timezone"
            label="时区"
          />
          <el-table-column
            prop="status"
            label="状态"
          />
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        label="服务与发布"
        name="services"
      >
        <el-table
          :data="services"
          empty-text="暂无服务"
        >
          <el-table-column
            prop="service_code"
            label="代码"
          />
          <el-table-column
            prop="internal_name"
            label="内部名称"
          />
          <el-table-column
            prop="booking_mode"
            label="预约模式"
          />
          <el-table-column
            prop="status"
            label="状态"
          />
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        label="安全与记录"
        name="safety"
      >
        <p>导师私密笔记与安全转介详情需要独立权限，普通预约列表永不返回这些字段。</p>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>
