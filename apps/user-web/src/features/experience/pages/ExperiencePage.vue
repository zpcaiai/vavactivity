<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { VAlert, VButton, VPageState, VStatusBadge } from "@vav/ui-core";
import { ExperienceBreadcrumbs } from "@vav/experience-components";
import { localizeRoute } from "@vav/navigation-contracts";

import { experienceApi, type ExperienceRow } from "@/features/experience/api";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const auth = useAuthStore();
const busy = ref(false);
const error = ref("");
const rows = ref<ExperienceRow[]>([]);
const home = ref<ExperienceRow>({});
const query = ref(String(route.query.q ?? ""));
const notice = ref("");
const section = computed(() => String(route.meta.experienceSection ?? "home"));
const locale = computed(() => String(route.params.locale ?? "zh-CN"));

function localized(value: unknown) {
  const map = value as Record<string, string> | undefined;
  return map?.[locale.value] ?? map?.["zh-CN"] ?? "";
}

function pathFor(row: ExperienceRow) {
  const raw = String(row.route_path ?? row.action_route_code ?? row.fallback_route_code ?? "");
  const routeMap: Record<string, string> = {
    "user.account": `/${locale.value}/account`,
    "user.experience-home": `/${locale.value}/account/home`,
    "user.activities": `/${locale.value}/activities`,
    "user.courses": `/${locale.value}/courses`,
    "user.counseling": `/${locale.value}/counseling`,
    "user.safety": `/${locale.value}/account/safety`,
    "user.privacy": `/${locale.value}/account/privacy`,
    "user.membership": `/${locale.value}/account/membership`,
    "user.dating-profile": `/${locale.value}/account/dating-profile`,
    "user.matchmaking": `/${locale.value}/account/matchmaking/matches`
  };
  return routeMap[raw] ?? (localizeRoute(raw, locale.value) || `/${locale.value}/account/home`);
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    if (section.value === "home") {
      home.value = await experienceApi.home();
      rows.value = [];
    } else if (section.value === "tasks") {
      rows.value = await experienceApi.tasks(Boolean(route.query.history));
    } else if (section.value === "journeys") {
      rows.value = await experienceApi.journeys();
    } else if (section.value === "search") {
      rows.value = query.value.trim() ? await experienceApi.search(query.value, Boolean(auth.user)) : [];
    } else {
      rows.value = await experienceApi.help(undefined, locale.value, Boolean(auth.user));
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "体验数据加载失败";
  } finally {
    busy.value = false;
  }
}

async function sendFeedback() {
  if (!auth.user) return;
  await experienceApi.feedback(`user.${section.value}`, "cannot_find_next_step");
  notice.value = "反馈已记录；内容已按最小化原则处理。";
}

onMounted(load);
watch(() => [section.value, route.query.history], load);
</script>

<template>
  <section class="experience-page">
    <header>
      <div>
        <p class="eyebrow">
          MY VAV · EXPERIENCE CENTER
        </p><h1>{{ section === 'home' ? '我的首页' : section === 'tasks' ? '任务中心' : section === 'journeys' ? '我的旅程' : section === 'search' ? '全站搜索' : '帮助中心' }}</h1><p>状态与完成结果来自所属业务模块；这里负责解释、导航和恢复，不会替你作决定。</p>
      </div>
      <VStatusBadge
        status="info"
        label="业务状态权威投影"
      />
    </header>
    <nav aria-label="体验中心导航">
      <RouterLink :to="`/${locale}/account/home`">
        首页
      </RouterLink><RouterLink :to="`/${locale}/account/tasks`">
        任务
      </RouterLink><RouterLink :to="`/${locale}/account/journeys`">
        旅程
      </RouterLink><RouterLink :to="`/${locale}/search`">
        搜索
      </RouterLink><RouterLink :to="`/${locale}/help`">
        帮助
      </RouterLink>
    </nav>
    <ExperienceBreadcrumbs :items="[{ label: '首页', href: `/${locale}/account/home` }, { label: section, href: route.fullPath }]" />
    <VAlert
      v-if="error"
      tone="danger"
      title="暂时无法加载"
    >
      {{ error }} <button
        type="button"
        @click="load"
      >
        重试
      </button>
    </VAlert>
    <VAlert
      v-if="notice"
      tone="success"
      title="已收到"
    >
      {{ notice }}
    </VAlert>
    <form
      v-if="section === 'search'"
      class="search-form"
      role="search"
      @submit.prevent="load"
    >
      <label for="experience-query">搜索内容、服务、任务和帮助</label><div>
        <input
          id="experience-query"
          v-model="query"
          maxlength="200"
          autocomplete="off"
        ><VButton
          type="submit"
          :disabled="busy"
        >
          搜索
        </VButton>
      </div>
    </form>
    <div
      v-if="section === 'home' && !busy"
      class="metrics"
    >
      <article><strong>{{ (home.critical_tasks as unknown[] | undefined)?.length ?? 0 }}</strong><span>必须处理</span></article><article><strong>{{ (home.next_tasks as unknown[] | undefined)?.length ?? 0 }}</strong><span>建议下一步</span></article><article><strong>{{ home.unread_notifications ?? 0 }}</strong><span>未读通知</span></article><article><strong>{{ home.active_journeys ?? 0 }}</strong><span>进行中旅程</span></article>
      <article class="wide">
        <h2>当前会员</h2><p>{{ (home.membership as Record<string, unknown> | undefined)?.plan_code ?? '当前没有可显示的会员计划' }} · {{ (home.membership as Record<string, unknown> | undefined)?.status ?? 'not_available' }}</p>
      </article>
      <article class="wide">
        <h2>优先级边界</h2><p>安全、隐私和付款事项始终优先于营销内容。</p>
      </article>
    </div>
    <VPageState
      v-else-if="busy"
      state="loading"
      title="正在读取权威状态"
      message="请稍候。"
    />
    <VPageState
      v-else-if="section !== 'home' && rows.length === 0"
      state="empty"
      title="当前没有项目"
      message="没有可执行项目时仍可返回首页或打开帮助。"
    />
    <div
      v-else-if="section !== 'home'"
      class="cards"
      aria-live="polite"
    >
      <article
        v-for="row in rows"
        :key="String(row.id ?? row.task_code ?? row.journey_code ?? row.route_code ?? row.title)"
      >
        <VStatusBadge
          :status="row.state === 'blocked' ? 'warning' : 'info'"
          :label="String(row.state ?? row.category ?? row.source_module ?? '可查看')"
        /><h2>{{ localized(row.title_i18n) || row.title || row.task_code || row.journey_code || row.document_code }}</h2><p>{{ localized(row.description_i18n) || row.summary || row.body_markdown || row.current_step_code || '查看当前状态和可用下一步。' }}</p><RouterLink
          v-if="row.action_route_code || row.route_path || row.route_code"
          :to="pathFor(row)"
        >
          继续或查看状态
        </RouterLink>
      </article>
    </div>
    <footer class="support-footer">
      <RouterLink :to="`/${locale}/help`">
        查看帮助
      </RouterLink><button
        v-if="auth.user"
        type="button"
        @click="sendFeedback"
      >
        找不到下一步
      </button><RouterLink :to="`/${locale}/contact`">
        联系支持
      </RouterLink>
    </footer>
  </section>
</template>

<style scoped>.experience-page{display:grid;gap:var(--vav-density-page-gap);max-width:var(--vav-layout-content-wide);margin:auto;padding:var(--vav-density-page-gap)}header{display:flex;justify-content:space-between;align-items:end;gap:var(--vav-space-5)}.eyebrow{color:var(--vav-color-action-primary);font-weight:700;letter-spacing:.08em}nav,.support-footer{display:flex;flex-wrap:wrap;gap:var(--vav-space-3)}nav a,.support-footer a,.support-footer button{min-height:var(--vav-control-min-height);display:inline-flex;align-items:center;padding:var(--vav-space-2) var(--vav-space-3);border:1px solid var(--vav-color-border);border-radius:var(--vav-radius-pill);background:var(--vav-color-surface-raised);color:var(--vav-color-text);text-decoration:none}.metrics,.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));gap:var(--vav-space-4)}article{padding:var(--vav-component-card-padding);border:1px solid var(--vav-color-border);border-radius:var(--vav-component-card-radius);background:var(--vav-color-surface-raised)}article.wide{grid-column:span 2}.search-form{display:grid;gap:var(--vav-space-2)}.search-form div{display:grid;grid-template-columns:1fr auto;gap:var(--vav-space-2)}input{min-height:var(--vav-control-min-height);border:1px solid var(--vav-color-border);border-radius:var(--vav-radius-md);padding:var(--vav-space-2)}@media(max-width:48rem){header{align-items:start;flex-direction:column}article.wide{grid-column:auto}.search-form div{grid-template-columns:1fr}}</style>
