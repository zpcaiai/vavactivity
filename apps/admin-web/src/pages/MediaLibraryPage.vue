<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { useAdminAuthStore } from "@/stores/admin-auth";

interface MediaItem {
  id: string;
  filename: string;
  mime_type: string;
  byte_size: number;
  visibility: string;
  processing_status: string;
}

const auth = useAdminAuthStore();
const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
const items = ref<MediaItem[]>([]);
const selectedFile = ref<File | null>(null);
const altText = ref("");
const locale = ref("zh-CN");
const visibility = ref("public");
const busy = ref(false);
const error = ref("");
const message = ref("");
const canUpload = computed(() => Boolean(selectedFile.value && altText.value.trim()));
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
    throw new Error(payload.error?.message ?? "媒体请求失败");
  }
  return payload.data;
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    const result = await api<{ items: MediaItem[] }>("/admin/media");
    items.value = result.items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "媒体加载失败";
  } finally {
    busy.value = false;
  }
}

function chooseFile(event: Event) {
  const input = event.target as HTMLInputElement;
  selectedFile.value = input.files?.[0] ?? null;
}

async function checksum(file: File) {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

async function upload() {
  const file = selectedFile.value;
  if (!file || !canUpload.value) {
    return;
  }
  busy.value = true;
  error.value = "";
  message.value = "";
  try {
    const sha256 = await checksum(file);
    const intent = await api<{ id: string; upload_url: string }>("/admin/media/uploads", {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        mime_type: file.type,
        byte_size: file.size,
        checksum_sha256: sha256,
        visibility: visibility.value
      })
    });
    const uploadResponse = await fetch(intent.upload_url, {
      method: "PUT",
      body: file,
      headers: {
        "Content-Type": file.type,
        "x-amz-meta-sha256": sha256
      }
    });
    if (!uploadResponse.ok) {
      throw new Error(`对象上传失败（${uploadResponse.status}）`);
    }
    await api(`/admin/media/uploads/${intent.id}/complete`, {
      method: "POST",
      body: JSON.stringify({ checksum_sha256: sha256 })
    });
    await api(`/admin/media/${intent.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        visibility: visibility.value,
        locale: locale.value,
        alt_text: altText.value,
        caption: null,
        accessibility_description: altText.value
      })
    });
    selectedFile.value = null;
    altText.value = "";
    message.value = "媒体内容、真实 MIME、SHA-256 与衍生尺寸已验证。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "媒体上传失败";
  } finally {
    busy.value = false;
  }
}

function previewUrl(item: MediaItem) {
  return `${baseUrl}/public/media/${item.id}?variant=thumbnail`;
}

onMounted(() => void load());
</script>

<template>
  <section v-loading="busy">
    <header class="page-toolbar">
      <div>
        <p class="admin-kicker">
          VERIFIED MEDIA
        </p>
        <h2>媒体库</h2>
      </div>
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
      v-permission="'content.media.upload'"
      class="media-upload-panel"
    >
      <label>
        <span>选择图片或 PDF</span>
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp,image/avif,application/pdf"
          @change="chooseFile"
        >
      </label>
      <label>语言<el-select v-model="locale">
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
      <label>可见性<el-select v-model="visibility">
        <el-option
          label="公开"
          value="public"
        />
        <el-option
          label="私有"
          value="private"
        />
      </el-select></label>
      <label>替代文本<el-input v-model="altText" /></label>
      <el-button
        type="primary"
        :disabled="!canUpload"
        @click="upload"
      >
        上传并验证
      </el-button>
    </div>
    <div class="media-grid">
      <article
        v-for="item in items"
        :key="item.id"
        class="media-card"
      >
        <img
          v-if="item.mime_type.startsWith('image/') && item.visibility === 'public' && item.processing_status === 'ready'"
          :src="previewUrl(item)"
          :alt="item.filename"
        >
        <div
          v-else
          class="media-file-placeholder"
        >
          {{ item.mime_type === "application/pdf" ? "PDF" : "MEDIA" }}
        </div>
        <strong>{{ item.filename }}</strong>
        <small>{{ item.mime_type }} · {{ Math.ceil(item.byte_size / 1024) }} KB</small>
        <small>{{ item.visibility }} · {{ item.processing_status }}</small>
      </article>
    </div>
  </section>
</template>
