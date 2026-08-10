<script setup lang="ts">
import { ref } from "vue";
import { AdminDataTable, EntityTimeline, ReviewWorkbench } from "@vav/ui-admin";
import { VAlert, VButton, VFormField, VModal, VPageState, VSkipLink, VStatusBadge, applyUiPreferences, type VavDensity, type VavTheme } from "@vav/ui-core";
import { StickyActionBar, UserPageLayout } from "@vav/ui-user";

const theme = ref<VavTheme>("light");
const density = ref<VavDensity>("comfortable");
const modalOpen = ref(false);
const selected = ref<string[]>([]);
const rows = [{ id: "synthetic-01", name: "示例规则 A", status: "待复核" }, { id: "synthetic-02", name: "示例规则 B", status: "已批准" }];
const timeline = [{ id: "1", title: "提交变更", at: "2026-08-06T08:00:00Z", actor: "演示审核员" }, { id: "2", title: "自动检查通过", at: "2026-08-06T08:03:00Z" }];
function updatePreferences() { applyUiPreferences(document.documentElement, theme.value, density.value); }
updatePreferences();
</script>

<template>
  <VSkipLink />
  <header class="catalog-nav"><strong>VAV 设计系统</strong><nav aria-label="目录"><a href="#foundations">基础</a><a href="#components">组件</a><a href="#patterns">模式</a></nav></header>
  <main id="main-content" class="catalog-shell">
    <section class="catalog-hero"><div><p class="eyebrow">Batch 22 · 受治理的 UI 基础设施</p><h1>统一、可访问、可审计的界面语言</h1><p>设计 token、共享组件、页面状态和审核模式由同一质量门管理。</p></div><div class="preference-panel"><label>主题<select v-model="theme" @change="updatePreferences"><option value="light">浅色</option><option value="dark">深色</option><option value="high-contrast">高对比</option></select></label><label>密度<select v-model="density" @change="updatePreferences"><option value="comfortable">舒适</option><option value="compact">紧凑</option></select></label></div></section>

    <section id="foundations" aria-labelledby="foundations-title"><h2 id="foundations-title">基础与状态</h2><div class="swatches"><article><span class="swatch primary" /><strong>主要操作</strong><code>color.actionPrimary</code></article><article><span class="swatch success" /><strong>成功</strong><code>color.success</code></article><article><span class="swatch warning" /><strong>警告</strong><code>color.warning</code></article><article><span class="swatch danger" /><strong>危险</strong><code>color.danger</code></article></div></section>

    <section id="components" aria-labelledby="components-title"><h2 id="components-title">基础组件</h2><div class="component-grid"><article><h3>操作</h3><div class="row"><VButton @click="modalOpen = true">打开确认</VButton><VButton variant="secondary">次要操作</VButton><VButton variant="danger">危险操作</VButton></div></article><article><h3>状态</h3><div class="row"><VStatusBadge status="success" label="已通过" /><VStatusBadge status="warning" label="需复核" /><VStatusBadge status="danger" label="已阻断" /></div></article><article><h3>消息</h3><VAlert tone="warning" title="发布前仍需人工复核">自动检查不能替代辅助技术和真实设备验证。</VAlert></article><article><h3>字段</h3><VFormField v-slot="field" label="基线名称" hint="使用稳定、可搜索的名称" required><input v-bind="field" /></VFormField></article></div></section>

    <section id="patterns" aria-labelledby="patterns-title"><h2 id="patterns-title">用户端与管理端模式</h2><UserPageLayout title="响应式用户页面" description="阅读宽度、动作区和安全区域由 token 驱动"><VPageState state="partial" title="部分数据可用" message="已显示缓存结果；网络恢复后会自动刷新。" /></UserPageLayout><AdminDataTable caption="合成审核记录" :columns="[{ key: 'name', label: '名称', priority: 'primary' }, { key: 'status', label: '状态' }]" :rows="rows" row-key="id" :selected="selected" @select="selected = $event" /><EntityTimeline :items="timeline" /><ReviewWorkbench title="视觉基线审核"><template #before><article><h3>变更前</h3><p>已批准基线。</p></article></template><template #after><article><h3>变更后</h3><p>候选截图。</p></article></template><template #evidence><VStatusBadge status="warning" label="等待双人复核" /></template></ReviewWorkbench><StickyActionBar><VButton variant="secondary">保存草稿</VButton><VButton>提交审核</VButton></StickyActionBar></section>
  </main>
  <VModal :open="modalOpen" title="确认设计变更" @close="modalOpen = false" @confirm="modalOpen = false"><p>此动作只演示焦点管理，不会写入真实数据。</p></VModal>
</template>
