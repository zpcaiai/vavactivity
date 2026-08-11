<script setup lang="ts">
import { resolveApiBaseUrl } from "@/config/api";
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref
} from "vue";
import { onBeforeRouteLeave, useRoute } from "vue-router";
import { localizeAdminValue } from "@vav/ui-admin";

import { useAdminAuthStore } from "@/stores/admin-auth";

interface ContentBlock {
  id: string;
  type: string;
  version: number;
  data: Record<string, unknown>;
}

interface Localization {
  locale: string;
  localized_slug: string | null;
  title: string;
  subtitle: string | null;
  excerpt: string | null;
  content_blocks: ContentBlock[];
  plain_text: string | null;
  seo_title: string | null;
  seo_description: string | null;
  social_title: string | null;
  social_description: string | null;
  cover_media_id: string | null;
  translation_status: string;
}

interface ContentEntry {
  id: string;
  internal_name: string;
  canonical_slug: string;
  status: string;
  default_locale: string;
  visibility: string;
  version: number;
  current_version: number;
  localizations: Record<string, Localization>;
}

interface ContentVersion {
  version_number: number;
  change_summary: string;
  created_at: string;
}

const route = useRoute();
const auth = useAdminAuthStore();
const baseUrl = resolveApiBaseUrl();
const entry = ref<ContentEntry | null>(null);
const versions = ref<ContentVersion[]>([]);
const locale = ref("zh-CN");
const localization = ref<Localization | null>(null);
const busy = ref(false);
const dirty = ref(false);
const error = ref("");
const savedMessage = ref("");
const scheduleAt = ref("");
const newBlockType = ref("hero");
const entryId = computed(() => String(route.params.id));

type ApiRequestInit = NonNullable<Parameters<typeof fetch>[1]>;

function deepCopy<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

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
  const payload = await response.json() as {
    data: T;
    error?: { message: string };
  };
  if (!response.ok) {
    throw new Error(payload.error?.message ?? "内容请求失败");
  }
  return payload.data;
}

function blankLocalization(selectedLocale: string): Localization {
  return {
    locale: selectedLocale,
    localized_slug: `${entry.value?.canonical_slug ?? "page"}-${selectedLocale.toLowerCase()}`,
    title: "",
    subtitle: null,
    excerpt: null,
    content_blocks: [],
    plain_text: null,
    seo_title: null,
    seo_description: null,
    social_title: null,
    social_description: null,
    cover_media_id: null,
    translation_status: "draft"
  };
}

function chooseLocale(selectedLocale: string) {
  locale.value = selectedLocale;
  localization.value = deepCopy(
    entry.value?.localizations[selectedLocale] ?? blankLocalization(selectedLocale)
  );
  dirty.value = false;
  savedMessage.value = "";
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    entry.value = await api<ContentEntry>(`/admin/content/pages/${entryId.value}`);
    const history = await api<{ items: ContentVersion[] }>(
      `/admin/content/pages/${entryId.value}/versions`
    );
    versions.value = history.items;
    chooseLocale(
      entry.value.localizations[locale.value]
        ? locale.value
        : entry.value.default_locale
    );
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "内容加载失败";
  } finally {
    busy.value = false;
  }
}

function markDirty() {
  dirty.value = true;
  savedMessage.value = "";
}

function blockId() {
  return globalThis.crypto?.randomUUID?.() ?? `block-${Date.now()}`;
}

function addBlock() {
  if (!localization.value) {
    return;
  }
  const defaults: Record<string, Record<string, unknown>> = {
    hero: { heading: "新标题", subheading: "" },
    rich_text: {
      document: {
        type: "doc",
        content: [{ type: "paragraph", content: [{ type: "text", text: "正文" }] }]
      }
    },
    quote: { quote: "引文", attribution: "" },
    call_to_action: {
      title: "行动标题",
      description: "",
      button: { label: "了解更多", href: "/" }
    },
    article_list: { title: "最新文章", limit: 3 },
    story_list: { title: "幸福见证", limit: 3 },
    divider: { title: null, limit: 1 }
  };
  localization.value.content_blocks.push({
    id: blockId(),
    type: newBlockType.value,
    version: 1,
    data: deepCopy(defaults[newBlockType.value] ?? defaults.hero)
  });
  markDirty();
}

function moveBlock(index: number, offset: number) {
  if (!localization.value) {
    return;
  }
  const target = index + offset;
  if (target < 0 || target >= localization.value.content_blocks.length) {
    return;
  }
  const [block] = localization.value.content_blocks.splice(index, 1);
  localization.value.content_blocks.splice(target, 0, block);
  markDirty();
}

function duplicateBlock(index: number) {
  if (!localization.value) {
    return;
  }
  const copy = deepCopy(localization.value.content_blocks[index]);
  copy.id = blockId();
  localization.value.content_blocks.splice(index + 1, 0, copy);
  markDirty();
}

function removeBlock(index: number) {
  localization.value?.content_blocks.splice(index, 1);
  markDirty();
}

function richText(block: ContentBlock) {
  const document = block.data.document as {
    content?: Array<{ content?: Array<{ text?: string }> }>;
  } | undefined;
  return document?.content?.[0]?.content?.[0]?.text ?? "";
}

function setRichText(block: ContentBlock, value: string) {
  block.data.document = {
    type: "doc",
    content: [{
      type: "paragraph",
      content: value ? [{ type: "text", text: value }] : []
    }]
  };
  markDirty();
}

async function save(auto = false) {
  if (!entry.value || !localization.value || (!dirty.value && auto)) {
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    entry.value = await api<ContentEntry>(
      `/admin/content/pages/${entry.value.id}/localizations/${localization.value.locale}`,
      {
        method: "PUT",
        body: JSON.stringify({
          ...localization.value,
          expected_version: entry.value.version,
          change_summary: auto
            ? "Autosave structured content draft"
            : "Save structured content from administration editor"
        })
      }
    );
    dirty.value = false;
    chooseLocale(locale.value);
    savedMessage.value = auto ? "已自动保存" : "草稿已保存";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "保存失败";
  } finally {
    busy.value = false;
  }
}

async function transition(action: string) {
  if (!entry.value) {
    return;
  }
  if (dirty.value) {
    await save();
  }
  try {
    await api(`/admin/content/pages/${entry.value.id}/${action}`, {
      method: "POST",
      body: JSON.stringify({
        reason: `Administration editor ${action} after content review`
      })
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "状态变更失败";
  }
}

async function schedule() {
  if (!entry.value || !scheduleAt.value) {
    return;
  }
  try {
    await api(`/admin/content/pages/${entry.value.id}/schedule`, {
      method: "POST",
      body: JSON.stringify({
        reason: "Schedule content publication after editorial review",
        scheduled_publish_at: new Date(scheduleAt.value).toISOString()
      })
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "定时发布失败";
  }
}

async function preview() {
  if (!entry.value) {
    return;
  }
  const result = await api<{ token: string }>(
    `/admin/content/${entry.value.id}/preview-token`,
    {
      method: "POST",
      body: JSON.stringify({ locale: locale.value })
    }
  );
  window.open(`${baseUrl}/public/preview/${result.token}`, "_blank", "noopener,noreferrer");
}

async function restore(versionNumber: number) {
  if (!entry.value) {
    return;
  }
  try {
    entry.value = await api<ContentEntry>(
      `/admin/content/pages/${entry.value.id}/versions/${versionNumber}/restore`,
      {
        method: "POST",
        body: JSON.stringify({
          reason: `Restore reviewed content version ${versionNumber}`,
          expected_version: entry.value.version
        })
      }
    );
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "版本恢复失败";
  }
}

function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value) {
    event.preventDefault();
  }
}

const autosaveTimer = window.setInterval(() => void save(true), 30_000);
onMounted(() => {
  window.addEventListener("beforeunload", beforeUnload);
  void load();
});
onBeforeUnmount(() => {
  window.clearInterval(autosaveTimer);
  window.removeEventListener("beforeunload", beforeUnload);
});
onBeforeRouteLeave(() => {
  if (!dirty.value) {
    return true;
  }
  return window.confirm("尚有未保存内容，确定离开吗？");
});
</script>

<template>
  <section v-loading="busy">
    <header class="page-toolbar">
      <div>
        <p class="admin-kicker">
          STRUCTURED CONTENT EDITOR
        </p>
        <h2>{{ entry?.internal_name }}</h2>
        <p>{{ entry?.canonical_slug }} · {{ localizeAdminValue(entry?.status, "status") }} · 版本 {{ entry?.version }}</p>
      </div>
      <div class="toolbar-actions">
        <el-button @click="preview">
          打开预览
        </el-button>
        <el-button
          type="primary"
          @click="save(false)"
        >
          保存草稿
        </el-button>
        <el-button
          v-if="entry?.status === 'draft'"
          @click="transition('submit-review')"
        >
          提交审核
        </el-button>
        <el-button
          v-if="entry?.status === 'in_review'"
          v-permission="'content.pages.publish'"
          type="success"
          @click="transition('publish')"
        >
          发布
        </el-button>
      </div>
    </header>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
    />
    <el-alert
      v-if="savedMessage"
      :title="savedMessage"
      type="success"
      :closable="false"
    />

    <div
      v-if="entry && localization"
      class="cms-editor-grid"
      @input="markDirty"
      @change="markDirty"
    >
      <aside class="panel">
        <h3>页面区块</h3>
        <div
          v-for="(block, index) in localization.content_blocks"
          :key="block.id"
          class="cms-block-list-item"
        >
          <strong>{{ index + 1 }}. {{ localizeAdminValue(block.type, "type") }}</strong>
          <div>
            <el-button
              link
              @click="moveBlock(index, -1)"
            >
              上移
            </el-button>
            <el-button
              link
              @click="moveBlock(index, 1)"
            >
              下移
            </el-button>
            <el-button
              link
              @click="duplicateBlock(index)"
            >
              复制
            </el-button>
            <el-button
              link
              type="danger"
              @click="removeBlock(index)"
            >
              删除
            </el-button>
          </div>
        </div>
        <el-select v-model="newBlockType">
          <el-option
            label="Hero"
            value="hero"
          />
          <el-option
            label="富文本"
            value="rich_text"
          />
          <el-option
            label="引文"
            value="quote"
          />
          <el-option
            label="行动按钮"
            value="call_to_action"
          />
          <el-option
            label="文章列表"
            value="article_list"
          />
          <el-option
            label="见证列表"
            value="story_list"
          />
          <el-option
            label="分隔线"
            value="divider"
          />
        </el-select>
        <el-button @click="addBlock">
          添加区块
        </el-button>
      </aside>

      <main class="panel">
        <h3>区块编辑</h3>
        <article
          v-for="(block, index) in localization.content_blocks"
          :key="block.id"
          class="cms-block-editor"
        >
          <strong>{{ index + 1 }} · {{ localizeAdminValue(block.type, "type") }}</strong>
          <template v-if="block.type === 'hero'">
            <label>标题<el-input v-model="block.data.heading" /></label>
            <label>副标题<el-input
              v-model="block.data.subheading"
              type="textarea"
            /></label>
          </template>
          <template v-else-if="block.type === 'rich_text'">
            <label>正文<el-input
              :model-value="richText(block)"
              type="textarea"
              :rows="8"
              @update:model-value="setRichText(block, String($event))"
            /></label>
          </template>
          <template v-else-if="block.type === 'quote'">
            <label>引文<el-input
              v-model="block.data.quote"
              type="textarea"
            /></label>
            <label>署名<el-input v-model="block.data.attribution" /></label>
          </template>
          <template v-else-if="block.type === 'call_to_action'">
            <label>标题<el-input v-model="block.data.title" /></label>
            <label>说明<el-input v-model="block.data.description" /></label>
          </template>
          <template v-else>
            <label>列表标题<el-input v-model="block.data.title" /></label>
            <label>条数<el-input-number
              v-model="block.data.limit"
              :min="1"
              :max="20"
            /></label>
          </template>
        </article>
        <el-empty
          v-if="!localization.content_blocks.length"
          description="尚未添加区块"
        />
      </main>

      <aside class="panel editor-form">
        <h3>设置与发布</h3>
        <label>语言<el-select
          :model-value="locale"
          @update:model-value="chooseLocale(String($event))"
        >
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
        <label>标题<el-input v-model="localization.title" /></label>
        <label>副标题<el-input v-model="localization.subtitle" /></label>
        <label>摘要<el-input
          v-model="localization.excerpt"
          type="textarea"
        /></label>
        <label>翻译状态<el-select v-model="localization.translation_status">
          <el-option
            label="草稿"
            value="draft"
          />
          <el-option
            label="需要审核"
            value="review_required"
          />
          <el-option
            label="已就绪"
            value="ready"
          />
          <el-option
            label="已过期"
            value="outdated"
          />
        </el-select></label>
        <label>SEO 标题<el-input v-model="localization.seo_title" /></label>
        <label>SEO 描述<el-input
          v-model="localization.seo_description"
          type="textarea"
        /></label>
        <label>定时发布<el-date-picker
          v-model="scheduleAt"
          type="datetime"
          value-format="YYYY-MM-DDTHH:mm:ss"
        /></label>
        <el-button @click="schedule">
          设置定时发布
        </el-button>
        <h3>版本记录</h3>
        <div
          v-for="item in versions"
          :key="item.version_number"
          class="version-row"
        >
          <span>v{{ item.version_number }} · {{ item.change_summary }}</span>
          <el-button
            link
            @click="restore(item.version_number)"
          >
            恢复
          </el-button>
        </div>
      </aside>
    </div>
  </section>
</template>
