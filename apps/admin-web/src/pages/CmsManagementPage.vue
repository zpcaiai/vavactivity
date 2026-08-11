<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { formatAdminTableCell } from "@vav/ui-admin";
import { resolveApiBaseUrl } from "@/config/api";

import { useAdminAuthStore } from "@/stores/admin-auth";

interface ContentItem {
  id: string;
  internal_name: string;
  canonical_slug: string;
  status: string;
  default_locale: string;
  version: number;
  localizations: Record<string, { title: string; translation_status: string }>;
}

const route = useRoute();
const router = useRouter();
const auth = useAdminAuthStore();
const baseUrl = resolveApiBaseUrl();
const items = ref<ContentItem[]>([]);
const busy = ref(false);
const error = ref("");
const showCreate = ref(false);
const form = ref({
  internal_name: "",
  canonical_slug: "",
  title: "",
  locale: "zh-CN"
});
const section = computed(() => String(route.meta.cmsSection ?? "pages"));
const endpoint = computed(() => `/admin/content/${section.value}`);

type ApiRequestInit = NonNullable<Parameters<typeof fetch>[1]>;

async function api<T>(path: string, init: ApiRequestInit = {}) {
  await auth.bootstrap();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${auth.accessToken}`);
  if (init.body) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    credentials: "include",
    headers
  });
  const payload = (await response.json()) as T & { error?: { message: string } };
  if (!response.ok) {
    throw new Error(payload.error?.message ?? "请求失败");
  }
  return payload;
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    const payload = await api<{ data: { items: ContentItem[] } }>(endpoint.value);
    items.value = payload.data.items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "加载失败";
  } finally {
    busy.value = false;
  }
}

async function create() {
  error.value = "";
  try {
    await api(endpoint.value, {
      method: "POST",
      body: JSON.stringify({
        internal_name: form.value.internal_name,
        canonical_slug: form.value.canonical_slug,
        default_locale: form.value.locale,
        localization: {
          locale: form.value.locale,
          localized_slug: form.value.canonical_slug,
          title: form.value.title,
          content_blocks: [],
          translation_status: "draft"
        },
        change_summary: "Create content draft from administration UI",
        ...(section.value === "testimonials"
          ? {
              metadata: {
                consent_status: "pending",
                anonymity_level: "fully_anonymous"
              }
            }
          : {})
      })
    });
    showCreate.value = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "创建失败";
  }
}

async function transition(item: ContentItem, action: string) {
  await api(`/admin/content/${section.value}/${item.id}/${action}`, {
    method: "POST",
    body: JSON.stringify({
      reason: `Administration workflow: ${action} content after editorial review`
    })
  });
  await load();
}

function openEditor(item: ContentItem) {
  if (section.value === "pages") {
    void router.push(`/admin/content/pages/${item.id}`);
  }
}

onMounted(() => void load());
watch(section, () => void load());
</script>

<template>
  <section v-loading="busy">
    <header class="page-toolbar">
      <div>
        <p class="admin-kicker">
          STRUCTURED CMS
        </p>
        <h2>{{ section }}</h2>
      </div>
      <el-button
        v-permission="`content.${section}.create`"
        type="primary"
        @click="showCreate = true"
      >
        创建草稿
      </el-button>
    </header>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
    />
    <el-table
      :data="items"
      stripe
      @row-click="openEditor"
    >
      <el-table-column
        prop="internal_name"
        label="内部名称"
      />
      <el-table-column
        prop="canonical_slug"
        label="Slug"
      />
      <el-table-column
        prop="status"
        :formatter="formatAdminTableCell"
        label="发布状态"
      />
      <el-table-column
        prop="version"
        label="版本"
        width="90"
      />
      <el-table-column
        label="操作"
        width="260"
      >
        <template #default="{ row }">
          <el-button
            v-if="row.status === 'draft'"
            size="small"
            @click="transition(row, 'submit-review')"
          >
            提交审核
          </el-button>
          <el-button
            v-if="row.status === 'in_review'"
            v-permission="`content.${section}.publish`"
            size="small"
            type="primary"
            @click="transition(row, 'publish')"
          >
            发布
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-dialog
      v-model="showCreate"
      title="创建内容草稿"
      width="640px"
    >
      <div class="editor-form">
        <label>内部名称<el-input v-model="form.internal_name" /></label>
        <label>Slug<el-input v-model="form.canonical_slug" /></label>
        <label>标题<el-input v-model="form.title" /></label>
        <label>语言<el-select v-model="form.locale">
          <el-option
            label="简体中文"
            value="zh-CN"
          />
          <el-option
            label="繁體中文"
            value="zh-TW"
          />
          <el-option
            label="English"
            value="en"
          />
        </el-select></label>
      </div>
      <template #footer>
        <el-button @click="showCreate = false">
          取消
        </el-button>
        <el-button
          type="primary"
          @click="create"
        >
          保存草稿
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>
