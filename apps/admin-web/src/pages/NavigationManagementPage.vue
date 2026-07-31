<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { useAdminAuthStore } from "@/stores/admin-auth";

interface NavigationItem {
  id?: string;
  internal_name: string;
  link_type: "route" | "external" | "content";
  target_entry_id: string | null;
  external_url: string | null;
  route_name: string | null;
  sort_order: number;
  open_in_new_tab: boolean;
  required_auth: boolean;
  is_active: boolean;
  localizations: Record<string, string>;
}

interface NavigationMenu {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
  items: NavigationItem[];
}

const auth = useAdminAuthStore();
const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
const menus = ref<NavigationMenu[]>([]);
const selectedCode = ref("");
const draft = ref<NavigationMenu | null>(null);
const busy = ref(false);
const error = ref("");
const message = ref("");
const selected = computed(() => menus.value.find((menu) => menu.code === selectedCode.value));
type ApiRequestInit = NonNullable<Parameters<typeof fetch>[1]>;

async function api<T>(path: string, init: ApiRequestInit = {}): Promise<T> {
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
  const payload = (await response.json()) as { data?: T; error?: { message: string } };
  if (!response.ok || !payload.data) {
    throw new Error(payload.error?.message ?? "导航请求失败");
  }
  return payload.data;
}

function copySelected() {
  draft.value = selected.value
    ? JSON.parse(JSON.stringify(selected.value)) as NavigationMenu
    : null;
}

async function load(preferredCode?: string) {
  busy.value = true;
  error.value = "";
  try {
    const data = await api<{ items: NavigationMenu[] }>("/admin/navigation");
    menus.value = data.items;
    const requestedCode = preferredCode || selectedCode.value || "main_navigation";
    selectedCode.value = data.items.some((item) => item.code === requestedCode)
      ? requestedCode
      : (data.items[0]?.code || "");
    copySelected();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "导航加载失败";
  } finally {
    busy.value = false;
  }
}

function addItem() {
  draft.value?.items.push({
    internal_name: "",
    link_type: "route",
    target_entry_id: null,
    external_url: null,
    route_name: "",
    sort_order: draft.value.items.length,
    open_in_new_tab: false,
    required_auth: false,
    is_active: true,
    localizations: { "zh-CN": "", "zh-TW": "", en: "" }
  });
}

function removeItem(index: number) {
  draft.value?.items.splice(index, 1);
}

function moveItem(index: number, direction: -1 | 1) {
  if (!draft.value) {
    return;
  }
  const target = index + direction;
  if (target < 0 || target >= draft.value.items.length) {
    return;
  }
  const [item] = draft.value.items.splice(index, 1);
  if (item) {
    draft.value.items.splice(target, 0, item);
  }
}

async function save() {
  if (!draft.value) {
    return;
  }
  busy.value = true;
  error.value = "";
  message.value = "";
  try {
    await api(`/admin/navigation/${encodeURIComponent(draft.value.code)}`, {
      method: "PUT",
      body: JSON.stringify({
        name: draft.value.name,
        is_active: draft.value.is_active,
        reason: "Update navigation after multilingual content review",
        items: draft.value.items.map((item, index) => ({
          internal_name: item.internal_name,
          link_type: item.link_type,
          target_entry_id: item.link_type === "content" ? item.target_entry_id : null,
          external_url: item.link_type === "external" ? item.external_url : null,
          route_name: item.link_type === "route" ? item.route_name : null,
          sort_order: index,
          open_in_new_tab: item.open_in_new_tab,
          required_auth: item.required_auth,
          is_active: item.is_active,
          localizations: Object.entries(item.localizations)
            .filter(([, label]) => label.trim())
            .map(([locale, label]) => ({ locale, label }))
        }))
      })
    });
    message.value = "导航已保存并刷新公共缓存。";
    await load(draft.value.code);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "导航保存失败";
  } finally {
    busy.value = false;
  }
}

onMounted(() => void load());
</script>

<template>
  <section v-loading="busy">
    <header class="page-toolbar">
      <div>
        <p class="admin-kicker">
          NAVIGATION &amp; FOOTER
        </p>
        <h2>导航管理</h2>
      </div>
      <el-button
        v-permission="'content.navigation.manage'"
        type="primary"
        @click="save"
      >
        保存导航
      </el-button>
    </header>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
    />
    <el-alert
      v-if="message"
      :title="message"
      type="success"
      :closable="false"
    />
    <div
      v-if="draft"
      class="navigation-editor"
    >
      <aside>
        <button
          v-for="menu in menus"
          :key="menu.code"
          type="button"
          :class="{ active: selectedCode === menu.code }"
          @click="selectedCode = menu.code; copySelected()"
        >
          <strong>{{ menu.name }}</strong>
          <small>{{ menu.code }}</small>
        </button>
      </aside>
      <div class="navigation-editor-main">
        <div class="editor-form navigation-settings">
          <label>菜单名称<el-input v-model="draft.name" /></label>
          <label class="checkbox-row">
            <input
              v-model="draft.is_active"
              type="checkbox"
            >
            启用此菜单
          </label>
        </div>
        <article
          v-for="(item, index) in draft.items"
          :key="item.id ?? index"
          class="navigation-item-card"
        >
          <div class="navigation-item-toolbar">
            <strong>项目 {{ index + 1 }}</strong>
            <div>
              <el-button
                size="small"
                :disabled="index === 0"
                @click="moveItem(index, -1)"
              >
                上移
              </el-button>
              <el-button
                size="small"
                :disabled="index === draft.items.length - 1"
                @click="moveItem(index, 1)"
              >
                下移
              </el-button>
              <el-button
                size="small"
                @click="removeItem(index)"
              >
                删除
              </el-button>
            </div>
          </div>
          <div class="editor-form">
            <label>内部名称<el-input v-model="item.internal_name" /></label>
            <label>链接类型<el-select v-model="item.link_type">
              <el-option
                label="站内路由"
                value="route"
              />
              <el-option
                label="内容条目"
                value="content"
              />
              <el-option
                label="外部链接"
                value="external"
              />
            </el-select></label>
            <label v-if="item.link_type === 'route'">
              路由名称<el-input v-model="item.route_name" />
            </label>
            <label v-if="item.link_type === 'content'">
              内容 UUID<el-input v-model="item.target_entry_id" />
            </label>
            <label v-if="item.link_type === 'external'">
              HTTPS URL<el-input v-model="item.external_url" />
            </label>
            <label>简体中文<el-input v-model="item.localizations['zh-CN']" /></label>
            <label>繁體中文<el-input v-model="item.localizations['zh-TW']" /></label>
            <label>English<el-input v-model="item.localizations.en" /></label>
            <label class="checkbox-row">
              <input
                v-model="item.open_in_new_tab"
                type="checkbox"
              >
              新窗口打开
            </label>
            <label class="checkbox-row">
              <input
                v-model="item.required_auth"
                type="checkbox"
              >
              需要登录
            </label>
            <label class="checkbox-row">
              <input
                v-model="item.is_active"
                type="checkbox"
              >
              启用
            </label>
          </div>
        </article>
        <el-button @click="addItem">
          添加导航项目
        </el-button>
      </div>
    </div>
  </section>
</template>
