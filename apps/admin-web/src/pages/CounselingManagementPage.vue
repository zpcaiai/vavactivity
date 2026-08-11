<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { formatAdminTableCell, localizeAdminValue } from "@vav/ui-admin";

import { catalogApi } from "@/features/catalog/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

type Mentor = { id: string; mentor_code: string; display_name: string; status: string; timezone: string };
type Service = { id: string; service_code: string; internal_name: string; status: string; booking_mode: string };
type Appointment = {
  id: string; appointment_number: string; mentor_id?: string | null; service_id: string; status: string;
  scheduled_starts_at?: string | null; scheduled_ends_at?: string | null; payment_status: string;
  proposal_version: number; version: number;
};
type Schedule = {
  id: string; mentor_id: string; service_id?: string | null; timezone: string; weekday: number;
  local_start_time: string; local_end_time: string; valid_from: string; valid_until?: string | null;
  daily_limit?: number | null; weekly_limit?: number | null; status: string;
};
type FollowUp = {
  id: string; appointment_id: string; user_id: string; assigned_to?: string | null;
  follow_up_type: string; status: string; due_at?: string | null; content: Record<string, unknown>;
  created_at: string;
};

const auth = useAdminAuthStore();
const mentors = ref<Mentor[]>([]);
const services = ref<Service[]>([]);
const appointments = ref<Appointment[]>([]);
const schedules = ref<Schedule[]>([]);
const followups = ref<FollowUp[]>([]);
const error = ref("");
const notice = ref("");
const busy = ref(false);
const tab = ref("appointments");
const actionReason = ref("");
const rescheduleOpen = ref(false);
const followupOpen = ref(false);
const selectedAppointment = ref<Appointment>();
const rescheduleForm = ref({ mentor_id: "", starts_at: "", reason: "" });
const today = new Date().toISOString().slice(0, 10);
const scheduleForm = ref({
  mentor_id: "", service_id: "", timezone: "Asia/Shanghai", weekday: 1,
  local_start_time: "09:00", local_end_time: "17:00", valid_from: today,
  valid_until: "", daily_limit: 6, weekly_limit: 30,
});
const followupForm = ref({ follow_up_type: "action_item", content: "", due_at: "" });

const canManageAppointments = computed(() => auth.hasPermission("counseling.appointments.manage"));
const canManageSchedules = computed(() => auth.hasPermission("counseling.schedules.manage"));
const canManageFollowups = computed(() => auth.hasPermission("counseling.followups.manage"));
const canReadMentors = computed(() => auth.hasPermission("counseling.mentors.read"));
const canReadServices = computed(() => auth.hasPermission("counseling.services.read"));
const weekdayLabels = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"];

function mentorName(id?: string | null) {
  return mentors.value.find((item) => item.id === id)?.display_name ?? "未分配";
}
function serviceName(id?: string | null) {
  return services.value.find((item) => item.id === id)?.internal_name ?? "全部服务";
}

function canReschedule(status: string) {
  return ["pending_review", "time_proposed", "confirmed", "reschedule_requested"].includes(status);
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    await auth.bootstrap();
    const tasks = [
      canReadMentors.value
        ? catalogApi<{ items: Mentor[] }>("/admin/counseling/mentors")
        : Promise.resolve({ items: [] as Mentor[] }),
      canReadServices.value
        ? catalogApi<{ items: Service[] }>("/admin/counseling/services")
        : Promise.resolve({ items: [] as Service[] }),
      catalogApi<{ items: Appointment[] }>("/admin/counseling/appointments?page_size=200"),
      canManageSchedules.value
        ? catalogApi<{ items: Schedule[] }>("/admin/counseling/availability-rules")
        : Promise.resolve({ items: [] }),
      canManageFollowups.value
        ? catalogApi<{ items: FollowUp[] }>("/admin/counseling/follow-ups")
        : Promise.resolve({ items: [] }),
    ] as const;
    const [mentorResult, serviceResult, appointmentResult, scheduleResult, followupResult] = await Promise.all(tasks);
    mentors.value = mentorResult.items;
    services.value = serviceResult.items;
    appointments.value = appointmentResult.items;
    schedules.value = scheduleResult.items;
    followups.value = followupResult.items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "辅导中心加载失败";
  } finally {
    busy.value = false;
  }
}

function reasonReady(value = actionReason.value) {
  if (value.trim().length >= 2) return true;
  error.value = "请填写操作原因，原因会进入预约历史或审计记录。";
  return false;
}

async function transition(appointment: Appointment, target_status: string) {
  if (!reasonReady() || !window.confirm(`确认把预约状态变更为“${localizeAdminValue(target_status, "status")}”？`)) return;
  busy.value = true;
  try {
    await catalogApi(`/admin/counseling/appointments/${appointment.id}/transition`, {
      method: "POST",
      body: JSON.stringify({ target_status, reason: actionReason.value.trim() }),
    });
    notice.value = "预约状态已更新并记录历史。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "预约状态变更失败";
  } finally {
    busy.value = false;
  }
}

function openReschedule(appointment: Appointment) {
  selectedAppointment.value = appointment;
  rescheduleForm.value = {
    mentor_id: appointment.mentor_id ?? mentors.value[0]?.id ?? "",
    starts_at: appointment.scheduled_starts_at?.slice(0, 16) ?? "",
    reason: "",
  };
  rescheduleOpen.value = true;
}

async function proposeTime() {
  const appointment = selectedAppointment.value;
  if (!appointment || !reasonReady(rescheduleForm.value.reason) || !rescheduleForm.value.mentor_id || !rescheduleForm.value.starts_at) return;
  busy.value = true;
  try {
    await catalogApi(`/admin/counseling/appointments/${appointment.id}/propose-time`, {
      method: "POST",
      body: JSON.stringify({
        mentor_id: rescheduleForm.value.mentor_id,
        starts_at: new Date(rescheduleForm.value.starts_at).toISOString(),
        expected_proposal_version: appointment.proposal_version,
        reason: rescheduleForm.value.reason.trim(),
      }),
    });
    rescheduleOpen.value = false;
    notice.value = "新的预约时间已提出；已确认预约会进入“等待用户确认改期”状态。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "改期失败";
  } finally {
    busy.value = false;
  }
}

async function createSchedule() {
  if (!scheduleForm.value.mentor_id) { error.value = "请选择导师。"; return; }
  busy.value = true;
  try {
    await catalogApi("/admin/counseling/availability-rules", {
      method: "POST",
      body: JSON.stringify({
        ...scheduleForm.value,
        service_id: scheduleForm.value.service_id || null,
        valid_until: scheduleForm.value.valid_until || null,
      }),
    });
    notice.value = "导师排班规则已创建。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "排班创建失败";
  } finally {
    busy.value = false;
  }
}

async function disableSchedule(schedule: Schedule) {
  if (!reasonReady() || !window.confirm("确认停用这条排班规则？已存在的预约不会被自动取消。")) return;
  await catalogApi(`/admin/counseling/availability-rules/${schedule.id}/disable`, {
    method: "POST", body: JSON.stringify({ reason: actionReason.value.trim() }),
  });
  notice.value = "排班规则已停用。";
  await load();
}

function openFollowup(appointment: Appointment) {
  selectedAppointment.value = appointment;
  followupForm.value = { follow_up_type: "action_item", content: "", due_at: "" };
  followupOpen.value = true;
}

async function createFollowup() {
  if (!selectedAppointment.value || followupForm.value.content.trim().length < 2) {
    error.value = "请填写跟进内容。"; return;
  }
  busy.value = true;
  try {
    await catalogApi(`/admin/counseling/appointments/${selectedAppointment.value.id}/follow-ups`, {
      method: "POST",
      body: JSON.stringify({
        follow_up_type: followupForm.value.follow_up_type,
        content: { summary: followupForm.value.content.trim() },
        due_at: followupForm.value.due_at ? new Date(followupForm.value.due_at).toISOString() : null,
      }),
    });
    followupOpen.value = false;
    notice.value = "跟进任务已创建并加密保存。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "跟进任务创建失败";
  } finally {
    busy.value = false;
  }
}

async function setFollowupStatus(item: FollowUp, status: "open" | "completed" | "cancelled") {
  if (!reasonReady()) return;
  await catalogApi(`/admin/counseling/follow-ups/${item.id}`, {
    method: "PATCH", body: JSON.stringify({ status, reason: actionReason.value.trim() }),
  });
  notice.value = "跟进任务状态已更新。";
  await load();
}

onMounted(() => void load());
</script>

<template>
  <section class="admin-module counseling-admin">
    <header class="module-heading">
      <div>
        <p class="admin-kicker">
          真人辅导运营闭环
        </p><h2>辅导中心</h2><p>导师排班、预约审核、改期取消、交付跟进与安全边界统一管理。</p>
      </div>
      <el-button
        :loading="busy"
        @click="load"
      >
        刷新
      </el-button>
    </header>
    <el-alert
      title="本模块不是心理治疗、医疗诊断、法律或紧急服务；录音与转写默认关闭。"
      type="warning"
      :closable="false"
      show-icon
    />
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
    />
    <el-alert
      v-if="notice"
      :title="notice"
      type="success"
      :closable="false"
      show-icon
    />
    <el-input
      v-model="actionReason"
      class="reason"
      placeholder="本次操作原因（取消、停排班、跟进结案时必填）"
    />

    <el-tabs v-model="tab">
      <el-tab-pane
        label="预约队列"
        name="appointments"
      >
        <el-table
          v-loading="busy"
          :data="appointments"
          empty-text="暂无预约"
          stripe
        >
          <el-table-column
            prop="appointment_number"
            label="预约号"
            min-width="190"
          />
          <el-table-column
            prop="status"
            label="状态"
            min-width="150"
          >
            <template #default="scope">
              {{ localizeAdminValue(scope.row.status, "status") }}
            </template>
          </el-table-column>
          <el-table-column
            label="导师"
            min-width="140"
          >
            <template #default="scope">
              {{ mentorName(scope.row.mentor_id) }}
            </template>
          </el-table-column>
          <el-table-column
            prop="scheduled_starts_at"
            label="预约开始时间（UTC+8）"
            min-width="220"
            :formatter="formatAdminTableCell"
          />
          <el-table-column
            prop="payment_status"
            label="支付状态"
            min-width="130"
          >
            <template #default="scope">
              {{ localizeAdminValue(scope.row.payment_status, "status") }}
            </template>
          </el-table-column>
          <el-table-column
            label="运营操作"
            fixed="right"
            min-width="360"
          >
            <template #default="scope">
              <el-button
                v-if="canManageAppointments && scope.row.status === 'pending_review'"
                size="small"
                @click="transition(scope.row, 'approved_pending_payment')"
              >
                批准
              </el-button>
              <el-button
                v-if="canManageAppointments && ['pending_review','manual_review'].includes(scope.row.status)"
                size="small"
                type="danger"
                @click="transition(scope.row, 'rejected')"
              >
                拒绝
              </el-button>
              <el-button
                v-if="canManageAppointments && canReschedule(scope.row.status)"
                size="small"
                @click="openReschedule(scope.row)"
              >
                改期
              </el-button>
              <el-button
                v-if="canManageAppointments && !['cancelled','completed','rejected','expired','no_show'].includes(scope.row.status)"
                size="small"
                type="danger"
                @click="transition(scope.row, 'cancelled')"
              >
                取消
              </el-button>
              <el-button
                v-if="canManageAppointments && scope.row.status === 'confirmed'"
                size="small"
                @click="transition(scope.row, 'no_show')"
              >
                标记未到
              </el-button>
              <el-button
                v-if="canManageFollowups"
                size="small"
                type="primary"
                @click="openFollowup(scope.row)"
              >
                创建跟进
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane
        v-if="canManageSchedules"
        label="导师排班"
        name="schedules"
      >
        <el-form
          class="schedule-form"
          label-position="top"
        >
          <el-form-item label="导师">
            <el-select v-model="scheduleForm.mentor_id">
              <el-option
                v-for="item in mentors"
                :key="item.id"
                :label="item.display_name"
                :value="item.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="适用服务">
            <el-select
              v-model="scheduleForm.service_id"
              clearable
            >
              <el-option
                v-for="item in services"
                :key="item.id"
                :label="item.internal_name"
                :value="item.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="时区">
            <el-input v-model="scheduleForm.timezone" />
          </el-form-item>
          <el-form-item label="星期">
            <el-select v-model="scheduleForm.weekday">
              <el-option
                v-for="(label,index) in weekdayLabels"
                :key="label"
                :label="label"
                :value="index"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="开始时间">
            <el-time-select
              v-model="scheduleForm.local_start_time"
              start="06:00"
              step="00:30"
              end="22:00"
            />
          </el-form-item>
          <el-form-item label="结束时间">
            <el-time-select
              v-model="scheduleForm.local_end_time"
              start="06:30"
              step="00:30"
              end="23:00"
            />
          </el-form-item>
          <el-form-item label="生效日期">
            <el-date-picker
              v-model="scheduleForm.valid_from"
              type="date"
              value-format="YYYY-MM-DD"
            />
          </el-form-item>
          <el-form-item label="截止日期">
            <el-date-picker
              v-model="scheduleForm.valid_until"
              type="date"
              value-format="YYYY-MM-DD"
              clearable
            />
          </el-form-item>
          <el-button
            type="primary"
            :loading="busy"
            @click="createSchedule"
          >
            新增排班规则
          </el-button>
        </el-form>
        <el-table
          :data="schedules"
          stripe
          empty-text="暂无排班"
        >
          <el-table-column
            label="导师"
            min-width="140"
          >
            <template #default="scope">
              {{ mentorName(scope.row.mentor_id) }}
            </template>
          </el-table-column>
          <el-table-column
            label="服务"
            min-width="160"
          >
            <template #default="scope">
              {{ serviceName(scope.row.service_id) }}
            </template>
          </el-table-column>
          <el-table-column
            label="星期"
            min-width="100"
          >
            <template #default="scope">
              {{ weekdayLabels[scope.row.weekday] }}
            </template>
          </el-table-column>
          <el-table-column
            label="工作时段"
            min-width="160"
          >
            <template #default="scope">
              {{ scope.row.local_start_time }}–{{ scope.row.local_end_time }}
            </template>
          </el-table-column>
          <el-table-column
            prop="timezone"
            label="时区"
            min-width="150"
          />
          <el-table-column
            prop="status"
            label="状态"
            min-width="100"
          >
            <template #default="scope">
              {{ localizeAdminValue(scope.row.status, "status") }}
            </template>
          </el-table-column>
          <el-table-column
            label="操作"
            width="100"
          >
            <template #default="scope">
              <el-button
                v-if="scope.row.status === 'active'"
                link
                type="danger"
                @click="disableSchedule(scope.row)"
              >
                停用
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane
        v-if="canManageFollowups"
        label="跟进记录"
        name="followups"
      >
        <el-table
          :data="followups"
          stripe
          empty-text="暂无跟进记录"
        >
          <el-table-column
            prop="appointment_id"
            label="预约编号"
            min-width="220"
          />
          <el-table-column
            prop="follow_up_type"
            label="跟进类型"
            min-width="130"
          >
            <template #default="scope">
              {{ localizeAdminValue(scope.row.follow_up_type, "type") }}
            </template>
          </el-table-column>
          <el-table-column
            prop="content"
            label="跟进内容"
            min-width="260"
          >
            <template #default="scope">
              {{ localizeAdminValue(scope.row.content, "content") }}
            </template>
          </el-table-column>
          <el-table-column
            prop="due_at"
            label="计划完成时间（UTC+8）"
            min-width="220"
            :formatter="formatAdminTableCell"
          />
          <el-table-column
            prop="status"
            label="状态"
            min-width="110"
          >
            <template #default="scope">
              {{ localizeAdminValue(scope.row.status, "status") }}
            </template>
          </el-table-column>
          <el-table-column
            label="操作"
            min-width="150"
          >
            <template #default="scope">
              <el-button
                v-if="scope.row.status === 'open'"
                link
                type="success"
                @click="setFollowupStatus(scope.row, 'completed')"
              >
                完成
              </el-button><el-button
                v-else
                link
                @click="setFollowupStatus(scope.row, 'open')"
              >
                重新打开
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane
        label="导师与服务"
        name="resources"
      >
        <h3>导师</h3><el-table
          :data="mentors"
          empty-text="暂无导师"
        >
          <el-table-column
            prop="mentor_code"
            label="导师代码"
          /><el-table-column
            prop="display_name"
            label="导师名称"
          /><el-table-column
            prop="timezone"
            label="时区"
          /><el-table-column
            prop="status"
            label="状态"
          >
            <template #default="scope">
              {{ localizeAdminValue(scope.row.status, "status") }}
            </template>
          </el-table-column>
        </el-table>
        <h3>服务</h3><el-table
          :data="services"
          empty-text="暂无服务"
        >
          <el-table-column
            prop="service_code"
            label="服务代码"
          /><el-table-column
            prop="internal_name"
            label="内部名称"
          /><el-table-column
            prop="booking_mode"
            label="预约模式"
          >
            <template #default="scope">
              {{ localizeAdminValue(scope.row.booking_mode, "type") }}
            </template>
          </el-table-column><el-table-column
            prop="status"
            label="状态"
          >
            <template #default="scope">
              {{ localizeAdminValue(scope.row.status, "status") }}
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="rescheduleOpen"
      title="预约改期"
      width="520px"
    >
      <el-form label-position="top">
        <el-form-item label="导师">
          <el-select v-model="rescheduleForm.mentor_id">
            <el-option
              v-for="item in mentors"
              :key="item.id"
              :label="item.display_name"
              :value="item.id"
            />
          </el-select>
        </el-form-item><el-form-item label="新的开始时间">
          <el-date-picker
            v-model="rescheduleForm.starts_at"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm"
          />
        </el-form-item><el-form-item label="改期原因">
          <el-input
            v-model="rescheduleForm.reason"
            type="textarea"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rescheduleOpen=false">
          取消
        </el-button><el-button
          type="primary"
          :loading="busy"
          @click="proposeTime"
        >
          提交改期
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="followupOpen"
      title="创建跟进任务"
      width="520px"
    >
      <el-form label-position="top">
        <el-form-item label="跟进类型">
          <el-select v-model="followupForm.follow_up_type">
            <el-option
              label="行动事项"
              value="action_item"
            /><el-option
              label="课程建议"
              value="course"
            /><el-option
              label="活动建议"
              value="activity"
            /><el-option
              label="再次辅导"
              value="counseling"
            /><el-option
              label="外部支持"
              value="external_support"
            />
          </el-select>
        </el-form-item><el-form-item label="跟进内容">
          <el-input
            v-model="followupForm.content"
            type="textarea"
            :rows="4"
          />
        </el-form-item><el-form-item label="计划完成时间">
          <el-date-picker
            v-model="followupForm.due_at"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm"
            clearable
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="followupOpen=false">
          取消
        </el-button><el-button
          type="primary"
          :loading="busy"
          @click="createFollowup"
        >
          创建
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.module-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}.reason{margin:16px 0;max-width:720px}.schedule-form{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;align-items:end;margin:16px 0}.schedule-form .el-button{margin-bottom:18px}h3{margin-top:24px}@media(max-width:1000px){.schedule-form{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:640px){.schedule-form{grid-template-columns:1fr}}
</style>
