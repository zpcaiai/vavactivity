<script setup lang="ts">
const isDevelopment = import.meta.env.DEV;
</script>

<template>
  <main class="admin-login">
    <section class="login-story">
      <span
        class="brand-mark login-mark"
        aria-hidden="true"
      >V</span>
      <p class="admin-kicker">
        VAV OPERATIONS
      </p>
      <h1>让每一次运营动作，都有边界和记录。</h1>
      <p>
        管理端与用户端完全分离。正式登录将在身份与 RBAC 批次接入，所有权限由后端验证。
      </p>
    </section>
    <section class="login-card">
      <span class="login-status">FOUNDATION READY</span>
      <h2>运营人员登录</h2>
      <p>当前版本不接收账户或密码，避免在认证服务完成前形成不安全的临时入口。</p>
      <el-alert
        title="开发环境可预览工作台框架；生产构建会自动关闭预览通道。"
        type="info"
        :closable="false"
        show-icon
      />
      <RouterLink
        v-if="isDevelopment"
        class="preview-link"
        to="/admin/dashboard"
      >
        进入工程预览
      </RouterLink>
    </section>
  </main>
</template>
