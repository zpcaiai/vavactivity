<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { formatAdminTableCell } from "@vav/ui-admin";

import { catalogApi } from "@/features/catalog/api";

type ActivityRow = {
  id: string;
  activity_code: string;
  internal_name: string;
  status: string;
  starts_at: string;
  version: number;
};
type RegistrationRow = {
  id: string;
  registration_number: string;
  activity_id: string;
  status: string;
  attendance_status: string;
  review_status?: string | null;
};
type WaitlistRow = {
  id: string;
  sequence_number: number;
  status: string;
  promotion_offer_expires_at?: string | null;
  manual_order_override?: number | null;
};
type GroupingPlanRow = {
  id: string;
  plan_name: string;
  status: string;
  target_group_size: number;
  random_seed: string;
};
type AttendanceSummary = { confirmed: number; checked_in: number; not_checked_in: number };

const tab = ref("activities");
const activities = ref<ActivityRow[]>([]);
const registrations = ref<RegistrationRow[]>([]);
const loading = ref(false);
const error = ref("");
const selectedActivityId = ref("");
const waitlistRows = ref<WaitlistRow[]>([]);
const groupingPlans = ref<GroupingPlanRow[]>([]);
const attendance = reactive<AttendanceSummary>({ confirmed: 0, checked_in: 0, not_checked_in: 0 });
const analytics = reactive({ eligible_participants: 0, choice_submitters: 0, mutual_choices: 0 });
const checkinReference = ref("");
const checkinReason = ref("");
const grouping = reactive({ activityId: "", targetSize: 6, seed: "vav-groups-2026" });
const localization = reactive({ locale: "zh-CN", slug: "", title: "", summary: "" });
const ticket = reactive({ ticket_code: "", internal_name: "", catalog_product_id: "", catalog_sku_id: "" });
const location = reactive({ location_type: "in_person", venue_name: "", city: "", address_line_1: "", online_join_url: "" });
const createForm = reactive({
  activity_code: "",
  internal_name: "",
  activity_format: "in_person",
  starts_at: "",
  ends_at: ""
});
const pendingReviews = computed(() =>
  registrations.value.filter((item) => item.status === "pending_approval")
);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [activityResult, registrationResult] = await Promise.all([
      catalogApi<{ items: ActivityRow[] }>("/admin/activities"),
      catalogApi<{ items: RegistrationRow[] }>("/admin/activity-registrations")
    ]);
    activities.value = activityResult.items;
    registrations.value = registrationResult.items;
    if (!selectedActivityId.value && activities.value[0]) {
      selectedActivityId.value = activities.value[0].id;
      grouping.activityId = activities.value[0].id;
    }
    if (selectedActivityId.value) await loadOperations();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "活动中心加载失败";
  } finally {
    loading.value = false;
  }
}

async function loadOperations() {
  if (!selectedActivityId.value) return;
  const results = await Promise.allSettled([
    catalogApi<{ items: WaitlistRow[] }>(`/admin/activities/${selectedActivityId.value}/waitlist`),
    catalogApi<{ summary: AttendanceSummary }>(`/admin/activities/${selectedActivityId.value}/attendance`),
    catalogApi<{ items: GroupingPlanRow[] }>(`/admin/activities/${selectedActivityId.value}/grouping-plans`),
    catalogApi<typeof analytics>(`/admin/activities/${selectedActivityId.value}/post-event/analytics`)
  ]);
  if (results[0].status === "fulfilled") waitlistRows.value = results[0].value.items;
  if (results[1].status === "fulfilled") Object.assign(attendance, results[1].value.summary);
  if (results[2].status === "fulfilled") groupingPlans.value = results[2].value.items;
  if (results[3].status === "fulfilled") Object.assign(analytics, results[3].value);
}

async function createActivity() {
  try {
    await catalogApi("/admin/activities", {
      method: "POST",
      body: JSON.stringify({
        ...createForm,
        starts_at: new Date(createForm.starts_at).toISOString(),
        ends_at: new Date(createForm.ends_at).toISOString(),
        default_locale: "zh-CN",
        timezone: "Asia/Shanghai",
        approval_policy: "automatic",
        payment_timing_policy: "before_approval",
        waitlist_enabled: true,
        post_event_choice_enabled: false
      })
    });
    Object.assign(createForm, {
      activity_code: "",
      internal_name: "",
      activity_format: "in_person",
      starts_at: "",
      ends_at: ""
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "创建失败";
  }
}

async function review(registration: RegistrationRow, action: "approve" | "reject") {
  try {
    await catalogApi(`/admin/activity-registrations/${registration.id}/review`, {
      method: "POST",
      body: JSON.stringify({
        action,
        reason_code: `operator_${action}`,
        user_message: action === "approve" ? "报名审核通过" : "报名暂未通过",
        private_notes: "Reviewed in activity operations center."
      })
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "审核失败";
  }
}

async function transition(activity: ActivityRow, target: string) {
  try {
    await catalogApi(`/admin/activities/${activity.id}/transition`, {
      method: "POST",
      body: JSON.stringify({ target_status: target, reason: `Operator moved activity to ${target}.` })
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "状态变更失败";
  }
}

async function saveLocalization() {
  try {
    await catalogApi(
      `/admin/activities/${selectedActivityId.value}/localizations/${localization.locale}`,
      {
        method: "PUT",
        body: JSON.stringify({
          ...localization,
          description_blocks: [],
          participation_notes: [],
          translation_status: "ready"
        })
      }
    );
    Object.assign(localization, { slug: "", title: "", summary: "" });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "多语言内容保存失败";
  }
}

async function linkTicket() {
  try {
    await catalogApi(`/admin/activities/${selectedActivityId.value}/tickets`, {
      method: "POST",
      body: JSON.stringify({ ...ticket, status: "active", waitlist_enabled: true })
    });
    Object.assign(ticket, { ticket_code: "", internal_name: "", catalog_product_id: "", catalog_sku_id: "" });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "票种关联失败";
  }
}

async function addLocation() {
  try {
    await catalogApi(`/admin/activities/${selectedActivityId.value}/locations`, {
      method: "POST",
      body: JSON.stringify({ ...location, public_address_precision: "city_only" })
    });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "地点配置失败";
  }
}

async function checkin() {
  try {
    await catalogApi("/admin/activity-checkins", {
      method: "POST",
      body: JSON.stringify({
        registration_number: checkinReference.value,
        action: "check_in",
        device_reference: "admin-web"
      })
    });
    checkinReference.value = "";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "签到失败";
  }
}

async function revokeCheckin(registration: RegistrationRow) {
  if (!checkinReason.value) {
    error.value = "撤销签到必须填写原因";
    return;
  }
  try {
    await catalogApi("/admin/activity-checkins", {
      method: "POST",
      body: JSON.stringify({
        registration_number: registration.registration_number,
        action: "revoke",
        reason: checkinReason.value,
        device_reference: "admin-web"
      })
    });
    checkinReason.value = "";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "撤销签到失败";
  }
}

async function reorderWaitlist(entry: WaitlistRow) {
  try {
    await catalogApi(`/admin/activity-waitlist/${entry.id}/reorder`, {
      method: "POST",
      body: JSON.stringify({
        manual_order_override: entry.manual_order_override ?? entry.sequence_number,
        reason_code: "operator_reorder",
        reason: "Operator adjusted waitlist order from the activity center."
      })
    });
    await loadOperations();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "候补调序失败";
  }
}

async function createGroups() {
  try {
    await catalogApi(`/admin/activities/${grouping.activityId}/grouping-plans`, {
      method: "POST",
      body: JSON.stringify({
        plan_name: `分组 ${new Date().toLocaleDateString()}`,
        target_group_size: grouping.targetSize,
        seed: grouping.seed,
        checked_in_only: true,
        publish: false
      })
    });
    await loadOperations();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "分组失败";
  }
}

async function setGroupingLock(plan: GroupingPlanRow, locked: boolean) {
  try {
    await catalogApi(`/admin/activity-grouping-plans/${plan.id}/${locked ? "lock" : "unlock"}`, {
      method: "POST",
      body: JSON.stringify({ reason: locked ? "Grouping approved for operations." : "Grouping reopened for an audited adjustment." })
    });
    await loadOperations();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "分组状态变更失败";
  }
}

onMounted(() => void load());
</script>

<template>
  <section v-loading="loading">
    <header class="page-toolbar">
      <div>
        <p class="admin-kicker">
          活动运营
        </p>
        <h2>活动中心</h2>
        <p>活动只关联 Catalog 票种；支付、名额与权益仍由 Commerce/Catalog 权威处理。</p>
      </div>
      <el-tag type="warning">
        单向互选严格保密，不自动披露联系方式
      </el-tag>
    </header>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
    />
    <el-form-item label="当前运营活动">
      <el-select
        v-model="selectedActivityId"
        @change="loadOperations"
      >
        <el-option
          v-for="activity in activities"
          :key="activity.id"
          :label="`${activity.internal_name} · ${activity.status}`"
          :value="activity.id"
        />
      </el-select>
    </el-form-item>
    <el-tabs v-model="tab">
      <el-tab-pane
        label="活动发布"
        name="activities"
      >
        <el-form
          :model="createForm"
          label-position="top"
          class="editor-grid"
        >
          <el-form-item label="活动代码">
            <el-input v-model="createForm.activity_code" />
          </el-form-item>
          <el-form-item label="内部名称">
            <el-input v-model="createForm.internal_name" />
          </el-form-item>
          <el-form-item label="形式">
            <el-select v-model="createForm.activity_format">
              <el-option
                label="线下"
                value="in_person"
              />
              <el-option
                label="线上"
                value="online"
              />
              <el-option
                label="混合"
                value="hybrid"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="开始">
            <el-input
              v-model="createForm.starts_at"
              type="datetime-local"
            />
          </el-form-item>
          <el-form-item label="结束">
            <el-input
              v-model="createForm.ends_at"
              type="datetime-local"
            />
          </el-form-item>
          <el-button
            type="primary"
            @click="createActivity"
          >
            创建草稿
          </el-button>
        </el-form>
        <el-table
          :data="activities"
          stripe
        >
          <el-table-column
            prop="activity_code"
            label="代码"
          />
          <el-table-column
            prop="internal_name"
            label="名称"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
          <el-table-column
            prop="starts_at"
            :formatter="formatAdminTableCell"
            label="开始时间（UTC+8）"
          />
          <el-table-column label="生命周期操作">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'draft'"
                size="small"
                @click="transition(row, 'in_review')"
              >
                提交审核
              </el-button>
              <el-button
                v-if="row.status === 'in_review'"
                size="small"
                type="primary"
                @click="transition(row, 'published')"
              >
                发布
              </el-button>
              <el-button
                v-if="row.status === 'published'"
                size="small"
                @click="transition(row, 'registration_open')"
              >
                开放报名
              </el-button>
              <el-button
                v-if="row.status === 'registration_open'"
                size="small"
                @click="transition(row, 'registration_closed')"
              >
                关闭报名
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        label="内容、地点与票种"
        name="configuration"
      >
        <h3>多语言活动内容</h3>
        <el-form
          :model="localization"
          label-position="top"
          class="editor-grid"
        >
          <el-form-item label="语言">
            <el-select v-model="localization.locale">
              <el-option
                label="简体中文"
                value="zh-CN"
              />
              <el-option
                label="繁體中文"
                value="zh-TW"
              />
              <el-option
                label="英文"
                value="en"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="URL 短标识">
            <el-input v-model="localization.slug" />
          </el-form-item>
          <el-form-item label="标题">
            <el-input v-model="localization.title" />
          </el-form-item>
          <el-form-item label="摘要">
            <el-input
              v-model="localization.summary"
              type="textarea"
            />
          </el-form-item>
          <el-button
            type="primary"
            @click="saveLocalization"
          >
            保存并标记翻译就绪
          </el-button>
        </el-form>

        <h3>私密地点或会议配置</h3>
        <el-form
          :model="location"
          label-position="top"
          class="editor-grid"
        >
          <el-form-item label="类型">
            <el-select v-model="location.location_type">
              <el-option
                label="线下"
                value="in_person"
              />
              <el-option
                label="线上"
                value="online"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="场地名称">
            <el-input v-model="location.venue_name" />
          </el-form-item>
          <el-form-item label="城市">
            <el-input v-model="location.city" />
          </el-form-item>
          <el-form-item label="完整地址（加密）">
            <el-input v-model="location.address_line_1" />
          </el-form-item>
          <el-form-item label="会议链接（加密）">
            <el-input v-model="location.online_join_url" />
          </el-form-item>
          <el-button
            type="primary"
            @click="addLocation"
          >
            新增地点配置
          </el-button>
        </el-form>

        <h3>Catalog 票种关联</h3>
        <p>价格、促销和有限名额仍由 Catalog SKU 权威维护。</p>
        <el-form
          :model="ticket"
          label-position="top"
          class="editor-grid"
        >
          <el-form-item label="票种代码">
            <el-input v-model="ticket.ticket_code" />
          </el-form-item>
          <el-form-item label="内部名称">
            <el-input v-model="ticket.internal_name" />
          </el-form-item>
          <el-form-item label="商品唯一标识">
            <el-input v-model="ticket.catalog_product_id" />
          </el-form-item>
          <el-form-item label="SKU 唯一标识">
            <el-input v-model="ticket.catalog_sku_id" />
          </el-form-item>
          <el-button
            type="primary"
            @click="linkTicket"
          >
            关联票种
          </el-button>
        </el-form>
      </el-tab-pane>
      <el-tab-pane
        :label="`报名审核 (${pendingReviews.length})`"
        name="registrations"
      >
        <el-table
          :data="registrations"
          stripe
        >
          <el-table-column
            prop="registration_number"
            label="报名编号"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
          <el-table-column
            prop="attendance_status"
            label="签到"
          />
          <el-table-column label="操作">
            <template #default="{ row }">
              <template v-if="row.status === 'pending_approval'">
                <el-button
                  size="small"
                  type="primary"
                  @click="review(row, 'approve')"
                >
                  通过
                </el-button>
                <el-button
                  size="small"
                  @click="review(row, 'reject')"
                >
                  拒绝
                </el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        :label="`候补 (${waitlistRows.length})`"
        name="waitlist"
      >
        <el-table
          :data="waitlistRows"
          stripe
        >
          <el-table-column
            prop="sequence_number"
            label="原始顺序"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
          <el-table-column
            prop="promotion_offer_expires_at"
            :formatter="formatAdminTableCell"
            label="邀请到期（UTC+8）"
          />
          <el-table-column label="人工顺序">
            <template #default="{ row }">
              <el-input-number
                v-model="row.manual_order_override"
                :min="1"
              />
              <el-button
                size="small"
                @click="reorderWaitlist(row)"
              >
                保存有因调序
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        label="签到"
        name="checkin"
      >
        <p>
          已确认 {{ attendance.confirmed }} · 已签到 {{ attendance.checked_in }} · 未签到
          {{ attendance.not_checked_in }}
        </p>
        <el-form
          inline
          @submit.prevent="checkin"
        >
          <el-form-item label="报名编号">
            <el-input
              v-model="checkinReference"
              placeholder="REG-..."
            />
          </el-form-item>
          <el-button
            type="primary"
            @click="checkin"
          >
            手工签到
          </el-button>
        </el-form>
        <el-input
          v-model="checkinReason"
          placeholder="撤销签到原因（必填）"
        />
        <el-table
          :data="registrations.filter((row) => row.status === 'confirmed')"
          stripe
        >
          <el-table-column
            prop="registration_number"
            label="报名号"
          />
          <el-table-column
            prop="attendance_status"
            label="到场状态"
          />
          <el-table-column label="操作">
            <template #default="{ row }">
              <el-button
                v-if="row.attendance_status === 'checked_in'"
                size="small"
                type="danger"
                @click="revokeCheckin(row)"
              >
                追加撤销事件
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        label="分组"
        name="grouping"
      >
        <el-form
          :model="grouping"
          label-position="top"
        >
          <el-form-item label="活动">
            <el-select v-model="grouping.activityId">
              <el-option
                v-for="activity in activities"
                :key="activity.id"
                :label="activity.internal_name"
                :value="activity.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="每组人数">
            <el-input-number
              v-model="grouping.targetSize"
              :min="2"
            />
          </el-form-item>
          <el-form-item label="可复现随机种子">
            <el-input v-model="grouping.seed" />
          </el-form-item>
          <el-button
            type="primary"
            @click="createGroups"
          >
            生成签到人员分组草稿
          </el-button>
        </el-form>
        <el-table
          :data="groupingPlans"
          stripe
        >
          <el-table-column
            prop="plan_name"
            label="方案"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
          <el-table-column
            prop="random_seed"
            label="固定随机种子"
          />
          <el-table-column label="操作">
            <template #default="{ row }">
              <el-button
                v-if="row.status !== 'locked'"
                size="small"
                @click="setGroupingLock(row, true)"
              >
                锁定
              </el-button>
              <el-button
                v-else
                size="small"
                @click="setGroupingLock(row, false)"
              >
                审计解锁
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        label="活动后互选"
        name="post-event"
      >
        <el-descriptions
          border
          :column="3"
        >
          <el-descriptions-item label="合格参与者">
            {{ analytics.eligible_participants }}
          </el-descriptions-item>
          <el-descriptions-item label="已提交选择">
            {{ analytics.choice_submitters }}
          </el-descriptions-item>
          <el-descriptions-item label="双向互选">
            {{ analytics.mutual_choices }}
          </el-descriptions-item>
        </el-descriptions>
        <el-alert
          title="默认只展示聚合指标；单向选择明细需独立高风险权限，且不得用于普通运营浏览。"
          type="warning"
          :closable="false"
        />
      </el-tab-pane>
    </el-tabs>
  </section>
</template>
