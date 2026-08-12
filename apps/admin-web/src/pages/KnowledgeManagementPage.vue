<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { formatAdminTableCell } from "@vav/ui-admin";

import { catalogApi } from "@/features/catalog/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

type Space = { id: string; space_code: string; name: string; purpose: string; status: string };
type Source = { id: string; space_id?: string; source_code: string; source_type: string; title: string; sensitivity: string; status: string };
type Document = { id: string; document_code: string; title: string; locale: string; status: string; current_version_id?: string | null };
type DocumentVersion = { id: string; version_number: number; status: string; mime_type: string; checksum_sha256: string; parse_quality_bps: number; published_at?: string | null };
type DocumentDetail = Document & { sensitivity: string; versions: DocumentVersion[] };
type Authorization = { id: string; source_id: string; document_id?: string | null; status: string; rights_holder_name: string; authorization_basis: string; citation_permission: string; valid_from: string; valid_until?: string | null; revoked_at?: string | null };
type AuthorizationImpact = { authorization_id: string; document_count: number; chunk_count: number; embedding_count: number; requires_index_repair: boolean };
type Finding = { id: string; finding_type: string; severity: string; blocks_publication: boolean; status: string; locator?: unknown; created_at: string };
type IndexVersion = { id: string; version_number: number; status: string; evaluation_status: string; previous_index_id?: string | null };
type Evaluation = { id: string; dataset_code: string; name: string; case_count: number };
type EvaluationRun = { id: string; index_version_id: string; status: string; total_cases: number; passed_cases: number; authorization_violations: number; acl_leakage_count: number };
type AuditEvent = { id: string; event_type: string; subject_type: string; subject_id: string; reason?: string | null; created_at: string };
type Result = { document_code: string; version_number: number; chunk_id: string; parent_chunk_id?: string | null; excerpt?: string | null; excerpt_sha256?: string | null; source_locator: Record<string, unknown> };
type ParsedBlock = { block_id: string; block_type: string; text?: string | null; page_number?: number | null; section_path: string[]; source_locator: Record<string, unknown> };

const auth = useAdminAuthStore();
const spaces = ref<Space[]>([]);
const sources = ref<Source[]>([]);
const documents = ref<Document[]>([]);
const authorizations = ref<Authorization[]>([]);
const indexes = ref<IndexVersion[]>([]);
const evaluations = ref<Evaluation[]>([]);
const evaluationRuns = ref<EvaluationRun[]>([]);
const auditEvents = ref<AuditEvent[]>([]);
const results = ref<Result[]>([]);
const parsedBlocks = ref<ParsedBlock[]>([]);
const parsingReport = ref<{ parser_name: string; quality_score_basis_points: number; requires_manual_review: boolean; warnings: unknown[] } | null>(null);
const query = ref("健康边界 尊重");
const locale = ref("zh-CN");
const error = ref("");
const notice = ref("");
const busy = ref(false);
const selectedSourceId = ref("");
const selectedFile = ref<File | null>(null);
const uploadCode = ref("");
const uploadTitle = ref("");
const selectedSpaceCode = ref("");
const selectedSpace = computed(() =>
  spaces.value.find((space) => space.space_code === selectedSpaceCode.value)
);

const canManageSpaces = computed(() => auth.hasPermission("knowledge.spaces.manage"));
const canManageSources = computed(() => auth.hasPermission("knowledge.sources.manage"));
const canApproveAuthorization = computed(() => auth.hasPermission("knowledge.authorizations.approve"));
const canManageAuthorization = computed(() => auth.hasPermission("knowledge.authorizations.manage"));
const canReadAuthorization = computed(() => auth.hasPermission("knowledge.authorizations.read"));
const canReviewDocument = computed(() => auth.hasPermission("knowledge.documents.review"));
const canPublishDocument = computed(() => auth.hasPermission("knowledge.documents.publish"));
const canManageIndex = computed(() => auth.hasPermission("knowledge.indexes.manage"));

/** Generic "confirm with a mandatory reason" dialog shared by governed actions. */
const reasonDialog = ref<{
  open: boolean;
  title: string;
  intent: string;
  reason: string;
  run?: (reason: string) => Promise<void>;
}>({ open: false, title: "", intent: "", reason: "" });

const spaceDialog = ref({
  open: false,
  space_code: "",
  name: "",
  purpose: "",
  default_locale: "zh-CN",
  allowed_roles: ""
});

const sourceDialog = ref({
  open: false,
  space_id: "",
  source_code: "",
  source_type: "upload",
  title: "",
  sensitivity: "internal"
});

const authorizationDialog = ref({
  open: false,
  scope: "document" as "document" | "source",
  document_id: "",
  source_id: "",
  allow_rag: true,
  allow_public_quote: false,
  allow_external_training: false,
  rights_holder_name: "VAV",
  authorization_basis: "owned_by_vav",
  citation_permission: "internal_reference_only",
  valid_from: "",
  valid_until: "",
  evidence_type: "written_license",
  evidence_reference: "",
  evidence_note: ""
});

const documentDrawer = ref(false);
const documentDetail = ref<DocumentDetail>();
const findings = ref<Finding[]>([]);
const findingsVersionId = ref("");
const findingResolution = ref<Record<string, { decision: string; resolution: string }>>({});
const publishForm = ref({ version_id: "", allowed_roles: "", reason: "" });
const impact = ref<AuthorizationImpact>();

const AUTHORIZATION_BASES = [
  { value: "owned_by_vav", label: "VAV 自有内容" },
  { value: "written_license", label: "书面授权许可" },
  { value: "public_domain", label: "公共领域" },
  { value: "contractual_permission", label: "合同约定许可" },
  { value: "user_supplied_authorized", label: "用户提供且已授权" }
];

const CITATION_PERMISSIONS = [
  { value: "none", label: "不可引用" },
  { value: "internal_reference_only", label: "仅内部引用" },
  { value: "short_public_excerpt", label: "可对外短摘录" },
  { value: "public_title_only", label: "仅可公开标题" }
];

const SOURCE_TYPES = ["upload", "cms", "course", "activity", "counseling", "faq"];

const FINDING_DECISIONS = [
  { value: "resolved", label: "已修复" },
  { value: "accepted_risk", label: "接受风险" },
  { value: "rejected", label: "误报驳回" }
];

function documentLabel(id?: string | null) {
  if (!id) return "整个来源";
  return documents.value.find((item) => item.id === id)?.document_code ?? id;
}

function sourceLabel(id?: string | null) {
  if (!id) return "-";
  return sources.value.find((item) => item.id === id)?.source_code ?? id;
}

function splitRoles(value: string) {
  return value
    .split(/[,，\s]+/u)
    .map((item) => item.trim())
    .filter(Boolean);
}

async function load() {
  error.value = "";
  try {
    const [spaceResult, sourceResult, documentResult, authorizationResult, indexResult, evaluationResult, runResult, auditResult] = await Promise.all([
      catalogApi<{ items: Space[] }>("/admin/knowledge/spaces"),
      catalogApi<{ items: Source[] }>("/admin/knowledge/sources"),
      catalogApi<{ items: Document[] }>("/admin/knowledge/documents"),
      canReadAuthorization.value
        ? catalogApi<{ items: Authorization[] }>("/admin/knowledge/authorizations")
        : Promise.resolve({ items: [] as Authorization[] }),
      catalogApi<{ items: IndexVersion[] }>("/admin/knowledge/indexes"),
      catalogApi<{ items: Evaluation[] }>("/admin/knowledge/evaluations"),
      catalogApi<{ items: EvaluationRun[] }>("/admin/knowledge/evaluation-runs"),
      catalogApi<{ items: AuditEvent[] }>("/admin/knowledge/audit")
    ]);
    spaces.value = spaceResult.items;
    sources.value = sourceResult.items;
    documents.value = documentResult.items;
    authorizations.value = authorizationResult.items;
    indexes.value = indexResult.items;
    evaluations.value = evaluationResult.items;
    evaluationRuns.value = runResult.items;
    auditEvents.value = auditResult.items;
    if (!spaces.value.some((space) => space.space_code === selectedSpaceCode.value)) {
      selectedSpaceCode.value = spaces.value.find(
        (space) => space.space_code === "vav-public-guidance"
      )?.space_code ?? spaces.value[0]?.space_code ?? "";
    }
    selectedSourceId.value ||= sources.value.find((item) => item.source_type === "upload")?.id ?? sources.value[0]?.id ?? "";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "知识库中心加载失败";
  }
}

async function retrieve() {
  try {
    const response = await catalogApi<{ items: Result[] }>("/admin/knowledge/retrieval/debug", {
      method: "POST",
      body: JSON.stringify({
        space_code: selectedSpace.value?.space_code,
        query: query.value,
        locale: locale.value,
        roles: [],
        top_k: 8,
        public: true
      })
    });
    results.value = response.items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "检索调试失败";
  }
}

async function inspectParsing(versionId?: string | null) {
  if (!versionId) return;
  try {
    const response = await catalogApi<{ report: typeof parsingReport.value; blocks: ParsedBlock[] }>(`/admin/knowledge/document-versions/${versionId}/parsing`);
    parsingReport.value = response.report;
    parsedBlocks.value = response.blocks;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "解析预览加载失败";
  }
}

function chooseFile(event: Event) {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0] ?? null;
  if (selectedFile.value) {
    uploadTitle.value ||= selectedFile.value.name;
    uploadCode.value ||= `upload-${Date.now()}`;
  }
}

async function sha256(file: File) {
  const bytes = await file.arrayBuffer();
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

async function uploadPrivateDocument() {
  if (!selectedFile.value || !selectedSourceId.value) return;
  busy.value = true;
  error.value = "";
  try {
    const checksum = await sha256(selectedFile.value);
    const created = await catalogApi<{ id: string; upload_url: string; required_headers: Record<string, string> }>("/admin/knowledge/uploads", {
      method: "POST",
      body: JSON.stringify({
        source_id: selectedSourceId.value,
        document_code: uploadCode.value,
        title: uploadTitle.value,
        locale: locale.value,
        filename: selectedFile.value.name,
        mime_type: selectedFile.value.type || "text/plain",
        byte_size: selectedFile.value.size,
        checksum_sha256: checksum
      })
    });
    const put = await fetch(created.upload_url, { method: "PUT", headers: created.required_headers, body: selectedFile.value });
    if (!put.ok) throw new Error("私有对象上传失败");
    await catalogApi(`/admin/knowledge/uploads/${created.id}/complete`, {
      method: "POST",
      body: JSON.stringify({ checksum_sha256: checksum })
    });
    notice.value = "文件已私有导入，等待授权与人工复核，尚未进入生产检索。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "私有上传失败";
  } finally {
    busy.value = false;
  }
}

async function syncSource(source: Source) {
  busy.value = true;
  try {
    const response = await catalogApi<{ document_count: number }>(`/admin/knowledge/sources/${source.id}/sync`, { method: "POST" });
    notice.value = `已同步 ${response.document_count} 个公开版本；仍需授权和复核。`;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "来源同步失败";
  } finally {
    busy.value = false;
  }
}

function askReason(title: string, intent: string, run: (reason: string) => Promise<void>) {
  notice.value = "";
  error.value = "";
  reasonDialog.value = { open: true, title, intent, reason: "", run };
}

async function confirmReason() {
  const { reason, run, title } = reasonDialog.value;
  if (!run) return;
  if (reason.trim().length < 10) {
    error.value = "请填写至少 10 个字符的操作原因，原因会写入知识库审计事件。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await run(reason.trim());
    notice.value = `${title}已完成。`;
    reasonDialog.value = { open: false, title: "", intent: "", reason: "" };
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : `${title}失败`;
  } finally {
    busy.value = false;
  }
}

function decideAuthorization(row: Authorization, action: "approve" | "reject" | "revoke") {
  const title = { approve: "批准授权", reject: "驳回授权", revoke: "撤销授权" }[action];
  const intent = {
    approve: "批准后该来源或文档的内容才允许进入索引与检索。",
    reject: "驳回后该授权申请作废，内容不会进入索引。",
    revoke: "撤销会使已入索引的内容失去授权依据，需要随后重建索引。"
  }[action];
  askReason(title, intent, async (reason) => {
    await catalogApi(`/admin/knowledge/authorizations/${row.id}/${action}`, {
      method: "POST",
      body: JSON.stringify({ reason })
    });
  });
}

async function previewImpact(row: Authorization) {
  impact.value = undefined;
  error.value = "";
  try {
    impact.value = await catalogApi<AuthorizationImpact>(
      `/admin/knowledge/authorizations/${row.id}/impact`
    );
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "影响面评估失败";
  }
}

function openAuthorizationDialog(scope: "document" | "source", id: string) {
  notice.value = "";
  error.value = "";
  authorizationDialog.value = {
    open: true,
    scope,
    document_id: scope === "document" ? id : "",
    source_id: scope === "source" ? id : "",
    allow_rag: true,
    allow_public_quote: false,
    allow_external_training: false,
    rights_holder_name: "VAV",
    authorization_basis: "owned_by_vav",
    citation_permission: "internal_reference_only",
    valid_from: "",
    valid_until: "",
    evidence_type: "written_license",
    evidence_reference: "",
    evidence_note: ""
  };
}

async function submitAuthorization() {
  const form = authorizationDialog.value;
  if (!form.valid_from) {
    error.value = "请选择授权生效时间。";
    return;
  }
  if (form.evidence_reference.trim().length < 2) {
    error.value = "请填写授权证据编号或存档链接，证据会加密留存并作为合规依据。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    const path =
      form.scope === "document"
        ? `/admin/knowledge/documents/${form.document_id}/authorizations`
        : `/admin/knowledge/sources/${form.source_id}/authorizations`;
    await catalogApi(path, {
      method: "POST",
      body: JSON.stringify({
        allow_rag: form.allow_rag,
        allow_public_quote: form.allow_public_quote,
        allow_external_training: form.allow_external_training,
        allowed_regions: [],
        evidence: {
          evidence_type: form.evidence_type,
          reference: form.evidence_reference.trim(),
          note: form.evidence_note.trim()
        },
        valid_from: form.valid_from,
        valid_until: form.valid_until || null,
        rights_holder_name: form.rights_holder_name.trim() || "VAV",
        authorization_basis: form.authorization_basis,
        citation_permission: form.citation_permission
      })
    });
    notice.value =
      form.scope === "document"
        ? "文档授权已提交，待具备审批权限的运营批准后才会生效。"
        : "来源授权已登记生效。";
    form.open = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "授权登记失败";
  } finally {
    busy.value = false;
  }
}

async function createSpace() {
  const form = spaceDialog.value;
  if (form.purpose.trim().length < 10) {
    error.value = "请写清楚该知识空间的用途边界（至少 10 个字符）。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await catalogApi("/admin/knowledge/spaces", {
      method: "POST",
      body: JSON.stringify({
        space_code: form.space_code.trim(),
        name: form.name.trim(),
        purpose: form.purpose.trim(),
        default_locale: form.default_locale,
        allowed_roles: splitRoles(form.allowed_roles)
      })
    });
    notice.value = "知识空间已创建。";
    form.open = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "知识空间创建失败";
  } finally {
    busy.value = false;
  }
}

async function createSource() {
  const form = sourceDialog.value;
  if (!form.space_id) {
    error.value = "请选择该来源归属的知识空间。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await catalogApi(`/admin/knowledge/spaces/${form.space_id}/sources`, {
      method: "POST",
      body: JSON.stringify({
        source_code: form.source_code.trim(),
        source_type: form.source_type,
        title: form.title.trim(),
        sensitivity: form.sensitivity
      })
    });
    notice.value = "知识来源已创建；导入内容前仍需登记授权。";
    form.open = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "知识来源创建失败";
  } finally {
    busy.value = false;
  }
}

async function openDocument(row: Document) {
  error.value = "";
  try {
    documentDetail.value = await catalogApi<DocumentDetail>(`/admin/knowledge/documents/${row.id}`);
    findings.value = [];
    findingsVersionId.value = "";
    publishForm.value = { version_id: "", allowed_roles: "", reason: "" };
    documentDrawer.value = true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "文档详情加载失败";
  }
}

async function refreshDocument() {
  if (!documentDetail.value) return;
  documentDetail.value = await catalogApi<DocumentDetail>(
    `/admin/knowledge/documents/${documentDetail.value.id}`
  );
}

function reviewVersion(version: DocumentVersion, decision: "approve" | "reject") {
  const title = decision === "approve" ? "通过版本复核" : "驳回版本复核";
  askReason(
    title,
    decision === "approve"
      ? "复核通过后该版本才可以进入发布环节。"
      : "驳回后该版本不会进入发布环节，请写明不合格的具体位置。",
    async (reason) => {
      await catalogApi(`/admin/knowledge/document-versions/${version.id}/review`, {
        method: "POST",
        body: JSON.stringify({ decision, reason })
      });
      await refreshDocument();
    }
  );
}

async function publishVersion() {
  const form = publishForm.value;
  if (!form.version_id) {
    error.value = "请选择要发布的文档版本。";
    return;
  }
  if (form.reason.trim().length < 10) {
    error.value = "请填写至少 10 个字符的发布说明，说明会写入知识库审计事件。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await catalogApi(`/admin/knowledge/document-versions/${form.version_id}/publish`, {
      method: "POST",
      body: JSON.stringify({
        allowed_roles: splitRoles(form.allowed_roles),
        reason: form.reason.trim()
      })
    });
    notice.value = "版本已发布；检索时仍会再次执行授权与 ACL 校验。";
    publishForm.value = { version_id: "", allowed_roles: "", reason: "" };
    await refreshDocument();
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "版本发布失败";
  } finally {
    busy.value = false;
  }
}

async function loadFindings(version: DocumentVersion) {
  error.value = "";
  try {
    const response = await catalogApi<{ items: Finding[] }>(
      `/admin/knowledge/document-versions/${version.id}/findings`
    );
    findings.value = response.items;
    findingsVersionId.value = version.id;
    // Seed the drafts here rather than lazily inside render: writing to a ref
    // while rendering would retrigger the render pass.
    const drafts: Record<string, { decision: string; resolution: string }> = {};
    for (const item of response.items) {
      drafts[item.id] = findingResolution.value[item.id] ?? { decision: "resolved", resolution: "" };
    }
    findingResolution.value = drafts;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "解析风险项加载失败";
  }
}

async function reviewFinding(finding: Finding) {
  const draft = findingResolution.value[finding.id];
  if (!draft || draft.resolution.trim().length < 10) {
    error.value = "请填写至少 10 个字符的处置说明。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await catalogApi(`/admin/knowledge/findings/${finding.id}/review`, {
      method: "POST",
      body: JSON.stringify({ decision: draft.decision, resolution: draft.resolution.trim() })
    });
    notice.value = "风险项已处置。";
    const version = documentDetail.value?.versions.find((item) => item.id === findingsVersionId.value);
    if (version) await loadFindings(version);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "风险项处置失败";
  } finally {
    busy.value = false;
  }
}

function changeIndex(index: IndexVersion, action: "activate" | "rollback") {
  askReason(
    action === "activate" ? "激活索引版本" : "回滚索引版本",
    action === "activate"
      ? "激活后线上检索立即切换到该索引版本。"
      : "回滚会把线上检索切回上一个索引版本。",
    async (reason) => {
      await catalogApi(`/admin/knowledge/indexes/${index.id}/${action}`, {
        method: "POST",
        body: JSON.stringify({ reason })
      });
    }
  );
}

onMounted(() => void load());
</script>

<template>
  <section class="admin-module knowledge-admin">
    <div class="module-heading">
      <div>
        <p class="admin-kicker">
          授权知识库
        </p>
        <h2>知识库中心</h2>
        <p>授权先于索引；检索时再次执行 ACL；引用始终绑定精确文档版本和 Chunk。</p>
      </div>
      <el-button @click="load">
        刷新
      </el-button>
    </div>
    <el-alert
      title="文档中的指令是不可信数据，不能授权工具调用；实时价格和可用性必须查询业务服务。"
      type="warning"
      :closable="false"
      show-icon
    />
    <el-alert
      v-if="notice"
      :title="notice"
      type="success"
      :closable="false"
      show-icon
    />
    <p
      v-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>

    <el-tabs>
      <el-tab-pane label="知识空间">
        <div class="pane-toolbar">
          <el-button
            v-if="canManageSpaces"
            type="primary"
            @click="spaceDialog.open = true"
          >
            新建知识空间
          </el-button>
        </div>
        <el-table :data="spaces">
          <el-table-column
            prop="space_code"
            label="代码"
          />
          <el-table-column
            prop="name"
            label="名称"
          />
          <el-table-column
            prop="purpose"
            label="用途边界"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="来源与同步">
        <div class="pane-toolbar">
          <el-button
            v-if="canManageSources"
            type="primary"
            @click="sourceDialog.open = true"
          >
            新建知识来源
          </el-button>
        </div>
        <el-table :data="sources">
          <el-table-column
            prop="source_code"
            label="来源"
          />
          <el-table-column
            prop="source_type"
            label="类型"
          />
          <el-table-column
            prop="sensitivity"
            label="敏感级别"
          />
          <el-table-column
            label="操作"
            width="260"
          >
            <template #default="scope">
              <el-button
                v-if="canManageSources && ['cms','course','activity','counseling'].includes(scope.row.source_type)"
                size="small"
                :loading="busy"
                @click="syncSource(scope.row)"
              >
                同步公开内容
              </el-button>
              <el-button
                v-if="canApproveAuthorization"
                size="small"
                @click="openAuthorizationDialog('source', scope.row.id)"
              >
                登记来源授权
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="私有导入向导">
        <p>文件先上传到私有对象存储；MIME、大小、SHA-256、病毒扫描边界和解析质量通过后，仍需授权与人工复核。</p>
        <el-select
          v-model="selectedSourceId"
          aria-label="知识来源"
        >
          <el-option
            v-for="source in sources"
            :key="source.id"
            :label="source.title"
            :value="source.id"
          />
        </el-select>
        <input
          aria-label="知识文档文件"
          type="file"
          accept=".pdf,.docx,.md,.txt,.html"
          @change="chooseFile"
        >
        <el-input
          v-model="uploadCode"
          aria-label="文档代码"
          placeholder="文档代码"
        />
        <el-input
          v-model="uploadTitle"
          aria-label="文档标题"
          placeholder="内部标题"
        />
        <el-button
          type="primary"
          :disabled="!selectedFile || !uploadCode || !uploadTitle"
          :loading="busy"
          @click="uploadPrivateDocument"
        >
          创建私有上传并校验
        </el-button>
      </el-tab-pane>

      <el-tab-pane label="文档与版本">
        <el-table :data="documents">
          <el-table-column
            prop="document_code"
            label="文档代码"
          />
          <el-table-column
            prop="title"
            label="标题"
          />
          <el-table-column
            prop="locale"
            label="语言"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
          <el-table-column
            label="操作"
            width="280"
          >
            <template #default="scope">
              <el-button
                size="small"
                type="primary"
                link
                @click="openDocument(scope.row)"
              >
                版本与复核
              </el-button>
              <el-button
                :disabled="!scope.row.current_version_id"
                size="small"
                @click="inspectParsing(scope.row.current_version_id)"
              >
                解析与溯源
              </el-button>
              <el-button
                v-if="canManageAuthorization"
                size="small"
                @click="openAuthorizationDialog('document', scope.row.id)"
              >
                申请授权
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-descriptions
          v-if="parsingReport"
          title="解析报告"
          :column="3"
          border
        >
          <el-descriptions-item label="解析器">
            {{ parsingReport.parser_name }}
          </el-descriptions-item>
          <el-descriptions-item label="质量">
            {{ parsingReport.quality_score_basis_points }}
          </el-descriptions-item>
          <el-descriptions-item label="人工复核">
            {{ parsingReport.requires_manual_review ? "需要" : "已满足阈值" }}
          </el-descriptions-item>
        </el-descriptions>
        <article
          v-for="block in parsedBlocks"
          :key="block.block_id"
          class="result-card"
        >
          <strong>{{ block.block_type }} · {{ block.section_path.join(" / ") }}</strong>
          <p>{{ block.text }}</p>
          <small>Page {{ block.page_number ?? "-" }} · {{ JSON.stringify(block.source_locator) }}</small>
        </article>
      </el-tab-pane>

      <el-tab-pane label="授权治理">
        <p class="pane-hint">
          授权是索引的前置条件：待审批的授权不会进入索引，撤销授权后需要重建索引才能真正生效。
        </p>
        <el-table :data="authorizations">
          <el-table-column
            label="授权对象"
            min-width="180"
          >
            <template #default="scope">
              {{ documentLabel(scope.row.document_id) }}
              <small>（来源 {{ sourceLabel(scope.row.source_id) }}）</small>
            </template>
          </el-table-column>
          <el-table-column
            prop="rights_holder_name"
            label="权利方"
          />
          <el-table-column
            prop="authorization_basis"
            label="依据"
          />
          <el-table-column
            prop="citation_permission"
            label="引用权限"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
          <el-table-column
            prop="valid_until"
            :formatter="formatAdminTableCell"
            label="到期时间（UTC+8）"
          />
          <el-table-column
            label="操作"
            fixed="right"
            width="300"
          >
            <template #default="scope">
              <el-button
                size="small"
                @click="previewImpact(scope.row)"
              >
                影响面
              </el-button>
              <el-button
                v-if="canApproveAuthorization && scope.row.status === 'pending'"
                size="small"
                type="success"
                @click="decideAuthorization(scope.row, 'approve')"
              >
                批准
              </el-button>
              <el-button
                v-if="canApproveAuthorization && scope.row.status === 'pending'"
                size="small"
                type="warning"
                @click="decideAuthorization(scope.row, 'reject')"
              >
                驳回
              </el-button>
              <el-button
                v-if="canApproveAuthorization && scope.row.status === 'approved'"
                size="small"
                type="danger"
                @click="decideAuthorization(scope.row, 'revoke')"
              >
                撤销
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-descriptions
          v-if="impact"
          title="撤销影响面"
          :column="4"
          border
        >
          <el-descriptions-item label="文档数">
            {{ impact.document_count }}
          </el-descriptions-item>
          <el-descriptions-item label="Chunk 数">
            {{ impact.chunk_count }}
          </el-descriptions-item>
          <el-descriptions-item label="向量数">
            {{ impact.embedding_count }}
          </el-descriptions-item>
          <el-descriptions-item label="需重建索引">
            {{ impact.requires_index_repair ? "是" : "否" }}
          </el-descriptions-item>
        </el-descriptions>
      </el-tab-pane>

      <el-tab-pane label="混合检索调试">
        <el-select
          v-model="selectedSpaceCode"
          aria-label="检索知识空间"
        >
          <el-option
            v-for="space in spaces"
            :key="space.id"
            :label="`${space.name} (${space.space_code})`"
            :value="space.space_code"
          />
        </el-select>
        <el-input
          v-model="query"
          aria-label="检索问题"
        />
        <el-select
          v-model="locale"
          aria-label="检索语言"
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
            label="英文"
            value="en"
          />
        </el-select>
        <el-button
          type="primary"
          @click="retrieve"
        >
          运行授权检索
        </el-button>
        <article
          v-for="item in results"
          :key="item.chunk_id"
          class="result-card"
        >
          <strong>{{ item.document_code }} · v{{ item.version_number }}</strong>
          <p>{{ item.excerpt }}</p>
          <small>Chunk {{ item.chunk_id }} · Parent {{ item.parent_chunk_id }} · SHA-256 {{ item.excerpt_sha256 }}</small>
        </article>
      </el-tab-pane>

      <el-tab-pane label="索引版本">
        <el-table :data="indexes">
          <el-table-column
            prop="version_number"
            label="版本"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
          <el-table-column
            prop="evaluation_status"
            label="评测"
          />
          <el-table-column label="受控切换">
            <template #default="scope">
              <el-button
                v-if="canManageIndex && scope.row.status === 'ready_for_evaluation'"
                :disabled="scope.row.evaluation_status !== 'passed'"
                @click="changeIndex(scope.row, 'activate')"
              >
                激活
              </el-button>
              <el-button
                v-if="canManageIndex && scope.row.status === 'active' && scope.row.previous_index_id"
                @click="changeIndex(scope.row, 'rollback')"
              >
                回滚
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="评测门禁">
        <p
          v-for="dataset in evaluations"
          :key="dataset.id"
        >
          {{ dataset.name }}：{{ dataset.case_count }} 个案例（授权和 ACL 泄漏必须为 0）
        </p>
        <el-table :data="evaluationRuns">
          <el-table-column
            prop="index_version_id"
            label="索引"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          />
          <el-table-column label="通过">
            <template #default="scope">
              {{ scope.row.passed_cases }}/{{ scope.row.total_cases }}
            </template>
          </el-table-column>
          <el-table-column
            prop="authorization_violations"
            label="授权违规"
          />
          <el-table-column
            prop="acl_leakage_count"
            label="访问控制泄漏"
          />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="知识审计">
        <el-table :data="auditEvents">
          <el-table-column
            prop="event_type"
            label="事件"
          />
          <el-table-column
            prop="subject_type"
            label="对象"
          />
          <el-table-column
            prop="reason"
            label="原因"
          />
          <el-table-column
            prop="created_at"
            :formatter="formatAdminTableCell"
            label="时间（UTC+8）"
          />
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-drawer
      v-model="documentDrawer"
      title="文档版本复核与发布"
      size="760px"
    >
      <template v-if="documentDetail">
        <h3>{{ documentDetail.document_code }} · {{ documentDetail.title }}</h3>
        <el-table
          :data="documentDetail.versions"
          size="small"
        >
          <el-table-column
            prop="version_number"
            label="版本"
            width="80"
          />
          <el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
            min-width="120"
          />
          <el-table-column
            prop="parse_quality_bps"
            label="解析质量"
            width="100"
          />
          <el-table-column
            label="复核"
            min-width="280"
          >
            <template #default="scope">
              <el-button
                size="small"
                @click="loadFindings(scope.row)"
              >
                风险项
              </el-button>
              <el-button
                v-if="canReviewDocument"
                size="small"
                type="success"
                @click="reviewVersion(scope.row, 'approve')"
              >
                复核通过
              </el-button>
              <el-button
                v-if="canReviewDocument"
                size="small"
                type="warning"
                @click="reviewVersion(scope.row, 'reject')"
              >
                驳回
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <template v-if="findings.length">
          <h3>解析风险项</h3>
          <article
            v-for="finding in findings"
            :key="finding.id"
            class="result-card"
          >
            <strong>{{ finding.finding_type }} · {{ finding.severity }}</strong>
            <p>
              当前状态 {{ finding.status }}
              <span v-if="finding.blocks_publication">· 阻断发布</span>
            </p>
            <el-form
              v-if="canReviewDocument && finding.status === 'open' && findingResolution[finding.id]"
              label-position="top"
            >
              <el-form-item label="处置结论">
                <el-select v-model="findingResolution[finding.id].decision">
                  <el-option
                    v-for="option in FINDING_DECISIONS"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="处置说明（至少 10 个字符）">
                <el-input
                  v-model="findingResolution[finding.id].resolution"
                  type="textarea"
                  :rows="2"
                />
              </el-form-item>
              <el-button
                :loading="busy"
                @click="reviewFinding(finding)"
              >
                提交处置
              </el-button>
            </el-form>
          </article>
        </template>

        <template v-if="canPublishDocument">
          <h3>发布版本</h3>
          <el-form label-position="top">
            <el-form-item label="待发布版本">
              <el-select
                v-model="publishForm.version_id"
                placeholder="选择已复核通过的版本"
              >
                <el-option
                  v-for="version in documentDetail.versions"
                  :key="version.id"
                  :label="`v${version.version_number}（${version.status}）`"
                  :value="version.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="可访问角色（留空表示沿用文档默认 ACL，多个角色用逗号分隔）">
              <el-input
                v-model="publishForm.allowed_roles"
                placeholder="member, counselor"
              />
            </el-form-item>
            <el-form-item label="发布说明（至少 10 个字符）">
              <el-input
                v-model="publishForm.reason"
                type="textarea"
                :rows="2"
              />
            </el-form-item>
            <el-button
              type="primary"
              :loading="busy"
              @click="publishVersion"
            >
              发布该版本
            </el-button>
          </el-form>
        </template>
      </template>
    </el-drawer>

    <el-dialog
      v-model="reasonDialog.open"
      :title="reasonDialog.title"
      width="520px"
    >
      <p class="pane-hint">
        {{ reasonDialog.intent }}
      </p>
      <el-form label-position="top">
        <el-form-item label="操作原因（至少 10 个字符）">
          <el-input
            v-model="reasonDialog.reason"
            type="textarea"
            :rows="3"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reasonDialog.open = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="busy"
          @click="confirmReason"
        >
          确认执行
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="spaceDialog.open"
      title="新建知识空间"
      width="560px"
    >
      <el-form label-position="top">
        <el-form-item label="空间代码（小写字母、数字、- 或 _）">
          <el-input
            v-model="spaceDialog.space_code"
            placeholder="vav-public-guidance"
          />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="spaceDialog.name" />
        </el-form-item>
        <el-form-item label="用途边界（至少 10 个字符，会作为检索授权依据）">
          <el-input
            v-model="spaceDialog.purpose"
            type="textarea"
            :rows="3"
          />
        </el-form-item>
        <el-form-item label="默认语言">
          <el-select v-model="spaceDialog.default_locale">
            <el-option
              label="简体中文"
              value="zh-CN"
            />
            <el-option
              label="繁體中文"
              value="zh-TW"
            />
            <el-option
              label="英文"
              value="en"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="可访问角色（多个角色用逗号分隔，留空表示仅内部）">
          <el-input v-model="spaceDialog.allowed_roles" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="spaceDialog.open = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="busy"
          @click="createSpace"
        >
          创建
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="sourceDialog.open"
      title="新建知识来源"
      width="560px"
    >
      <el-form label-position="top">
        <el-form-item label="归属知识空间">
          <el-select v-model="sourceDialog.space_id">
            <el-option
              v-for="space in spaces"
              :key="space.id"
              :label="`${space.name} (${space.space_code})`"
              :value="space.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="来源代码（小写字母、数字、- 或 _）">
          <el-input v-model="sourceDialog.source_code" />
        </el-form-item>
        <el-form-item label="来源类型">
          <el-select v-model="sourceDialog.source_type">
            <el-option
              v-for="type in SOURCE_TYPES"
              :key="type"
              :label="type"
              :value="type"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="sourceDialog.title" />
        </el-form-item>
        <el-form-item label="敏感级别">
          <el-select v-model="sourceDialog.sensitivity">
            <el-option
              label="公开"
              value="public"
            />
            <el-option
              label="内部"
              value="internal"
            />
            <el-option
              label="受限"
              value="restricted"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="sourceDialog.open = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="busy"
          @click="createSource"
        >
          创建
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="authorizationDialog.open"
      :title="authorizationDialog.scope === 'document' ? '申请文档授权' : '登记来源授权'"
      width="620px"
    >
      <el-form label-position="top">
        <el-form-item label="权利方名称">
          <el-input v-model="authorizationDialog.rights_holder_name" />
        </el-form-item>
        <el-form-item label="授权依据">
          <el-select v-model="authorizationDialog.authorization_basis">
            <el-option
              v-for="option in AUTHORIZATION_BASES"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="引用权限">
          <el-select v-model="authorizationDialog.citation_permission">
            <el-option
              v-for="option in CITATION_PERMISSIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="允许的用途">
          <el-checkbox v-model="authorizationDialog.allow_rag">
            用于检索增强问答
          </el-checkbox>
          <el-checkbox v-model="authorizationDialog.allow_public_quote">
            允许对外引用
          </el-checkbox>
          <el-checkbox v-model="authorizationDialog.allow_external_training">
            允许外部模型训练
          </el-checkbox>
        </el-form-item>
        <el-form-item label="生效时间">
          <el-date-picker
            v-model="authorizationDialog.valid_from"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ssZ"
            placeholder="选择生效时间"
          />
        </el-form-item>
        <el-form-item label="到期时间（留空表示长期有效）">
          <el-date-picker
            v-model="authorizationDialog.valid_until"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ssZ"
            placeholder="选择到期时间"
          />
        </el-form-item>
        <el-form-item label="证据类型">
          <el-select v-model="authorizationDialog.evidence_type">
            <el-option
              label="书面授权书"
              value="written_license"
            />
            <el-option
              label="合同条款"
              value="contract_clause"
            />
            <el-option
              label="内部创作记录"
              value="internal_authorship"
            />
            <el-option
              label="用户授权同意"
              value="user_consent"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="证据编号或存档链接">
          <el-input
            v-model="authorizationDialog.evidence_reference"
            placeholder="合同编号、审批单号或归档系统链接"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input
            v-model="authorizationDialog.evidence_note"
            type="textarea"
            :rows="2"
          />
        </el-form-item>
      </el-form>
      <p class="pane-hint">
        证据会加密留存；未获批准的授权不会进入索引，允许外部模型训练属于高风险选项，请确认书面依据。
      </p>
      <template #footer>
        <el-button @click="authorizationDialog.open = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="busy"
          @click="submitAuthorization"
        >
          提交
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.pane-toolbar{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px}.pane-hint{color:var(--el-text-color-secondary);margin:0 0 12px}h3{margin-top:24px}
</style>
