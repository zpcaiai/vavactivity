<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  datingProfileApi,
  type Completeness,
  type DatingProfile,
  type FieldDefinition,
  type PreferenceState,
  type PrivacyState,
  type ProfilePhoto,
  type ProfileSchema,
  type ReviewFeedback,
  type ViewProjection
} from "@/features/dating-profile/api";

type StepKey =
  | "basic"
  | "faith"
  | "history"
  | "family"
  | "lifestyle"
  | "narratives"
  | "photos"
  | "preferences"
  | "privacy"
  | "preview"
  | "review";

const STEPS: { key: StepKey; label: string; sections: string[] }[] = [
  { key: "basic", label: "基本资料", sections: ["basic", "location", "education_and_work"] },
  { key: "faith", label: "信仰", sections: ["faith"] },
  { key: "history", label: "婚史", sections: ["relationship_history"] },
  { key: "family", label: "家庭", sections: ["family", "children_and_parenting"] },
  { key: "lifestyle", label: "生活方式", sections: ["lifestyle", "interests", "communication"] },
  { key: "narratives", label: "自我介绍", sections: [] },
  { key: "photos", label: "照片", sections: [] },
  { key: "preferences", label: "择偶条件", sections: [] },
  { key: "privacy", label: "隐私设置", sections: [] },
  { key: "preview", label: "档案预览", sections: [] },
  { key: "review", label: "提交审核", sections: [] }
];

const NARRATIVE_FIELDS: { key: string; label: string; hint: string }[] = [
  { key: "self_introduction", label: "自我介绍", hint: "至少 80 字。请勿填写联系方式。" },
  { key: "faith_journey", label: "信仰经历", hint: "可选。" },
  { key: "relationship_values", label: "关系价值观", hint: "可选。" },
  { key: "marriage_vision", label: "婚姻愿景", hint: "可选。" },
  { key: "family_vision", label: "家庭愿景", hint: "可选。" },
  { key: "strengths_and_growth", label: "优势与成长", hint: "可选。" },
  { key: "interests_and_lifestyle", label: "兴趣生活", hint: "可选。" },
  { key: "hoped_for_relationship", label: "希望认识怎样的人", hint: "可选。" }
];

const PREVIEW_CONTEXTS = [
  { value: "recommendation_card", label: "推荐卡片" },
  { value: "profile_detail", label: "档案详情" },
  { value: "activity_directory", label: "活动目录" },
  { value: "mutual_match", label: "互选之后" }
];

const VISIBILITY_OPTIONS = [
  { value: "private", label: "仅自己可见" },
  { value: "mutual_only", label: "互选后可见" },
  { value: "verified_members", label: "已验证会员可见" }
];

const route = useRoute();
const busy = ref(false);
const error = ref("");
const notice = ref("");
const step = ref<StepKey>("basic");

const profile = ref<DatingProfile>();
const schema = ref<ProfileSchema>();
const completeness = ref<Completeness>();
const photos = ref<ProfilePhoto[]>([]);
const preferences = ref<PreferenceState>();
const privacy = ref<PrivacyState>();
const feedback = ref<ReviewFeedback>();
const previewContext = ref("profile_detail");
const preview = ref<ViewProjection>();

const fieldValues = reactive<Record<string, unknown>>({});
const narrativeValues = reactive<Record<string, string>>({});
const aiAssisted = ref(false);
const aiConfirmed = ref(false);
const changeSummary = ref("完成建档并提交审核。");

const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const currentStep = computed(() => STEPS.find((item) => item.key === step.value) ?? STEPS[0]);
const completionPercent = computed(() =>
  Math.round((completeness.value?.total_basis_points ?? 0) / 100)
);
const missingRequired = computed(() => completeness.value?.missing_required_fields ?? []);
const canSubmit = computed(() => completeness.value?.submission_eligible === true);

const stepFields = computed<FieldDefinition[]>(() => {
  const sections = currentStep.value.sections;
  if (!schema.value || sections.length === 0) return [];
  return schema.value.fields
    .filter((field) => sections.includes(field.section_code))
    .sort((a, b) => b.weight - a.weight);
});

function taxonomyFor(field: FieldDefinition) {
  const code = field.value_schema.taxonomy as string | undefined;
  if (!code || !schema.value) return [];
  return (schema.value.taxonomies[code]?.values ?? []).filter((value) => value.enabled);
}

function isMissing(fieldCode: string) {
  return missingRequired.value.includes(fieldCode);
}

function textValue(fieldCode: string): string {
  const value = fieldValues[fieldCode];
  return typeof value === "string" ? value : "";
}

function setText(fieldCode: string, event: Event) {
  fieldValues[fieldCode] = (event.target as HTMLInputElement | HTMLTextAreaElement).value;
}

function labelFor(field: FieldDefinition) {
  return field.field_code.split(".").slice(1).join(".");
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    const current = await datingProfileApi.get();
    profile.value = current;
    if (!current.exists) return;
    const [schemaValue, completenessValue, photoValue, preferenceValue, privacyValue, feedbackValue] =
      await Promise.all([
        datingProfileApi.schema(locale.value),
        datingProfileApi.completeness(),
        datingProfileApi.photos(),
        datingProfileApi.preferences(),
        datingProfileApi.privacy(),
        datingProfileApi.reviewFeedback()
      ]);
    schema.value = schemaValue;
    completeness.value = completenessValue;
    photos.value = photoValue.items;
    preferences.value = preferenceValue;
    privacy.value = privacyValue;
    feedback.value = feedbackValue;
    const visible = current.projection?.visible_fields ?? {};
    for (const [key, value] of Object.entries(visible)) fieldValues[key] = value;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "婚恋档案加载失败";
  } finally {
    busy.value = false;
  }
}

async function createProfile() {
  error.value = "";
  try {
    await datingProfileApi.create(locale.value);
    notice.value = "婚恋档案已创建，默认使用严格隐私模式。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "创建失败";
  }
}

async function saveStep() {
  error.value = "";
  notice.value = "";
  try {
    const payload: Record<string, unknown> = {};
    for (const field of stepFields.value) {
      const value = fieldValues[field.field_code];
      if (value !== undefined) payload[field.field_code] = value;
    }
    if (Object.keys(payload).length > 0) {
      completeness.value = await datingProfileApi.patchFields(payload, profile.value?.version);
    }
    notice.value = "本节内容已保存，完整度由后端重新计算。";
    await refreshProfile();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "保存失败";
  }
}

async function saveNarratives() {
  error.value = "";
  try {
    completeness.value = await datingProfileApi.putNarratives({
      locale: locale.value,
      ...narrativeValues,
      ai_assisted: aiAssisted.value,
      ai_content_confirmed: aiConfirmed.value
    });
    notice.value = "叙述已保存并进入内容审核。";
    await refreshProfile();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "叙述保存失败";
  }
}

async function uploadPhoto(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  error.value = "";
  try {
    const buffer = await file.arrayBuffer();
    let binary = "";
    const bytes = new Uint8Array(buffer);
    for (let index = 0; index < bytes.byteLength; index += 1) {
      binary += String.fromCharCode(bytes[index]);
    }
    const result = await datingProfileApi.uploadPhoto({
      filename: file.name,
      mime_type: file.type,
      content_base64: btoa(binary),
      photo_role: photos.value.some((photo) => photo.photo_role === "primary") ? "gallery" : "primary"
    });
    notice.value = result.exif_removed
      ? "照片已上传，EXIF 已清除，等待人工审核。"
      : "照片已上传，等待人工审核。";
    photos.value = (await datingProfileApi.photos()).items;
    await refreshProfile();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "照片上传失败";
  } finally {
    input.value = "";
  }
}

async function makePrimary(photoId: string) {
  await datingProfileApi.makePrimary(photoId);
  photos.value = (await datingProfileApi.photos()).items;
  notice.value = "主照片已更新。";
}

async function removePhoto(photoId: string) {
  await datingProfileApi.deletePhoto(photoId);
  photos.value = (await datingProfileApi.photos()).items;
  notice.value = "照片已删除，相关访问链接立即失效。";
  await refreshProfile();
}

async function savePreferences() {
  if (!preferences.value) return;
  error.value = "";
  try {
    preferences.value = await datingProfileApi.savePreferences(
      preferences.value.criteria,
      preferences.value.allow_recommendation_relaxation
    );
    notice.value = "择偶条件已保存，仅你本人和推荐引擎可见。";
    await refreshProfile();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "择偶条件保存失败";
  }
}

async function savePrivacy() {
  if (!privacy.value) return;
  error.value = "";
  try {
    const rules = Object.entries(privacy.value.field_visibility).map(([field_code, visibility]) => ({
      field_code,
      visibility
    }));
    await datingProfileApi.savePrivacy(rules, privacy.value.visible_in_matchmaking);
    notice.value = "隐私设置已保存，推荐投影会立即重建。";
    await refreshProfile();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "隐私设置保存失败";
  }
}

async function loadPreview() {
  error.value = "";
  try {
    preview.value = (await datingProfileApi.preview(previewContext.value)).preview;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "预览失败";
  }
}

async function submitForReview() {
  error.value = "";
  try {
    const result = await datingProfileApi.submit(changeSummary.value);
    notice.value = `第 ${result.version_number} 版已提交审核，该版本不可再修改。`;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "提交失败";
  }
}

async function pause() {
  await datingProfileApi.pause();
  notice.value = "档案已暂停，已退出推荐池。";
  await refreshProfile();
}

async function reactivate() {
  await datingProfileApi.reactivate();
  notice.value = "档案已重新启用。";
  await refreshProfile();
}

async function refreshProfile() {
  profile.value = await datingProfileApi.get();
  completeness.value = await datingProfileApi.completeness();
}

onMounted(() => void load());
watch(previewContext, () => {
  if (step.value === "preview") void loadPreview();
});
watch(step, (value) => {
  notice.value = "";
  if (value === "preview") void loadPreview();
});
</script>

<template>
  <section class="dating-profile">
    <p class="eyebrow">
      BATCH 13 · DATING PROFILE
    </p>
    <h1>婚恋档案</h1>
    <p class="intro">
      档案默认使用严格隐私模式。联系方式在任何场景下都不会自动公开，
      完整度只反映资料填写情况，不代表任何个人评价。
    </p>

    <p
      v-if="error"
      class="alert error"
      role="alert"
    >
      {{ error }}
    </p>
    <p
      v-if="notice"
      class="alert notice"
      role="status"
    >
      {{ notice }}
    </p>

    <div
      v-if="profile && !profile.exists"
      class="empty-state"
    >
      <h2>还没有婚恋档案</h2>
      <p>创建后即可分步填写，随时暂存退出。年龄由后端根据受保护的出生日期计算。</p>
      <button
        type="button"
        class="primary"
        @click="createProfile"
      >
        创建婚恋档案
      </button>
    </div>

    <template v-else-if="profile?.exists">
      <div class="status-bar">
        <span class="chip">档案编号 {{ profile.profile_number }}</span>
        <span class="chip">状态 {{ profile.status }}</span>
        <span class="chip">审核 {{ profile.review_status }}</span>
        <span
          v-if="profile.approved_version_number"
          class="chip"
        >
          展示版本 v{{ profile.approved_version_number }}
        </span>
      </div>

      <div class="completeness">
        <div class="bar">
          <div
            class="fill"
            :style="{ width: `${completionPercent}%` }"
          />
        </div>
        <p>
          资料完整度 {{ completionPercent }}%（仅衡量填写完成度）
          <span v-if="missingRequired.length">· 还有 {{ missingRequired.length }} 个必填项</span>
        </p>
      </div>

      <nav
        class="stepper"
        aria-label="建档步骤"
      >
        <button
          v-for="item in STEPS"
          :key="item.key"
          type="button"
          :class="{ active: step === item.key }"
          @click="step = item.key"
        >
          {{ item.label }}
        </button>
      </nav>

      <!-- Structured field sections -->
      <form
        v-if="stepFields.length"
        class="panel"
        @submit.prevent="saveStep"
      >
        <h2>{{ currentStep.label }}</h2>
        <div
          v-for="field in stepFields"
          :key="field.field_code"
          class="field"
        >
          <label :for="field.field_code">
            {{ labelFor(field) }}
            <span
              v-if="field.required_for_submission"
              class="required"
            >必填</span>
            <span class="sensitivity">{{ field.sensitivity }}</span>
          </label>

          <select
            v-if="field.field_type === 'enum' && taxonomyFor(field).length"
            :id="field.field_code"
            v-model="fieldValues[field.field_code]"
          >
            <option value="">
              未填写
            </option>
            <option
              v-for="value in taxonomyFor(field)"
              :key="value.code"
              :value="value.code"
            >
              {{ value.label }}
            </option>
          </select>

          <select
            v-else-if="field.field_type === 'enum_set'"
            :id="field.field_code"
            v-model="fieldValues[field.field_code]"
            multiple
          >
            <option
              v-for="value in taxonomyFor(field)"
              :key="value.code"
              :value="value.code"
            >
              {{ value.label }}
            </option>
          </select>

          <input
            v-else-if="field.field_type === 'boolean'"
            :id="field.field_code"
            v-model="fieldValues[field.field_code]"
            type="checkbox"
          >

          <input
            v-else-if="field.field_type === 'integer' || field.field_type === 'scale'"
            :id="field.field_code"
            v-model.number="fieldValues[field.field_code]"
            type="number"
          >

          <textarea
            v-else-if="field.field_type === 'encrypted_text'"
            :id="field.field_code"
            :value="textValue(field.field_code)"
            rows="3"
            @input="setText(field.field_code, $event)"
          />

          <input
            v-else
            :id="field.field_code"
            :value="textValue(field.field_code)"
            type="text"
            @input="setText(field.field_code, $event)"
          >

          <p
            v-if="isMissing(field.field_code)"
            class="hint missing"
          >
            此项为提交审核的必填内容。
          </p>
        </div>
        <button
          type="submit"
          class="primary"
        >
          保存本节
        </button>
      </form>

      <!-- Narratives -->
      <form
        v-else-if="step === 'narratives'"
        class="panel"
        @submit.prevent="saveNarratives"
      >
        <h2>自我介绍与叙述</h2>
        <p class="hint">
          请勿在文字中填写电话、邮箱、微信或站外链接，这类内容会被拒绝。
        </p>
        <div
          v-for="item in NARRATIVE_FIELDS"
          :key="item.key"
          class="field"
        >
          <label :for="item.key">{{ item.label }}</label>
          <textarea
            :id="item.key"
            v-model="narrativeValues[item.key]"
            rows="4"
          />
          <p class="hint">
            {{ item.hint }}
          </p>
        </div>
        <label class="inline">
          <input
            v-model="aiAssisted"
            type="checkbox"
          > 使用了 AI 辅助润色
        </label>
        <label
          v-if="aiAssisted"
          class="inline"
        >
          <input
            v-model="aiConfirmed"
            type="checkbox"
          >
          我确认以上内容属实，并同意作为我本人的陈述保存
        </label>
        <button
          type="submit"
          class="primary"
        >
          保存叙述
        </button>
      </form>

      <!-- Photos -->
      <section
        v-else-if="step === 'photos'"
        class="panel"
      >
        <h2>照片</h2>
        <p class="hint">
          照片以私有方式存储，上传后自动清除 EXIF 并重新编码，需经人工审核才会对他人展示。
          平台不进行人脸识别，也不建立生物特征模板。
        </p>
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          @change="uploadPhoto"
        >
        <ul class="photo-list">
          <li
            v-for="photo in photos"
            :key="photo.photo_id"
          >
            <span class="chip">{{ photo.photo_role === 'primary' ? '主照片' : '相册' }}</span>
            <span class="chip">{{ photo.status }}</span>
            <span
              v-if="photo.rejection_message_safe"
              class="hint missing"
            >
              {{ photo.rejection_message_safe }}
            </span>
            <button
              v-if="photo.photo_role !== 'primary'"
              type="button"
              @click="makePrimary(photo.photo_id)"
            >
              设为主照片
            </button>
            <button
              type="button"
              class="danger"
              @click="removePhoto(photo.photo_id)"
            >
              删除
            </button>
          </li>
        </ul>
      </section>

      <!-- Preferences -->
      <section
        v-else-if="step === 'preferences' && preferences"
        class="panel"
      >
        <h2>择偶条件</h2>
        <p class="hint">
          标记为“硬性条件”的项目会直接排除不符合的候选人。系统不会在未获授权时自动放宽这些条件，
          也不会从你的叙述文字中推断隐藏偏好。
        </p>
        <ul class="criteria">
          <li
            v-for="criterion in preferences.criteria"
            :key="criterion.criterion_code"
          >
            <strong>{{ criterion.criterion_code }}</strong>
            <span class="chip">{{ criterion.operator }}</span>
            <span class="chip">{{ criterion.importance }}</span>
            <span
              v-if="criterion.hard_constraint"
              class="chip danger"
            >硬性条件</span>
            <code>{{ JSON.stringify(criterion.desired_value) }}</code>
          </li>
        </ul>
        <p
          v-if="preferences.hard_constraints.length"
          class="hint missing"
        >
          以下条件会造成硬性排除：
          {{ preferences.hard_constraints.map((item) => item.criterion_code).join('、') }}
        </p>
        <label class="inline">
          <input
            v-model="preferences.allow_recommendation_relaxation"
            type="checkbox"
          >
          允许系统在候选人不足时适度放宽非硬性条件
        </label>
        <button
          type="button"
          class="primary"
          @click="savePreferences"
        >
          保存择偶条件
        </button>
      </section>

      <!-- Privacy -->
      <section
        v-else-if="step === 'privacy' && privacy"
        class="panel"
      >
        <h2>字段隐私</h2>
        <p class="hint">
          可见性由后端在每次查询时判定，前端不会先取到完整档案再隐藏。
          联系方式在任何场景都不会自动公开。
        </p>
        <label class="inline">
          <input
            v-model="privacy.visible_in_matchmaking"
            type="checkbox"
          >
          允许我的档案进入推荐池
        </label>
        <div
          v-for="(value, field) in privacy.field_visibility"
          :key="field"
          class="field"
        >
          <label :for="`visibility-${field}`">{{ field }}</label>
          <select
            :id="`visibility-${field}`"
            v-model="privacy.field_visibility[field]"
          >
            <option
              v-for="option in VISIBILITY_OPTIONS"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </option>
          </select>
        </div>
        <button
          type="button"
          class="primary"
          @click="savePrivacy"
        >
          保存隐私设置
        </button>
      </section>

      <!-- Preview -->
      <section
        v-else-if="step === 'preview'"
        class="panel"
      >
        <h2>档案预览</h2>
        <label for="preview-context">查看场景</label>
        <select
          id="preview-context"
          v-model="previewContext"
        >
          <option
            v-for="item in PREVIEW_CONTEXTS"
            :key="item.value"
            :value="item.value"
          >
            {{ item.label }}
          </option>
        </select>
        <div
          v-if="preview"
          class="preview-card"
        >
          <h3>{{ preview.display_name }}</h3>
          <p>{{ preview.age_display ?? '年龄未展示' }} · {{ preview.city_display ?? '城市未展示' }}</p>
          <p>{{ preview.self_introduction ?? '此场景不展示自我介绍。' }}</p>
          <p class="hint">
            此场景共展示 {{ Object.keys(preview.visible_fields).length }} 个字段，
            隐藏 {{ preview.withheld_field_count }} 个字段。联系方式：
            {{ preview.contact_details_available ? '可见' : '不可见' }}。
          </p>
        </div>
      </section>

      <!-- Review -->
      <section
        v-else-if="step === 'review'"
        class="panel"
      >
        <h2>提交审核</h2>
        <p
          v-if="missingRequired.length"
          class="hint missing"
        >
          还有必填项未完成：{{ missingRequired.join('、') }}
        </p>
        <div
          v-if="feedback?.has_feedback"
          class="feedback"
        >
          <h3>审核反馈</h3>
          <p>{{ feedback.message }}</p>
          <ul>
            <li
              v-for="(item, index) in feedback.items"
              :key="index"
            >
              {{ item.field_code ?? '照片' }} · {{ item.decision }}
              <span v-if="item.user_message_safe">— {{ item.user_message_safe }}</span>
            </li>
          </ul>
        </div>
        <label for="change-summary">本次修改说明</label>
        <textarea
          id="change-summary"
          v-model="changeSummary"
          rows="3"
        />
        <button
          type="button"
          class="primary"
          :disabled="!canSubmit"
          @click="submitForReview"
        >
          提交审核
        </button>
        <div class="lifecycle">
          <button
            type="button"
            @click="pause"
          >
            暂停档案
          </button>
          <button
            type="button"
            @click="reactivate"
          >
            恢复档案
          </button>
        </div>
        <p class="hint">
          提交后该版本不可修改。审核期间继续编辑会创建新的草稿版本，
          已批准的版本会继续对外展示。
        </p>
      </section>
    </template>

    <p v-else-if="busy">
      正在加载婚恋档案…
    </p>
  </section>
</template>

<style scoped>
.dating-profile { display: flex; flex-direction: column; gap: 1.25rem; padding: 2rem 0; }
.eyebrow { letter-spacing: 0.18em; font-size: 0.75rem; opacity: 0.7; }
.intro { max-width: 62ch; line-height: 1.7; }
.alert { padding: 0.75rem 1rem; border-radius: 0.5rem; }
.alert.error { background: #fdecea; color: #8a1c12; }
.alert.notice { background: #eaf6ec; color: #1c5a2a; }
.empty-state { padding: 2rem; border: 1px dashed currentColor; border-radius: 0.75rem; }
.status-bar { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.chip { padding: 0.15rem 0.6rem; border-radius: 999px; background: rgba(0, 0, 0, 0.06); font-size: 0.8rem; }
.chip.danger { background: #fdecea; color: #8a1c12; }
.completeness .bar { height: 0.5rem; background: rgba(0, 0, 0, 0.08); border-radius: 999px; overflow: hidden; }
.completeness .fill { height: 100%; background: #3f7d58; transition: width 0.3s ease; }
.stepper { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.stepper button { padding: 0.4rem 0.9rem; border-radius: 999px; border: 1px solid rgba(0, 0, 0, 0.15); background: transparent; cursor: pointer; }
.stepper button.active { background: #1f2933; color: #fff; }
.panel { display: flex; flex-direction: column; gap: 1rem; padding: 1.5rem; border: 1px solid rgba(0, 0, 0, 0.1); border-radius: 0.75rem; }
.field { display: flex; flex-direction: column; gap: 0.35rem; }
.field label { font-weight: 600; display: flex; gap: 0.5rem; align-items: center; }
.required { font-size: 0.7rem; color: #8a1c12; }
.sensitivity { font-size: 0.7rem; opacity: 0.6; }
.hint { font-size: 0.85rem; opacity: 0.75; }
.hint.missing { color: #8a1c12; opacity: 1; }
.inline { display: flex; align-items: center; gap: 0.5rem; font-weight: 500; }
.photo-list, .criteria { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.photo-list li, .criteria li { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
.preview-card { padding: 1rem; border: 1px solid rgba(0, 0, 0, 0.12); border-radius: 0.5rem; }
.lifecycle { display: flex; gap: 0.5rem; }
button.primary { align-self: flex-start; padding: 0.6rem 1.4rem; border-radius: 0.5rem; border: none; background: #1f2933; color: #fff; cursor: pointer; }
button.primary:disabled { opacity: 0.45; cursor: not-allowed; }
button.danger { color: #8a1c12; }
</style>
