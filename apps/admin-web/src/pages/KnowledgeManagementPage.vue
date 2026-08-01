<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { catalogApi } from "@/features/catalog/api";

type Space = { id: string; space_code: string; name: string; purpose: string; status: string };
type Source = { id: string; source_code: string; source_type: string; title: string; sensitivity: string; status: string };
type Document = { id: string; document_code: string; title: string; locale: string; status: string; current_version_id?: string | null };
type Authorization = { id: string; document_id?: string | null; status: string; rights_holder_name: string; authorization_basis: string; citation_permission: string; valid_until?: string | null };
type IndexVersion = { id: string; version_number: number; status: string; evaluation_status: string; previous_index_id?: string | null };
type Evaluation = { id: string; dataset_code: string; name: string; case_count: number };
type EvaluationRun = { id: string; index_version_id: string; status: string; total_cases: number; passed_cases: number; authorization_violations: number; acl_leakage_count: number };
type AuditEvent = { id: string; event_type: string; subject_type: string; subject_id: string; reason?: string | null; created_at: string };
type Result = { document_code: string; version_number: number; chunk_id: string; parent_chunk_id?: string | null; excerpt?: string | null; excerpt_sha256?: string | null; source_locator: Record<string, unknown> };
type ParsedBlock = { block_id: string; block_type: string; text?: string | null; page_number?: number | null; section_path: string[]; source_locator: Record<string, unknown> };

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

async function load() {
  error.value = "";
  try {
    const [spaceResult, sourceResult, documentResult, authorizationResult, indexResult, evaluationResult, runResult, auditResult] = await Promise.all([
      catalogApi<{ items: Space[] }>("/admin/knowledge/spaces"),
      catalogApi<{ items: Source[] }>("/admin/knowledge/sources"),
      catalogApi<{ items: Document[] }>("/admin/knowledge/documents"),
      catalogApi<{ items: Authorization[] }>("/admin/knowledge/authorizations"),
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

async function changeIndex(index: IndexVersion, action: "activate" | "rollback") {
  try {
    await catalogApi(`/admin/knowledge/indexes/${index.id}/${action}`, {
      method: "POST",
      body: JSON.stringify({ reason: `管理端${action === "activate" ? "激活" : "回滚"}审批` })
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "索引切换失败";
  }
}

onMounted(() => void load());
</script>

<template>
  <section class="admin-module knowledge-admin">
    <div class="module-heading">
      <div>
        <p class="admin-kicker">
          AUTHORIZED KNOWLEDGE
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
            label="状态"
          />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="来源与同步">
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
          <el-table-column label="操作">
            <template #default="scope">
              <el-button
                v-if="['cms','course','activity','counseling'].includes(scope.row.source_type)"
                :loading="busy"
                @click="syncSource(scope.row)"
              >
                同步公开内容
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
            label="状态"
          />
          <el-table-column label="证据">
            <template #default="scope">
              <el-button
                :disabled="!scope.row.current_version_id"
                @click="inspectParsing(scope.row.current_version_id)"
              >
                解析与溯源
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
        <el-table :data="authorizations">
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
            label="状态"
          />
          <el-table-column
            prop="valid_until"
            label="到期"
          />
        </el-table>
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
            label="English"
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
            label="状态"
          />
          <el-table-column
            prop="evaluation_status"
            label="评测"
          />
          <el-table-column label="受控切换">
            <template #default="scope">
              <el-button
                v-if="scope.row.status === 'ready_for_evaluation'"
                :disabled="scope.row.evaluation_status !== 'passed'"
                @click="changeIndex(scope.row, 'activate')"
              >
                激活
              </el-button>
              <el-button
                v-if="scope.row.status === 'active' && scope.row.previous_index_id"
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
            label="ACL 泄漏"
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
            label="时间"
          />
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>
