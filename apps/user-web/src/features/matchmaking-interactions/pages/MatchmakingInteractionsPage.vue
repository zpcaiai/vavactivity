<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  matchmakingInteractionsApi,
  type InteractionRow
} from "@/features/matchmaking-interactions/api";
import { privacyApi } from "@/features/privacy/api";

type ContactPoint = {
  id: string;
  contact_type: string;
  masked_value: string;
  status: string;
};

const route = useRoute();
const section = computed(() => String(route.meta.interactionSection ?? "matches"));
const detailId = computed(() => String(route.params.id ?? ""));
const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const rows = ref<InteractionRow[]>([]);
const detail = ref<InteractionRow>();
const contacts = ref<ContactPoint[]>([]);
const selectedContactIds = ref<string[]>([]);
const invitationMessage = ref("");
const declineReason = ref("");
const revealed = ref<Record<string, string>>({});
const busy = ref(false);
const error = ref("");
const notice = ref("");

const navigation = computed(() => [
  ["matches", `/${locale.value}/account/matchmaking/matches`, "双方互选"],
  ["invitations", `/${locale.value}/account/matchmaking/invitations`, "认识邀请"],
  ["likes", `/${locale.value}/account/matchmaking/likes`, "我的喜欢"],
  ["skips", `/${locale.value}/account/matchmaking/skips`, "暂时跳过"]
]);

async function load() {
  busy.value = true;
  error.value = "";
  notice.value = "";
  rows.value = [];
  detail.value = undefined;
  try {
    if (section.value === "likes") rows.value = await matchmakingInteractionsApi.outgoingLikes();
    else if (section.value === "skips") rows.value = await matchmakingInteractionsApi.skips();
    else if (section.value === "invitations") {
      rows.value = await matchmakingInteractionsApi.invitations();
      if (detailId.value) detail.value = await matchmakingInteractionsApi.invitation(detailId.value);
    } else if (section.value === "contact") {
      detail.value = await matchmakingInteractionsApi.contactExchange(detailId.value);
      const result = await privacyApi<{ items: ContactPoint[] }>("/account/contact-points");
      contacts.value = result.items.filter((item) => item.status === "verified");
      selectedContactIds.value = contacts.value.map((item) => item.id);
    } else {
      rows.value = await matchmakingInteractionsApi.matches();
      if (detailId.value) detail.value = await matchmakingInteractionsApi.match(detailId.value);
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "互动记录加载失败";
  } finally {
    busy.value = false;
  }
}

async function run(action: () => Promise<unknown>, message: string) {
  busy.value = true;
  error.value = "";
  try {
    await action();
    notice.value = message;
    await load();
    notice.value = message;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "互动操作失败";
  } finally {
    busy.value = false;
  }
}

function withdrawLike(row: InteractionRow) {
  if (!row.like_id || !window.confirm("确定撤回这次尚未互选的喜欢吗？")) return;
  return run(() => matchmakingInteractionsApi.withdrawLike(row.like_id!), "喜欢已撤回。对方不会收到单向喜欢通知。");
}

function withdrawSkip(row: InteractionRow) {
  if (!row.skip_id) return;
  return run(() => matchmakingInteractionsApi.withdrawSkip(row.skip_id!), "已撤销这次暂时跳过。");
}

function sendInvitation() {
  if (!detail.value?.mutual_match_id) return;
  if (!window.confirm("发送后对方可以接受或婉拒；这不会自动公开联系方式。确定发送吗？")) return;
  return run(
    () => matchmakingInteractionsApi.sendInvitation(detail.value!.mutual_match_id!, invitationMessage.value),
    "认识邀请已发送。"
  );
}

function decideInvitation(action: "accept" | "decline" | "cancel") {
  if (!detail.value?.invitation_id || !detail.value.invitation_version) return;
  if (!window.confirm(action === "accept" ? "接受后仍需双方另行同意才能交换联系方式。确定接受吗？" : "确定继续这个操作吗？")) return;
  return run(
    () => matchmakingInteractionsApi.invitationDecision(
      detail.value!.invitation_id!,
      action,
      detail.value!.invitation_version!,
      declineReason.value || undefined
    ),
    action === "accept" ? "邀请已接受。" : action === "decline" ? "已婉拒；原因不会显示给对方。" : "邀请已取消。"
  );
}

function requestExchange() {
  if (!detail.value?.mutual_match_id) return;
  return run(
    () => matchmakingInteractionsApi.requestContactExchange(detail.value!.mutual_match_id!),
    "联系方式交换请求已建立；任何一方单独同意都不会公开信息。"
  );
}

function consent(platformOnly = false) {
  if (!detailId.value) return;
  return run(
    () => matchmakingInteractionsApi.consentContactExchange(
      detailId.value,
      platformOnly ? [] : selectedContactIds.value,
      platformOnly
    ),
    platformOnly ? "已选择仅在平台内联系。" : "你的选择已记录；双方同意前不会公开任何联系方式。"
  );
}

async function reveal(contact: Record<string, unknown>) {
  const contactPointId = String(contact.contact_point_id ?? "");
  if (!contactPointId || !detailId.value) return;
  try {
    const token = await matchmakingInteractionsApi.revealToken(detailId.value, contactPointId);
    const result = await matchmakingInteractionsApi.reveal(detailId.value, token.reveal_token);
    revealed.value[contactPointId] = result.value;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "联系方式查看失败";
  }
}

watch(() => route.fullPath, load);
onMounted(load);
</script>

<template>
  <section class="interactions">
    <p class="eyebrow">
      BATCH 15 · MEMBER CHOICE
    </p>
    <h1>互选与认识邀请</h1>
    <p class="intro">
      单向喜欢、跳过原因和婉拒原因都保持私密。互选不等于交换联系方式；只有双方分别确认后，才会建立可撤回的访问授权。
    </p>

    <nav
      class="links"
      aria-label="互动中心"
    >
      <RouterLink
        v-for="item in navigation"
        :key="item[0]"
        :to="item[1]"
      >
        {{ item[2] }}
      </RouterLink>
    </nav>

    <p
      v-if="error"
      role="alert"
      class="alert error"
    >
      {{ error }}
    </p>
    <p
      v-if="notice"
      role="status"
      class="alert notice"
    >
      {{ notice }}
    </p>
    <p v-if="busy">
      正在处理…
    </p>

    <article
      v-if="detail && section === 'matches'"
      class="panel"
    >
      <h2>互选详情</h2>
      <p>状态：{{ detail.status }}</p>
      <p>编号：{{ detail.match_number }}</p>
      <p>对方：{{ detail.other_member_user_id }}</p>
      <label>邀请留言（不得包含联系方式）<textarea
        v-model="invitationMessage"
        maxlength="500"
      /></label>
      <button
        v-if="!detail.invitation_status"
        type="button"
        @click="sendInvitation"
      >
        发送认识邀请
      </button>
      <RouterLink
        v-if="detail.invitation_id"
        :to="`/${locale}/account/matchmaking/invitations/${detail.invitation_id}`"
      >
        查看邀请
      </RouterLink>
      <button
        v-if="detail.status === 'introduction_accepted' && !detail.contact_exchange_id"
        type="button"
        @click="requestExchange"
      >
        请求双方确认联系方式
      </button>
      <RouterLink
        v-if="detail.contact_exchange_id"
        :to="`/${locale}/account/matchmaking/contact-exchanges/${detail.contact_exchange_id}`"
      >
        管理联系方式交换
      </RouterLink>
    </article>

    <article
      v-else-if="detail && section === 'invitations'"
      class="panel"
    >
      <h2>认识邀请</h2>
      <p>状态：{{ detail.status }}</p>
      <p v-if="detail.message">
        留言：{{ detail.message }}
      </p>
      <p v-if="detail.outcome_note">
        {{ detail.outcome_note }}
      </p>
      <template v-if="detail.status === 'pending' && detail.role === 'recipient'">
        <button
          type="button"
          @click="decideInvitation('accept')"
        >
          接受邀请
        </button>
        <label>婉拒原因（仅自己和获授权安全人员可见）<input
          v-model="declineReason"
          maxlength="128"
        ></label>
        <button
          type="button"
          @click="decideInvitation('decline')"
        >
          婉拒
        </button>
      </template>
      <button
        v-if="detail.status === 'pending' && detail.role === 'sender'"
        type="button"
        @click="decideInvitation('cancel')"
      >
        取消邀请
      </button>
    </article>

    <article
      v-else-if="detail && section === 'contact'"
      class="panel"
    >
      <h2>联系方式交换确认</h2>
      <p>状态：{{ detail.status }}</p>
      <p>你的选择：{{ (detail.your_consent as Record<string, unknown>)?.status }}</p>
      <p>{{ detail.other_member_has_consented ? '对方已完成自己的确认。' : '对方尚未完成确认；当前不会公开任何联系方式。' }}</p>
      <fieldset>
        <legend>选择经过验证且愿意分享的联系方式</legend>
        <label
          v-for="contact in contacts"
          :key="contact.id"
        >
          <input
            v-model="selectedContactIds"
            type="checkbox"
            :value="contact.id"
          >
          {{ contact.contact_type }} · {{ contact.masked_value }}
        </label>
      </fieldset>
      <button
        type="button"
        :disabled="!selectedContactIds.length"
        @click="consent(false)"
      >
        确认所选联系方式
      </button>
      <button
        type="button"
        @click="consent(true)"
      >
        仅在平台内联系
      </button>
      <button
        type="button"
        @click="run(() => matchmakingInteractionsApi.withdrawContactConsent(detailId), '联系方式同意已撤回，现有授权已撤销。')"
      >
        撤回同意
      </button>
      <ul>
        <li
          v-for="contact in (detail.contacts as Array<Record<string, unknown>> ?? [])"
          :key="String(contact.contact_point_id)"
        >
          {{ contact.type }} · {{ contact.masked_value ?? contact.state }}
          <button
            v-if="contact.state === 'available'"
            type="button"
            @click="reveal(contact)"
          >
            一次性查看
          </button>
          <strong v-if="revealed[String(contact.contact_point_id)]">{{ revealed[String(contact.contact_point_id)] }}</strong>
        </li>
      </ul>
    </article>

    <ul
      v-else
      class="list"
    >
      <li
        v-for="row in rows"
        :key="String(row.like_id ?? row.skip_id ?? row.mutual_match_id ?? row.invitation_id)"
      >
        <template v-if="section === 'likes'">
          <strong>喜欢</strong> · {{ row.status }} · {{ row.created_at }}
          <button
            v-if="row.status === 'active'"
            type="button"
            @click="withdrawLike(row)"
          >
            撤回
          </button>
        </template>
        <template v-else-if="section === 'skips'">
          <strong>{{ row.skip_type }}</strong> · {{ row.status }} · 冷却至 {{ row.cooldown_until }}
          <button
            v-if="row.status === 'active'"
            type="button"
            @click="withdrawSkip(row)"
          >
            撤销
          </button>
        </template>
        <RouterLink
          v-else-if="section === 'invitations'"
          :to="`/${locale}/account/matchmaking/invitations/${row.invitation_id}`"
        >
          {{ row.role }} · {{ row.status }}
        </RouterLink>
        <RouterLink
          v-else
          :to="`/${locale}/account/matchmaking/matches/${row.mutual_match_id}`"
        >
          互选 {{ row.match_number }} · {{ row.status }}
        </RouterLink>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.interactions { display: flex; flex-direction: column; gap: 1rem; padding: 2rem 0; }
.eyebrow { letter-spacing: .16em; font-size: .75rem; opacity: .65; }
.intro { max-width: 68ch; line-height: 1.7; }
.links { display: flex; flex-wrap: wrap; gap: 1rem; }
.panel, .list li { border: 1px solid rgba(0,0,0,.12); border-radius: .75rem; padding: 1rem; }
.panel { display: flex; flex-direction: column; align-items: flex-start; gap: .75rem; }
.panel label, fieldset { display: flex; flex-direction: column; gap: .4rem; width: min(100%, 38rem); }
.panel textarea { min-height: 7rem; }
.list { list-style: none; padding: 0; display: flex; flex-direction: column; gap: .75rem; }
.alert { padding: .75rem 1rem; border-radius: .5rem; }
.error { background: #fdecea; color: #8a1c12; }
.notice { background: #eaf6ec; color: #1c5a2a; }
button { padding: .45rem .9rem; border: 1px solid rgba(0,0,0,.2); border-radius: .5rem; background: white; cursor: pointer; }
</style>
