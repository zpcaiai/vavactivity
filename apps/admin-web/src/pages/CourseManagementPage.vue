<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { formatAdminTableCell } from "@vav/ui-admin";

import { catalogApi } from "@/features/catalog/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

type CourseRow = {
  id: string;
  course_code: string;
  title: string;
  course_type: string;
  status: string;
  free_enrollment: boolean;
};
type LessonRow = { id: string; title: string; lesson_type: string };
type ModuleRow = { id: string; title: string; lessons: LessonRow[] };
type CourseDetail = CourseRow & { modules: ModuleRow[] };
type EnrollmentRow = {
  id: string;
  course_id: string;
  status: string;
  source_type: string;
  course_version_id: string;
};
type CertificateRow = {
  id: string;
  certificate_number: string;
  recipient_name: string;
  course_title: string;
  status: string;
};

const auth = useAdminAuthStore();
const courses = ref<CourseRow[]>([]);
const selectedCourseId = ref("");
const selectedCourse = ref<CourseDetail>();
const enrollments = ref<EnrollmentRow[]>([]);
const certificates = ref<CertificateRow[]>([]);
const loading = ref(false);
const error = ref("");
const tab = ref("publication");
const form = reactive({
  course_code: "",
  internal_name: "",
  course_type: "self_paced",
  visibility: "public",
  free_access_policy: "free_enrollment"
});
const moduleForm = reactive({ module_code: "", internal_name: "", title: "" });
const lessonForm = reactive({
  module_id: "",
  lesson_code: "",
  internal_name: "",
  title: "",
  lesson_type: "rich_text",
  completion_mode: "manual"
});
const videoForm = reactive({
  lesson_id: "",
  provider_video_id: "",
  private_reference: "",
  duration_seconds: 120
});
const grantForm = reactive({ user_id: "", access_duration_days: 365, reason: "" });

/**
 * Courses could be built and published but never attached to anything sellable:
 * the catalog mapping endpoints existed with no UI, so monetisation had to be
 * done straight against the API. Only digital-access course / course-bundle
 * SKUs are accepted by the backend, so the picker offers exactly those.
 */
type CatalogMapping = {
  id: string;
  catalog_sku_id: string;
  access_duration_days: number | null;
  access_start_policy: string;
  course_version_policy: string;
};
type SellableSku = { id: string; sku_code: string; product_name: string };

const catalogMappings = ref<CatalogMapping[]>([]);
const sellableSkus = ref<SellableSku[]>([]);
const mappingForm = reactive({ catalog_sku_id: "", access_duration_days: 365 });

const canManageCatalog = computed(() => auth.hasPermission("courses.catalog.manage"));

function skuLabel(id: string) {
  const sku = sellableSkus.value.find((item) => item.id === id);
  return sku ? `${sku.sku_code}（${sku.product_name}）` : id;
}

async function loadSellableSkus() {
  // Listing SKUs needs its own permission; without it the picker stays empty
  // rather than failing the whole page load.
  if (!auth.hasPermission(["catalog.products.read", "catalog.skus.read"])) return;
  const products = await catalogApi<{ items: Array<Record<string, unknown>> }>(
    "/admin/catalog/products?page_size=100"
  );
  const eligible = products.items.filter(
    (product) =>
      ["course", "course_bundle"].includes(String(product.product_type)) &&
      String(product.fulfillment_type) === "digital_access"
  );
  const collected: SellableSku[] = [];
  for (const product of eligible) {
    const skus = await catalogApi<{ items: Array<Record<string, unknown>> }>(
      `/admin/catalog/products/${String(product.id)}/skus`
    );
    for (const sku of skus.items) {
      collected.push({
        id: String(sku.id),
        sku_code: String(sku.sku_code ?? sku.id),
        product_name: String(product.internal_name ?? product.product_code ?? "")
      });
    }
  }
  sellableSkus.value = collected;
}

async function loadCatalogMappings() {
  if (!selectedCourseId.value || !canManageCatalog.value) return;
  const result = await catalogApi<{ items: CatalogMapping[] }>(
    `/admin/courses/${selectedCourseId.value}/catalog-mappings`
  );
  catalogMappings.value = result.items;
}

async function saveCatalogMapping() {
  if (!mappingForm.catalog_sku_id) {
    error.value = "请选择要关联的商品 SKU。";
    return;
  }
  error.value = "";
  try {
    await catalogApi(`/admin/courses/${selectedCourseId.value}/catalog-mappings`, {
      method: "POST",
      body: JSON.stringify({
        catalog_sku_id: mappingForm.catalog_sku_id,
        access_duration_days: mappingForm.access_duration_days || null,
        access_start_policy: "entitlement_activation",
        course_version_policy: "pin_at_enrollment"
      })
    });
    mappingForm.catalog_sku_id = "";
    await loadCatalogMappings();
    await loadSelected();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "商品关联失败";
  }
}

async function removeCatalogMapping(mapping: CatalogMapping) {
  if (!window.confirm("确认解除该商品关联？解除后新的购买将无法开通本课程访问权。")) return;
  error.value = "";
  try {
    await catalogApi(
      `/admin/courses/${selectedCourseId.value}/catalog-mappings/${mapping.id}`,
      { method: "DELETE" }
    );
    await loadCatalogMappings();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "解除关联失败";
  }
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    courses.value = (await catalogApi<{ items: CourseRow[] }>("/admin/courses")).items;
    if (!selectedCourseId.value && courses.value.length) {
      selectedCourseId.value = courses.value[0].id;
    }
    if (selectedCourseId.value) await loadSelected();
    await loadSellableSkus();

  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "课程中心加载失败";
  } finally {
    loading.value = false;
  }
}

async function loadSelected() {
  if (!selectedCourseId.value) return;
  try {
    const [detail, enrollmentResult, certificateResult] = await Promise.all([
      catalogApi<CourseDetail>(`/admin/courses/${selectedCourseId.value}`),
      catalogApi<{ items: EnrollmentRow[] }>(
        `/admin/course-enrollments?course_id=${selectedCourseId.value}`
      ),
      catalogApi<{ items: CertificateRow[] }>(
        `/admin/course-certificates?course_id=${selectedCourseId.value}`
      )
    ]);
    selectedCourse.value = detail;
    enrollments.value = enrollmentResult.items;
    certificates.value = certificateResult.items;
    await loadCatalogMappings();
    if (!detail.modules.some((module) => module.id === lessonForm.module_id)) {
      lessonForm.module_id = detail.modules[0]?.id ?? "";
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "课程详情加载失败";
  }
}

async function createCourse() {
  try {
    const course = await catalogApi<CourseRow>("/admin/courses", {
      method: "POST",
      body: JSON.stringify({
        ...form,
        default_locale: "zh-CN",
        difficulty_level: "beginner"
      })
    });
    await catalogApi(`/admin/courses/${course.id}/localizations/zh-CN`, {
      method: "PUT",
      body: JSON.stringify({
        locale: "zh-CN",
        slug: form.course_code.replaceAll("_", "-"),
        title: form.internal_name,
        description_blocks: [],
        learning_outcomes: [],
        target_audience: [],
        prerequisites: [],
        translation_status: "ready"
      })
    });
    Object.assign(form, {
      course_code: "",
      internal_name: "",
      course_type: "self_paced",
      visibility: "public",
      free_access_policy: "free_enrollment"
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "课程创建失败";
  }
}

async function createModule() {
  if (!selectedCourseId.value) return;
  try {
    await catalogApi(`/admin/courses/${selectedCourseId.value}/modules`, {
      method: "POST",
      body: JSON.stringify({
        ...moduleForm,
        locale: "zh-CN",
        sort_order: (selectedCourse.value?.modules.length ?? 0) * 10 + 10,
        status: "published",
        required: true
      })
    });
    Object.assign(moduleForm, { module_code: "", internal_name: "", title: "" });
    await loadSelected();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "章节创建失败";
  }
}

async function createLesson() {
  if (!lessonForm.module_id) return;
  try {
    await catalogApi(`/admin/course-modules/${lessonForm.module_id}/lessons`, {
      method: "POST",
      body: JSON.stringify({
        ...lessonForm,
        locale: "zh-CN",
        sort_order: 10,
        status: "published",
        required: true,
        preview_policy: "none",
        content_blocks:
          lessonForm.lesson_type === "rich_text"
            ? [{ type: "paragraph", text: "请在内容编辑器中补充课时正文。" }]
            : []
      })
    });
    Object.assign(lessonForm, {
      lesson_code: "",
      internal_name: "",
      title: "",
      lesson_type: "rich_text",
      completion_mode: "manual"
    });
    await loadSelected();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "课时创建失败";
  }
}

async function attachVideo() {
  if (!videoForm.lesson_id) return;
  try {
    await catalogApi(`/admin/course-lessons/${videoForm.lesson_id}/video`, {
      method: "PUT",
      body: JSON.stringify({
        ...videoForm,
        duration_seconds: Number(videoForm.duration_seconds),
        processing_status: "ready",
        required_watch_basis_points: 9000
      })
    });
    Object.assign(videoForm, {
      provider_video_id: "",
      private_reference: "",
      duration_seconds: 120
    });
    await loadSelected();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "视频关联失败";
  }
}

async function grantEnrollment() {
  if (!selectedCourseId.value) return;
  try {
    await catalogApi(`/admin/courses/${selectedCourseId.value}/enrollments`, {
      method: "POST",
      body: JSON.stringify(grantForm)
    });
    Object.assign(grantForm, { user_id: "", access_duration_days: 365, reason: "" });
    await loadSelected();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "学员授权失败";
  }
}

async function enrollmentAction(enrollment: EnrollmentRow, action: "suspend" | "restore" | "revoke") {
  try {
    await catalogApi(`/admin/course-enrollments/${enrollment.id}/${action}`, {
      method: "POST",
      body: JSON.stringify({ reason: `Operator ${action} from course center` })
    });
    await loadSelected();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "学员状态变更失败";
  }
}

async function revokeCertificate(certificate: CertificateRow) {
  try {
    await catalogApi(`/admin/course-certificates/${certificate.id}/revoke`, {
      method: "POST",
      body: JSON.stringify({ reason: "Operator revocation from course center" })
    });
    await loadSelected();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "证书撤销失败";
  }
}

function lessonTitles(module: ModuleRow) {
  return module.lessons.map((lesson) => lesson.title).join("、") || "暂无";
}

async function transition(course: CourseRow, target_status: string) {
  try {
    await catalogApi(`/admin/courses/${course.id}/transition`, {
      method: "POST",
      body: JSON.stringify({
        target_status,
        reason: `Operator transition to ${target_status}`
      })
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "课程状态变更失败";
  }
}

onMounted(() => void load());
</script>

<template>
  <section v-loading="loading">
    <header class="page-toolbar">
      <div>
        <p class="admin-kicker">
          课程运营
        </p>
        <h2>课程中心</h2>
        <p>课程结构、版本、视频与学习进度在此管理；商品定价和订单仍由 Catalog/Commerce 管理。</p>
      </div>
      <el-tag type="warning">
        发布会生成不可变课程版本
      </el-tag>
    </header>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
    />
    <el-form-item label="当前课程">
      <el-select
        v-model="selectedCourseId"
        placeholder="选择课程"
        @change="loadSelected"
      >
        <el-option
          v-for="course in courses"
          :key="course.id"
          :label="`${course.title} · ${course.status}`"
          :value="course.id"
        />
      </el-select>
    </el-form-item>
    <el-tabs v-model="tab">
      <el-tab-pane
        label="课程发布"
        name="publication"
      >
        <el-form
          :model="form"
          label-position="top"
          class="editor-grid"
        >
          <el-form-item label="课程代码">
            <el-input
              v-model="form.course_code"
              placeholder="relationship_foundations"
            />
          </el-form-item>
          <el-form-item label="内部名称">
            <el-input v-model="form.internal_name" />
          </el-form-item>
          <el-form-item label="课程类型">
            <el-select v-model="form.course_type">
              <el-option
                label="自主学习"
                value="self_paced"
              />
              <el-option
                label="同期班"
                value="cohort"
              />
              <el-option
                label="混合课程"
                value="hybrid"
              />
            </el-select>
          </el-form-item>
          <el-button
            type="primary"
            @click="createCourse"
          >
            创建课程草稿
          </el-button>
        </el-form>
        <el-table
          :data="courses"
          stripe
        >
          <el-table-column
            prop="course_code"
            label="代码"
          />
          <el-table-column
            prop="title"
            label="名称"
          />
          <el-table-column
            prop="course_type"
            label="类型"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
          <el-table-column
            label="操作"
            min-width="220"
          >
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
                type="primary"
                size="small"
                @click="transition(row, 'published')"
              >
                发布版本
              </el-button>
              <el-button
                v-if="row.status === 'published'"
                size="small"
                @click="transition(row, 'unpublished')"
              >
                下架
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        label="结构与课时"
        name="curriculum"
      >
        <el-form
          :model="moduleForm"
          label-position="top"
          class="editor-grid"
        >
          <el-form-item label="章节代码">
            <el-input v-model="moduleForm.module_code" />
          </el-form-item>
          <el-form-item label="内部名称">
            <el-input v-model="moduleForm.internal_name" />
          </el-form-item>
          <el-form-item label="显示标题">
            <el-input v-model="moduleForm.title" />
          </el-form-item>
          <el-button
            type="primary"
            @click="createModule"
          >
            新增章节
          </el-button>
        </el-form>
        <el-form
          :model="lessonForm"
          label-position="top"
          class="editor-grid"
        >
          <el-form-item label="所属章节">
            <el-select v-model="lessonForm.module_id">
              <el-option
                v-for="module in selectedCourse?.modules"
                :key="module.id"
                :label="module.title"
                :value="module.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="课时代码">
            <el-input v-model="lessonForm.lesson_code" />
          </el-form-item>
          <el-form-item label="课时名称">
            <el-input v-model="lessonForm.internal_name" />
          </el-form-item>
          <el-form-item label="显示标题">
            <el-input v-model="lessonForm.title" />
          </el-form-item>
          <el-form-item label="课时类型">
            <el-select v-model="lessonForm.lesson_type">
              <el-option
                label="富文本"
                value="rich_text"
              />
              <el-option
                label="视频"
                value="video"
              />
              <el-option
                label="音频"
                value="audio"
              />
              <el-option
                label="文档"
                value="document"
              />
              <el-option
                label="练习"
                value="exercise"
              />
              <el-option
                label="作业"
                value="assignment"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="完成规则">
            <el-select v-model="lessonForm.completion_mode">
              <el-option
                label="手动完成"
                value="manual"
              />
              <el-option
                label="有效观看"
                value="video_watch"
              />
              <el-option
                label="练习通过"
                value="exercise_pass"
              />
              <el-option
                label="作业评分"
                value="assignment_graded"
              />
            </el-select>
          </el-form-item>
          <el-button
            type="primary"
            @click="createLesson"
          >
            新增课时
          </el-button>
        </el-form>
        <el-form
          :model="videoForm"
          label-position="top"
          class="editor-grid"
        >
          <el-form-item label="视频课时">
            <el-select v-model="videoForm.lesson_id">
              <el-option
                v-for="lesson in selectedCourse?.modules.flatMap((item) => item.lessons).filter((item) => item.lesson_type === 'video')"
                :key="lesson.id"
                :label="lesson.title"
                :value="lesson.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="服务商视频编号">
            <el-input v-model="videoForm.provider_video_id" />
          </el-form-item>
          <el-form-item label="私有资源引用">
            <el-input
              v-model="videoForm.private_reference"
              type="password"
              show-password
            />
          </el-form-item>
          <el-form-item label="时长（秒）">
            <el-input-number
              v-model="videoForm.duration_seconds"
              :min="1"
            />
          </el-form-item>
          <el-button @click="attachVideo">
            关联私有视频
          </el-button>
        </el-form>
        <el-table
          :data="selectedCourse?.modules ?? []"
          stripe
        >
          <el-table-column
            prop="title"
            label="章节"
          />
          <el-table-column label="课时">
            <template #default="{ row }">
              {{ lessonTitles(row) }}
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        label="报名与进度"
        name="learners"
      >
        <el-form
          :model="grantForm"
          label-position="top"
          class="editor-grid"
        >
          <el-form-item label="用户唯一标识">
            <el-input v-model="grantForm.user_id" />
          </el-form-item>
          <el-form-item label="授权天数">
            <el-input-number
              v-model="grantForm.access_duration_days"
              :min="1"
            />
          </el-form-item>
          <el-form-item label="操作理由">
            <el-input v-model="grantForm.reason" />
          </el-form-item>
          <el-button
            type="primary"
            @click="grantEnrollment"
          >
            授权课程
          </el-button>
        </el-form>
        <el-table
          :data="enrollments"
          stripe
        >
          <el-table-column
            prop="source_type"
            label="来源"
          />
          <el-table-column
            prop="course_version_id"
            label="固定版本"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
          <el-table-column label="操作">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'active'"
                size="small"
                @click="enrollmentAction(row, 'suspend')"
              >
                暂停
              </el-button>
              <el-button
                v-if="row.status === 'suspended'"
                size="small"
                @click="enrollmentAction(row, 'restore')"
              >
                恢复
              </el-button>
              <el-button
                type="danger"
                size="small"
                @click="enrollmentAction(row, 'revoke')"
              >
                撤销
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        v-if="canManageCatalog"
        label="商品关联"
        name="catalog"
      >
        <el-alert
          title="课程只有关联到「数字访问」类型的课程或课程套餐 SKU 之后才能被售卖；关联后按订单权益开通访问权，并在报名时锁定课程版本。"
          type="info"
          :closable="false"
        />
        <el-form
          label-position="top"
          class="editor-grid"
        >
          <el-form-item label="可售 SKU">
            <el-select
              v-model="mappingForm.catalog_sku_id"
              filterable
              placeholder="选择数字访问类课程 SKU"
            >
              <el-option
                v-for="sku in sellableSkus"
                :key="sku.id"
                :label="`${sku.sku_code}（${sku.product_name}）`"
                :value="sku.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="访问有效期（天，留空表示长期有效）">
            <el-input-number
              v-model="mappingForm.access_duration_days"
              :min="0"
            />
          </el-form-item>
          <el-button
            type="primary"
            @click="saveCatalogMapping"
          >
            保存关联
          </el-button>
        </el-form>
        <el-table
          :data="catalogMappings"
          stripe
        >
          <el-table-column label="SKU">
            <template #default="{ row }">
              {{ skuLabel(row.catalog_sku_id) }}
            </template>
          </el-table-column>
          <el-table-column
            prop="access_duration_days"
            label="有效期（天）"
          />
          <el-table-column
            prop="access_start_policy"
            :formatter="formatAdminTableCell"
            label="生效方式"
          />
          <el-table-column
            prop="course_version_policy"
            :formatter="formatAdminTableCell"
            label="版本策略"
          />
          <el-table-column label="操作">
            <template #default="{ row }">
              <el-button
                type="danger"
                size="small"
                @click="removeCatalogMapping(row)"
              >
                解除关联
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        label="证书"
        name="certificates"
      >
        <el-alert
          title="证书仅证明 VAV 课程完成，不宣称政府、学术或专业认证资质。"
          type="info"
          :closable="false"
        />
        <el-table
          :data="certificates"
          stripe
        >
          <el-table-column
            prop="certificate_number"
            label="证书编号"
          />
          <el-table-column
            prop="recipient_name"
            label="学员"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
          <el-table-column label="操作">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'valid'"
                type="danger"
                size="small"
                @click="revokeCertificate(row)"
              >
                撤销证书
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>
