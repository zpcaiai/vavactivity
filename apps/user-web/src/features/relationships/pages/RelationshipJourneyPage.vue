<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { relationshipsApi, type RelationshipRow } from "@/features/relationships/api";

const route = useRoute();
const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const journeyId = computed(() => String(route.params.id ?? ""));
const journeys = ref<RelationshipRow[]>([]);
const detail = ref<RelationshipRow>();
const timeline = ref<RelationshipRow[]>([]);
const proposals = ref<RelationshipRow[]>([]);
const milestones = ref<RelationshipRow[]>([]);
const reflections = ref<RelationshipRow[]>([]);
const targetStage = ref("initial_contact");
const message = ref("");
const title = ref("");
const reflection = ref("");
const privateReason = ref("");
const visibleMessage = ref("");
const busy = ref(false);
const error = ref("");
const notice = ref("");

const stages = ["introduction_accepted", "initial_contact", "getting_to_know", "intentional_getting_to_know", "dating", "exclusive_relationship", "relationship_confirmed"];

async function load() {
  busy.value = true;
  error.value = "";
  try {
    if (!journeyId.value) journeys.value = await relationshipsApi.list();
    else {
      [detail.value, timeline.value, proposals.value, milestones.value, reflections.value] = await Promise.all([
        relationshipsApi.detail(journeyId.value), relationshipsApi.timeline(journeyId.value), relationshipsApi.proposals(journeyId.value), relationshipsApi.milestones(journeyId.value), relationshipsApi.reflections(journeyId.value)
      ]);
      const index = stages.indexOf(String(detail.value.current_stage_code));
      targetStage.value = stages[Math.min(index + 1, stages.length - 1)] ?? "initial_contact";
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "关系旅程加载失败";
  } finally { busy.value = false; }
}

async function run(action: () => Promise<unknown>, successMessage: string) {
  busy.value = true;
  error.value = "";
  try { await action(); notice.value = successMessage; await load(); notice.value = successMessage; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "操作失败"; }
  finally { busy.value = false; }
}

function propose() { return run(() => relationshipsApi.proposeStage(journeyId.value, targetStage.value, message.value), "阶段提议已发送；只有对方确认后才会推进。"); }
function decide(row: RelationshipRow, accept: boolean) { return run(() => relationshipsApi.decideProposal(String(row.id), accept ? "accept" : "decline", Number(row.version)), accept ? "双方已确认新的阶段。" : "已婉拒；关系阶段没有改变。"); }
function pause() { if (window.confirm("暂停会立即生效，恢复需要双方再次确认。继续吗？")) return run(() => relationshipsApi.pause(journeyId.value, privateReason.value, visibleMessage.value), "旅程已暂停。"); }
function resume() { return run(() => relationshipsApi.requestResume(journeyId.value), "恢复请求已发送；不会自动恢复。"); }
function endJourney() { if (window.confirm("结束会立即撤销联系方式授权且无法由管理员恢复。确定结束吗？")) return run(() => relationshipsApi.end(journeyId.value, "member_choice", privateReason.value, visibleMessage.value), "关系旅程已结束。"); }
function addMilestone() { if (title.value.trim()) return run(() => relationshipsApi.createMilestone(journeyId.value, { milestone_type: "personal", title: title.value, visibility: "shared" }), "里程碑已保存。"); }
function saveReflection() { if (reflection.value.trim()) return run(() => relationshipsApi.reflect(journeyId.value, reflection.value), "私密反思已加密保存，不会向对方展示。"); }

watch(() => route.fullPath, load);
onMounted(load);
</script>

<template>
  <section class="journey-page">
    <p class="eyebrow">
      BATCH 16 · MUTUAL JOURNEY
    </p>
    <h1>关系旅程</h1>
    <p class="intro">
      阶段推进需要双方确认；任何一方都可以暂停或结束。这里不会对关系作量化评价，也不会用提醒制造压力。
    </p>
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

    <div
      v-if="!journeyId"
      class="cards"
    >
      <RouterLink
        v-for="item in journeys"
        :key="String(item.journey_id)"
        class="card"
        :to="`/${locale}/account/relationships/${item.journey_id}`"
      >
        <strong>{{ item.current_stage_code }}</strong><span>{{ item.status }}</span><small>{{ item.journey_number }}</small>
      </RouterLink>
      <p v-if="!busy && journeys.length === 0">
        接受一份认识邀请后，双方的关系旅程会出现在这里。
      </p>
    </div>

    <template v-else-if="detail">
      <RouterLink :to="`/${locale}/account/relationships`">
        ← 返回全部旅程
      </RouterLink>
      <article class="panel hero">
        <div><small>当前阶段</small><h2>{{ detail.current_stage_code }}</h2><p>状态：{{ detail.status }}</p></div><p>对方：{{ detail.partner_user_id }}</p>
      </article>
      <div class="grid">
        <article class="panel">
          <h2>双方确认阶段</h2><select v-model="targetStage">
            <option
              v-for="stage in stages"
              :key="stage"
              :value="stage"
            >
              {{ stage }}
            </option>
          </select><textarea
            v-model="message"
            maxlength="2000"
            placeholder="可选：温和说明你的提议"
          /><button
            :disabled="busy || detail.status !== 'active'"
            @click="propose"
          >
            提出阶段变化
          </button><div
            v-for="proposal in proposals"
            :key="String(proposal.id)"
            class="row"
          >
            <span>{{ proposal.from_stage_code }} → {{ proposal.to_stage_code }} · {{ proposal.status }}</span><template v-if="proposal.status === 'pending' && proposal.recipient_user_id !== detail.partner_user_id">
              <button @click="decide(proposal, true)">
                同意
              </button><button
                class="quiet"
                @click="decide(proposal, false)"
              >
                婉拒
              </button>
            </template>
          </div>
        </article>
        <article class="panel">
          <h2>暂停、恢复或结束</h2><textarea
            v-model="visibleMessage"
            maxlength="2000"
            placeholder="给对方可见的可选说明"
          /><textarea
            v-model="privateReason"
            maxlength="4000"
            placeholder="只对你可见的私人原因"
          /><div class="actions">
            <button
              v-if="detail.status === 'active'"
              class="quiet"
              @click="pause"
            >
              立即暂停
            </button><button
              v-if="detail.status === 'paused'"
              @click="resume"
            >
              请求恢复
            </button><button
              v-if="!['ended','archived'].includes(String(detail.status))"
              class="danger"
              @click="endJourney"
            >
              结束关系旅程
            </button>
          </div>
        </article>
        <article class="panel">
          <h2>共同里程碑</h2><input
            v-model="title"
            maxlength="160"
            placeholder="例如：第一次共同参加活动"
          ><button @click="addMilestone">
            保存共享里程碑
          </button><div
            v-for="item in milestones"
            :key="String(item.milestone_id)"
            class="row"
          >
            <strong>{{ item.title }}</strong><small>{{ item.visibility }}</small>
          </div>
        </article>
        <article class="panel">
          <h2>我的私密反思</h2><p>反思只对你可见；默认不会交给 AI 处理。</p><textarea
            v-model="reflection"
            maxlength="10000"
            placeholder="写下只属于你的想法"
          /><button @click="saveReflection">
            加密保存
          </button><div
            v-for="item in reflections"
            :key="String(item.reflection_id)"
            class="reflection"
          >
            {{ item.reflection }}
          </div>
        </article>
      </div>
      <article class="panel">
        <h2>旅程时间线</h2><ol>
          <li
            v-for="event in timeline"
            :key="String(event.id)"
          >
            <strong>{{ event.event_type }}</strong><span>{{ event.from_stage_code }}<template v-if="event.to_stage_code"> → {{ event.to_stage_code }}</template></span>
          </li>
        </ol>
      </article>
    </template>
  </section>
</template>

<style scoped>
.journey-page{max-width:1120px;margin:0 auto;padding:3rem 1.25rem 5rem}.eyebrow{letter-spacing:.14em;color:#7b5d38}.intro{max-width:760px;color:#5e6265}.cards,.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}.card,.panel{display:flex;flex-direction:column;gap:.75rem;padding:1.25rem;border:1px solid #dfd8cc;border-radius:18px;background:#fff;color:inherit;text-decoration:none}.hero{margin:1.25rem 0;background:#f7f1e7}.row,.actions{display:flex;gap:.65rem;align-items:center;flex-wrap:wrap}.row{padding:.65rem 0;border-top:1px solid #eee}textarea,input,select{box-sizing:border-box;width:100%;padding:.75rem;border:1px solid #c9c1b5;border-radius:10px;font:inherit}button{padding:.7rem 1rem;border:0;border-radius:999px;background:#365f50;color:#fff;cursor:pointer}.quiet{background:#6f7772}.danger{background:#9b3b38}.alert{padding:.8rem;border-radius:10px}.error{background:#fde8e7}.notice{background:#e7f4ed}.reflection{padding:.75rem;background:#f7f7f4;border-radius:10px}ol{display:grid;gap:.75rem}li{display:flex;justify-content:space-between;gap:1rem}
</style>
