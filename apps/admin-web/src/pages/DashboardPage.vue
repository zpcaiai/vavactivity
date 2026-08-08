<script setup lang="ts">
const metrics = [
  { label: "运行状态", value: "就绪", note: "API、数据库与队列健康检查" },
  { label: "待决策项", value: "9", note: "全部保持 undecided / 关闭" },
  { label: "业务数据", value: "0", note: "未生成演示用户或虚假交易" },
  { label: "审计保护", value: "只追加", note: "数据库触发器拒绝更新和删除" }
];

const gates = [
  { label: "身份认证与 RBAC", status: "Batch 2" },
  { label: "目录与交易闭环", status: "Batch 4–5" },
  { label: "AI 风险转介", status: "Batch 9–10" },
  { label: "婚恋匹配闭环", status: "Batch 13–18" }
];
</script>

<template>
  <div class="dashboard">
    <section class="metric-grid">
      <article
        v-for="metric in metrics"
        :key="metric.label"
        class="metric-card"
      >
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
        <p>{{ metric.note }}</p>
      </article>
    </section>

    <section class="dashboard-grid">
      <article class="panel">
        <div class="panel-heading">
          <div>
            <p class="admin-kicker">
              DELIVERY MAP
            </p>
            <h2>能力开放顺序</h2>
          </div>
          <el-tag
            type="warning"
            effect="plain"
          >
            Fail closed
          </el-tag>
        </div>
        <div class="gate-list">
          <div
            v-for="(gate, index) in gates"
            :key="gate.label"
          >
            <span>0{{ index + 1 }}</span>
            <strong>{{ gate.label }}</strong>
            <small>{{ gate.status }}</small>
          </div>
        </div>
      </article>

      <article class="panel decision-panel">
        <div class="panel-heading">
          <div>
            <p class="admin-kicker">
              DECISIONS
            </p>
            <h2>未决政策保护</h2>
          </div>
        </div>
        <p>
          收款主体、首发地区、首发语言、会员方案、联系方式交换、视频托管、辅导排班、
          AI 知识授权与试点人群均未设置生产默认值。
        </p>
        <RouterLink to="/admin/settings">
          查看系统设置 →
        </RouterLink>
      </article>
    </section>
  </div>
</template>
