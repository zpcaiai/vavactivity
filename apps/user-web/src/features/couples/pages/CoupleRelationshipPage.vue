<script setup lang="ts">
import { VAlert, VButton, VCard, VChip, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { couplesApiClient } from "@/features/couples/api";
import type {
  CoupleInvitation,
  CoupleRelationship,
  RelationshipKind
} from "@/features/couples/types";

const { t } = useI18n();

const relationship = ref<CoupleRelationship | null>(null);
const invitations = ref<CoupleInvitation[]>([]);
const loading = ref(true);
const busy = ref(false);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);

const inviteeId = ref("");
const kind = ref<RelationshipKind>("dating");
const note = ref("");
const unbindReason = ref("");

const KINDS: RelationshipKind[] = ["dating", "engaged", "married"];

async function load() {
  loading.value = true;
  error.value = null;
  try {
    // No active binding is a normal state, not an error, so a 404 here clears
    // the panel rather than failing the page.
    relationship.value = await couplesApiClient.relationship().catch(() => null);
    invitations.value = (await couplesApiClient.invitations()).items;
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    loading.value = false;
  }
}

async function invite() {
  busy.value = true;
  error.value = null;
  notice.value = null;
  try {
    await couplesApiClient.createInvitation({
      invitee_user_id: inviteeId.value.trim(),
      relationship_kind: kind.value,
      note: note.value.trim() || null
    });
    // Sending binds nobody: the invitation still has to be accepted. Saying so
    // avoids a member believing the relationship is already recorded.
    notice.value = t("couples.invite.sentPending");
    inviteeId.value = "";
    note.value = "";
    await load();
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    busy.value = false;
  }
}

async function respond(invitation: CoupleInvitation, decision: "accept" | "reject") {
  busy.value = true;
  error.value = null;
  try {
    await couplesApiClient.respond(invitation.invitation_id, decision);
    notice.value = t(`couples.invite.responded.${decision}`);
    await load();
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    busy.value = false;
  }
}

async function cancel(invitation: CoupleInvitation) {
  busy.value = true;
  try {
    await couplesApiClient.cancel(invitation.invitation_id);
    await load();
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    busy.value = false;
  }
}

async function unbind() {
  busy.value = true;
  error.value = null;
  try {
    await couplesApiClient.unbind(unbindReason.value.trim());
    notice.value = t("couples.relationship.unbound");
    unbindReason.value = "";
    await load();
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    busy.value = false;
  }
}

function expiresLabel(invitation: CoupleInvitation): string | null {
  if (!invitation.expires_at) return null;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(invitation.expires_at));
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    :title="t('couples.title')"
    :description="t('couples.description')"
    :eyebrow="t('couples.eyebrow')"
  >
    <VPageState
      v-if="loading"
      state="loading"
      :title="t('common.loading')"
      :message="t('couples.loadingMessage')"
    />

    <template v-else>
      <VAlert
        v-if="error"
        tone="danger"
        :title="t('common.errorTitle')"
      >
        {{ error }}
      </VAlert>
      <VAlert
        v-if="notice"
        tone="success"
        :title="t('common.saved')"
      >
        {{ notice }}
      </VAlert>

      <VCard v-if="relationship">
        <h2 class="couples__heading">
          {{ t("couples.relationship.heading") }}
        </h2>
        <VChip
          tone="success"
          :label="t(`couples.kind.${relationship.relationship_kind}`)"
        />
        <p class="couples__note">
          {{ t("couples.relationship.partner", { id: relationship.partner_user_id }) }}
        </p>

        <label
          class="couples__label"
          for="unbind-reason"
        >
          {{ t("couples.relationship.unbindReasonLabel") }}
        </label>
        <input
          id="unbind-reason"
          v-model="unbindReason"
          class="couples__input"
          type="text"
          maxlength="1000"
        >
        <p class="couples__note">
          {{ t("couples.relationship.unbindHint") }}
        </p>
        <VButton
          variant="danger"
          :loading="busy"
          @click="unbind"
        >
          {{ t("couples.relationship.unbind") }}
        </VButton>
      </VCard>

      <VCard v-else>
        <h2 class="couples__heading">
          {{ t("couples.invite.heading") }}
        </h2>
        <!--
          COUPLE-001: an invitation is half of a two-sided binding. Saying this
          up front stops a member from treating "sent" as "bound".
        -->
        <p class="couples__note">
          {{ t("couples.invite.explanation") }}
        </p>

        <label
          class="couples__label"
          for="invitee"
        >{{ t("couples.invite.inviteeLabel") }}</label>
        <input
          id="invitee"
          v-model="inviteeId"
          class="couples__input"
          type="text"
        >

        <label
          class="couples__label"
          for="kind"
        >{{ t("couples.invite.kindLabel") }}</label>
        <select
          id="kind"
          v-model="kind"
          class="couples__input"
        >
          <option
            v-for="option in KINDS"
            :key="option"
            :value="option"
          >
            {{ t(`couples.kind.${option}`) }}
          </option>
        </select>

        <label
          class="couples__label"
          for="note"
        >{{ t("couples.invite.noteLabel") }}</label>
        <input
          id="note"
          v-model="note"
          class="couples__input"
          type="text"
          maxlength="500"
        >
        <p class="couples__note">
          {{ t("couples.invite.noteHint") }}
        </p>

        <VButton
          :loading="busy"
          :disabled="!inviteeId.trim()"
          @click="invite"
        >
          {{ t("couples.invite.send") }}
        </VButton>
      </VCard>

      <VCard>
        <h2 class="couples__heading">
          {{ t("couples.invitations.heading") }}
        </h2>
        <p
          v-if="!invitations.length"
          class="couples__note"
        >
          {{ t("couples.invitations.empty") }}
        </p>
        <ul
          v-else
          class="couples__list"
        >
          <li
            v-for="invitation in invitations"
            :key="invitation.invitation_id"
          >
            <div class="couples__invitation">
              <div>
                <p class="couples__invitation-title">
                  {{ t(`couples.invitations.direction.${invitation.direction}`) }}
                  · {{ t(`couples.kind.${invitation.relationship_kind}`) }}
                </p>
                <p class="couples__note">
                  {{ invitation.counterparty_user_id }}
                </p>
                <p
                  v-if="invitation.note"
                  class="couples__note"
                >
                  {{ invitation.note }}
                </p>
                <p
                  v-if="expiresLabel(invitation)"
                  class="couples__note"
                >
                  {{ t("couples.invitations.expiresAt", { time: expiresLabel(invitation) }) }}
                </p>
              </div>
              <div class="couples__invitation-side">
                <VChip
                  :tone="invitation.status === 'pending' ? 'warning' : 'neutral'"
                  :label="t(`couples.invitations.status.${invitation.status}`)"
                />
                <!-- `actionable` is the server's call, not a local guess. -->
                <template v-if="invitation.actionable && invitation.direction === 'incoming'">
                  <VButton
                    :loading="busy"
                    @click="respond(invitation, 'accept')"
                  >
                    {{ t("couples.invitations.accept") }}
                  </VButton>
                  <VButton
                    variant="secondary"
                    :loading="busy"
                    @click="respond(invitation, 'reject')"
                  >
                    {{ t("couples.invitations.reject") }}
                  </VButton>
                </template>
                <VButton
                  v-else-if="invitation.actionable"
                  variant="secondary"
                  :loading="busy"
                  @click="cancel(invitation)"
                >
                  {{ t("couples.invitations.cancel") }}
                </VButton>
              </div>
            </div>
          </li>
        </ul>
      </VCard>
    </template>
  </UserPageLayout>
</template>

<style scoped>
.couples__heading {
  margin: 0 0 var(--vav-space-2);
  font-size: var(--vav-font-size-lg);
  color: var(--vav-color-text-primary);
}

.couples__note {
  margin: var(--vav-space-1) 0 0;
  color: var(--vav-color-text-secondary);
}

.couples__label {
  display: block;
  margin-top: var(--vav-space-3);
  font-weight: var(--vav-font-weight-medium);
  color: var(--vav-color-text-primary);
}

.couples__input {
  width: 100%;
  margin-top: var(--vav-space-1);
  padding: var(--vav-space-2) var(--vav-space-3);
  border: 1px solid var(--vav-color-border-default);
  border-radius: var(--vav-radius-md);
  background: var(--vav-color-surface-default);
  color: var(--vav-color-text-primary);
}

.couples__list {
  display: grid;
  gap: var(--vav-space-3);
  margin: var(--vav-space-2) 0 0;
  padding: 0;
  list-style: none;
}

.couples__invitation {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--vav-space-4);
}

.couples__invitation-title {
  margin: 0;
  font-weight: var(--vav-font-weight-medium);
  color: var(--vav-color-text-primary);
}

.couples__invitation-side {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--vav-space-2);
  flex-shrink: 0;
}
</style>
