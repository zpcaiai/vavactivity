<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { localizeAdminLabel, localizeAdminValue } from "@vav/ui-admin";

import { catalogApi } from "@/features/catalog/api";

interface CatalogRow {
  [key: string]: unknown;
  id: string;
  created_at?: string;
  updated_at?: string;
  sku_id?: string;
  product_code?: string;
  internal_name?: string;
  product_type?: string;
  fulfillment_type?: string;
  visibility?: string;
  default_locale?: string;
  category_id?: string;
  purchasable_from?: string | null;
  purchasable_until?: string | null;
  featured?: boolean;
  sort_order?: number;
  metadata?: Record<string, unknown>;
  version?: number;
  sku_count?: number;
  status?: string;
  price_book_code?: string;
  price_book_id?: string;
  name?: string;
  region_code?: string | null;
  customer_segment?: string | null;
  currency_code?: string;
  unit_amount_minor?: number;
  compare_at_amount_minor?: number | null;
  billing_type?: string;
  billing_interval?: string | null;
  billing_interval_count?: number | null;
  tax_behavior?: string;
  valid_from?: string | null;
  valid_until?: string | null;
  external_price_references?: Record<string, unknown>;
  supersedes_price_id?: string | null;
  inventory_policy?: string;
  total_capacity?: number | null;
  reserved_quantity?: number;
  sold_quantity?: number;
  safety_stock?: number;
  overselling_allowed?: boolean;
  oversell_limit?: number;
  available_quantity?: number | null;
  promotion_code?: string;
  promotion_type?: string;
  application_mode?: string;
  stackability?: string;
  total_redemption_limit?: number | null;
  per_user_redemption_limit?: number | null;
  current_redemption_count?: number;
  current_discount_total_minor?: number;
  display_code?: string;
  assigned_user_id?: string | null;
  priority?: number;
}

interface TableColumn {
  prop: string;
  label: string;
}

const route = useRoute();
const router = useRouter();
const section = computed(() => String(route.meta.catalogSection ?? "products"));
const isCouponImport = computed(
  () => section.value === "coupons" && route.path.endsWith("/import"),
);
const rows = ref<CatalogRow[]>([]);
const loading = ref(false);
const error = ref("");
const showCreate = ref(false);
const showAdjust = ref(false);
const selectedInventory = ref<CatalogRow | null>(null);
const adjustment = ref({ quantityDelta: 0, reason: "" });

const form = ref({
  code: "",
  slug: "",
  internalName: "",
  name: "",
  visibility: "public",
  productType: "digital_service",
  locale: "zh-CN",
  categoryId: "",
  purchasableFrom: "",
  purchasableUntil: "",
  featured: false,
  sortOrder: 0,
  metadata: "{}",
  priority: 0,
  applicationMode: "automatic",
  promotionType: "percentage",
  percentage: 1000,
  fixedAmount: 0,
  budgetLimitMinor: "",
  budgetCurrency: "",
  promotionId: "",
  couponCode: "",
  totalLimit: "",
  perUserLimit: "",
  assignedUserId: "",
  validFrom: "",
  validUntil: "",
  regionCode: "",
  customerSegment: "",
  importPrefix: "",
  importCount: 1,
  importValidUntil: ""
});

const fulfillmentByProductType: Record<string, string> = {
  activity_ticket: "event_admission",
  course: "digital_access",
  course_bundle: "digital_access",
  counseling_session: "appointment_credits",
  counseling_package: "appointment_credits",
  ai_credit_package: "ai_credits",
  ai_subscription: "ai_credits",
  membership: "membership_entitlement",
  digital_service: "digital_access"
};

const title = computed(() => ({
  products: "商品管理",
  "price-books": "价格簿",
  prices: "价格记录",
  inventory: "库存与名额",
  promotions: "优惠活动",
  coupons: "优惠码"
})[section.value] ?? "商品中心");

const endpoint = computed(() => `/admin/catalog/${section.value}`);
const canCreate = computed(() => !["inventory", "prices"].includes(section.value));

const columns = computed<TableColumn[]>(() => {
  if (section.value === "products") {
    return [
      { prop: "id", label: "商品 ID" },
      { prop: "product_code", label: "商品编码" },
      { prop: "internal_name", label: "内部名称" },
      { prop: "product_type", label: "类型" },
      { prop: "fulfillment_type", label: "履约方式" },
      { prop: "visibility", label: "可见性" },
      { prop: "default_locale", label: "默认语言" },
      { prop: "category_id", label: "分类" },
      { prop: "sku_count", label: "SKU 数" },
      { prop: "purchasable_from", label: "可售起始" },
      { prop: "purchasable_until", label: "可售截止" },
      { prop: "featured", label: "精选" },
      { prop: "sort_order", label: "排序权重" },
      { prop: "status", label: "状态" },
      { prop: "updated_at", label: "更新时间" },
      { prop: "version", label: "版本" },
    ];
  }
  if (section.value === "price-books") {
    return [
      { prop: "id", label: "价格簿 ID" },
      { prop: "price_book_code", label: "价格簿编码" },
      { prop: "name", label: "名称" },
      { prop: "region_code", label: "地区码" },
      { prop: "customer_segment", label: "用户分群" },
      { prop: "priority", label: "优先级" },
      { prop: "valid_from", label: "生效起始" },
      { prop: "valid_until", label: "失效截止" },
      { prop: "status", label: "状态" },
    ];
  }
  if (section.value === "prices") {
    return [
      { prop: "id", label: "价格 ID" },
      { prop: "sku_id", label: "SKU" },
      { prop: "price_book_id", label: "价格簿 ID" },
      { prop: "currency_code", label: "币种" },
      { prop: "unit_amount_minor", label: "单价（最小单位）" },
      { prop: "compare_at_amount_minor", label: "对比价（最小单位）" },
      { prop: "billing_type", label: "计费方式" },
      { prop: "billing_interval", label: "计费周期" },
      { prop: "billing_interval_count", label: "周期倍数" },
      { prop: "tax_behavior", label: "税务策略" },
      { prop: "valid_from", label: "生效起始" },
      { prop: "valid_until", label: "失效截止" },
      { prop: "status", label: "状态" },
      { prop: "external_price_references", label: "外部引用" },
      { prop: "supersedes_price_id", label: "替代价格 ID" },
    ];
  }
  if (section.value === "inventory") {
    return [
      { prop: "id", label: "库存 ID" },
      { prop: "sku_id", label: "SKU" },
      { prop: "inventory_policy", label: "库存策略" },
      { prop: "total_capacity", label: "总容量" },
      { prop: "safety_stock", label: "安全库存" },
      { prop: "oversell_limit", label: "超卖上限" },
      { prop: "overselling_allowed", label: "允许超卖" },
      { prop: "reserved_quantity", label: "预留" },
      { prop: "sold_quantity", label: "已售" },
      { prop: "available_quantity", label: "可售" },
      { prop: "version", label: "版本" },
    ];
  }
  if (section.value === "promotions") {
    return [
      { prop: "promotion_code", label: "活动码" },
      { prop: "internal_name", label: "内部名称" },
      { prop: "promotion_type", label: "类型" },
      { prop: "application_mode", label: "应用方式" },
      { prop: "stackability", label: "叠加策略" },
      { prop: "priority", label: "优先级" },
      { prop: "valid_from", label: "生效起始" },
      { prop: "valid_until", label: "失效截止" },
      { prop: "total_redemption_limit", label: "总可兑" },
      { prop: "per_user_redemption_limit", label: "每人可兑" },
      { prop: "current_redemption_count", label: "已兑" },
      { prop: "current_discount_total_minor", label: "累计折扣（最小单位）" },
      { prop: "budget_limit_minor", label: "预算上限（最小单位）" },
      { prop: "budget_currency", label: "预算币种" },
      { prop: "status", label: "状态" },
    ];
  }
  return [
    { prop: "id", label: "优惠码 ID" },
    { prop: "promotion_id", label: "活动 ID" },
    { prop: "display_code", label: "优惠码" },
    { prop: "status", label: "状态" },
    { prop: "valid_from", label: "生效起始" },
    { prop: "valid_until", label: "失效截止" },
    { prop: "total_redemption_limit", label: "总可兑" },
    { prop: "per_user_redemption_limit", label: "每人可兑" },
    { prop: "current_redemption_count", label: "已兑" },
    { prop: "assigned_user_id", label: "指定用户" },
  ];
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const result = await catalogApi<{ items: CatalogRow[] }>(endpoint.value);
    rows.value = result.items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

function safeMetadata() {
  try {
    return JSON.parse(form.value.metadata || "{}");
  } catch {
    return {};
  }
}

async function create() {
  error.value = "";
  let body: Record<string, unknown>;
  if (section.value === "products") {
    body = {
      product_code: form.value.code.toUpperCase(),
      product_type: form.value.productType,
      fulfillment_type: fulfillmentByProductType[form.value.productType],
      internal_name: form.value.internalName,
      visibility: form.value.visibility,
      default_locale: form.value.locale,
      category_id: form.value.categoryId || null,
      purchasable_from: form.value.purchasableFrom || null,
      purchasable_until: form.value.purchasableUntil || null,
      featured: form.value.featured,
      sort_order: form.value.sortOrder,
      metadata: safeMetadata(),
      localizations: [{
        locale: form.value.locale,
        slug: form.value.slug || form.value.code.toLowerCase().replaceAll("_", "-"),
        name: form.value.name,
        description_blocks: [],
        translation_status: "draft"
      }]
    };
  } else if (section.value === "price-books") {
    body = {
      price_book_code: form.value.code.toUpperCase(),
      name: form.value.name,
      region_code: form.value.regionCode || null,
      customer_segment: form.value.customerSegment || null,
      valid_from: form.value.validFrom || null,
      valid_until: form.value.validUntil || null,
      priority: form.value.priority
    };
  } else if (section.value === "promotions") {
    body = {
      promotion_code: form.value.code.toUpperCase(),
      internal_name: form.value.internalName,
      promotion_type: form.value.promotionType,
      application_mode: form.value.applicationMode,
      priority: form.value.priority,
      stackability: "exclusive",
      rules: { schema_version: 1 },
      benefits: {
        schema_version: 1,
        percentage_basis_points: form.value.percentage,
        fixed_amounts: form.value.fixedAmount > 0 ? { CNY: form.value.fixedAmount } : undefined
      },
      valid_from: form.value.validFrom ? new Date(form.value.validFrom).toISOString() : new Date().toISOString(),
      valid_until: form.value.validUntil ? new Date(form.value.validUntil).toISOString() : null,
      total_redemption_limit: form.value.totalLimit ? Number(form.value.totalLimit) : null,
      per_user_redemption_limit: form.value.perUserLimit ? Number(form.value.perUserLimit) : null,
      budget_limit_minor: form.value.budgetLimitMinor ? Number(form.value.budgetLimitMinor) : null,
      budget_currency: form.value.budgetCurrency || null
    };
    if (body.benefits && (body.benefits as { fixed_amounts?: Record<string, number> }).fixed_amounts === undefined) {
      delete (body.benefits as { fixed_amounts?: Record<string, number> }).fixed_amounts;
    }
  } else if (isCouponImport.value) {
    body = {
      promotion_id: form.value.promotionId,
      prefix: form.value.importPrefix || "BATCH",
      count: Number(form.value.importCount || 1),
      valid_until: form.value.importValidUntil || null
    };
  } else {
    body = {
      promotion_id: form.value.promotionId,
      code: (form.value.couponCode || form.value.code).trim(),
      valid_from: form.value.validFrom || null,
      valid_until: form.value.validUntil || null,
      total_redemption_limit: form.value.totalLimit ? Number(form.value.totalLimit) : null,
      per_user_redemption_limit: form.value.perUserLimit ? Number(form.value.perUserLimit) : null,
      assigned_user_id: form.value.assignedUserId || null
    };
  }

  try {
    const path = isCouponImport.value ? `${endpoint.value}/bulk-create` : endpoint.value;
    await catalogApi(path, {
      method: "POST",
      body: JSON.stringify(body)
    });
    showCreate.value = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "创建失败";
  }
}

function open(row: CatalogRow) {
  if (section.value === "products") {
    void router.push(`/admin/catalog/products/${row.id}`);
  }
}

function openAdjustment(row: CatalogRow) {
  selectedInventory.value = row;
  adjustment.value = { quantityDelta: 0, reason: "" };
  showAdjust.value = true;
}

async function adjustInventory() {
  if (!selectedInventory.value) {
    return;
  }
  try {
    await catalogApi(
      `/admin/catalog/inventory/${selectedInventory.value.sku_id}/adjust`,
      {
        method: "POST",
        body: JSON.stringify({
          quantity_delta: adjustment.value.quantityDelta,
          reason: adjustment.value.reason,
          expected_version: selectedInventory.value.version
        })
      }
    );
    showAdjust.value = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "库存调整失败";
  }
}

async function lifecycle(row: CatalogRow, action: string) {
  const resource = section.value;
  try {
    await catalogApi(`/admin/catalog/${resource}/${row.id}/${action}`, {
      method: "POST",
      body: JSON.stringify({
        reason: `Administration catalog ${resource} ${action} after review`
      })
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "状态变更失败";
  }
}

function formatValue(value: unknown, field: string) {
  return localizeAdminValue(value, field);
}

onMounted(() => void load());
watch(section, () => void load());
</script>

<template>
  <section v-loading="loading">
    <header class="page-toolbar">
      <div>
        <p class="admin-kicker">
          商品运营控制台
        </p>
        <h2>{{ title }}</h2>
      </div>
      <el-button
        v-if="canCreate"
        type="primary"
        @click="showCreate = true"
      >
        新建
      </el-button>
    </header>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
    />
    <el-table
      :data="rows"
      stripe
      @row-click="open"
    >
      <el-table-column
        v-for="column in columns"
        :key="`${column.prop}-${column.label}`"
        :prop="column.prop"
        :label="localizeAdminLabel(column.prop, column.label)"
      >
        <template #default="{ row }">
          <span>{{ formatValue(row[column.prop], column.prop) }}</span>
        </template>
      </el-table-column>
      <el-table-column
        label="操作"
        width="180"
      >
        <template #default="{ row }">
          <el-button
            v-if="section === 'inventory'"
            size="small"
            @click.stop="openAdjustment(row)"
          >
            调整
          </el-button>
          <el-button
            v-if="['price-books', 'prices', 'promotions'].includes(section) && row.status !== 'active'"
            size="small"
            type="primary"
            @click.stop="lifecycle(row, 'activate')"
          >
            启用
          </el-button>
          <el-button
            v-if="section === 'coupons' && row.status === 'active'"
            size="small"
            @click.stop="lifecycle(row, 'disable')"
          >
            停用
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-dialog
      v-model="showCreate"
      :title="`新建${title}`"
      width="680px"
    >
      <div class="editor-form">
        <label>编码<el-input v-model="form.code" /></label>
        <label>Slug<el-input v-model="form.slug" /></label>
        <label v-if="section === 'products' || section === 'promotions'">
          内部名称<el-input v-model="form.internalName" />
        </label>
        <label v-if="section === 'products' || section === 'price-books'">
          公开名称<el-input v-model="form.name" />
        </label>
        <label v-if="section === 'products'">
          商品类型
          <el-select v-model="form.productType">
            <el-option
              label="活动票"
              value="activity_ticket"
            />
            <el-option
              label="课程"
              value="course"
            />
            <el-option
              label="课程套餐"
              value="course_bundle"
            />
            <el-option
              label="辅导单次"
              value="counseling_session"
            />
            <el-option
              label="辅导套餐"
              value="counseling_package"
            />
            <el-option
              label="AI 次数包"
              value="ai_credit_package"
            />
            <el-option
              label="AI 订阅"
              value="ai_subscription"
            />
            <el-option
              label="婚恋会员"
              value="membership"
            />
            <el-option
              label="数字服务"
              value="digital_service"
            />
          </el-select>
        </label>
        <label v-if="section === 'products'">
          可见性
          <el-select v-model="form.visibility">
            <el-option
              label="公开"
              value="public"
            />
            <el-option
              label="私有"
              value="private"
            />
          </el-select>
        </label>
        <label v-if="section === 'products'">
          默认语言<el-input v-model="form.locale" />
        </label>
        <label v-if="section === 'products'">
          分类 UUID<el-input v-model="form.categoryId" />
        </label>
        <label v-if="section === 'products'">
          可售起始时间<el-input
            v-model="form.purchasableFrom"
            type="datetime-local"
          />
        </label>
        <label v-if="section === 'products'">
          可售截止时间<el-input
            v-model="form.purchasableUntil"
            type="datetime-local"
          />
        </label>
        <label v-if="section === 'products'">
          设为精选
          <el-select v-model="form.featured">
            <el-option
              label="否"
              :value="false"
            />
            <el-option
              label="是"
              :value="true"
            />
          </el-select>
        </label>
        <label v-if="section === 'products'">
          排序权重<el-input v-model.number="form.sortOrder" />
        </label>
        <label v-if="section === 'products'">
          元数据（JSON）<el-input
            v-model="form.metadata"
            type="textarea"
            :rows="4"
          />
        </label>
        <label v-if="section === 'promotions'">
          折扣基点（1000 = 10%）<el-input v-model.number="form.percentage" />
        </label>
        <label v-if="section === 'promotions'">
          固定金额减免（最小单位）<el-input v-model.number="form.fixedAmount" />
        </label>
        <label v-if="section === 'promotions'">
          应用方式<el-select v-model="form.applicationMode">
            <el-option
              label="自动"
              value="automatic"
            />
            <el-option
              label="手动"
              value="manual"
            />
          </el-select>
        </label>
        <label v-if="section === 'promotions'">
          活动类型<el-select v-model="form.promotionType">
            <el-option
              label="比例折扣"
              value="percentage"
            />
            <el-option
              label="固定金额"
              value="fixed_amount"
            />
          </el-select>
        </label>
        <label v-if="section === 'promotions'">
          优先级<el-input v-model.number="form.priority" />
        </label>
        <label v-if="section === 'promotions'">
          预算上限（最小单位）<el-input v-model="form.budgetLimitMinor" />
        </label>
        <label v-if="section === 'promotions'">
          预算币种<el-input v-model="form.budgetCurrency" />
        </label>
        <label v-if="section === 'promotions'">
          总可兑<el-input v-model="form.totalLimit" />
        </label>
        <label v-if="section === 'promotions'">
          每用户可兑<el-input v-model="form.perUserLimit" />
        </label>
        <label v-if="section === 'promotions'">
          生效起始<el-input
            v-model="form.validFrom"
            type="datetime-local"
          />
        </label>
        <label v-if="section === 'promotions'">
          生效截止<el-input
            v-model="form.validUntil"
            type="datetime-local"
          />
        </label>
        <label v-if="section === 'price-books'">
          地区码<el-input v-model="form.regionCode" />
        </label>
        <label v-if="section === 'price-books'">
          用户分群<el-input v-model="form.customerSegment" />
        </label>
        <label v-if="section === 'price-books'">
          生效起始<el-input
            v-model="form.validFrom"
            type="datetime-local"
          />
        </label>
        <label v-if="section === 'price-books'">
          生效截止<el-input
            v-model="form.validUntil"
            type="datetime-local"
          />
        </label>
        <label v-if="section === 'coupons'">
          优惠活动 UUID<el-input v-model="form.promotionId" />
        </label>
        <label v-if="section === 'coupons' && !isCouponImport">
          优惠码<el-input v-model="form.couponCode" />
        </label>
        <label v-if="section === 'coupons' && !isCouponImport">
          生效起始<el-input
            v-model="form.validFrom"
            type="datetime-local"
          />
        </label>
        <label v-if="section === 'coupons' && !isCouponImport">
          生效截止<el-input
            v-model="form.validUntil"
            type="datetime-local"
          />
        </label>
        <label v-if="section === 'coupons' && !isCouponImport">
          总可兑<el-input v-model="form.totalLimit" />
        </label>
        <label v-if="section === 'coupons' && !isCouponImport">
          每用户可兑<el-input v-model="form.perUserLimit" />
        </label>
        <label v-if="section === 'coupons' && !isCouponImport">
          指定用户 UUID<el-input v-model="form.assignedUserId" />
        </label>
        <label v-if="isCouponImport">
          批量前缀<el-input v-model="form.importPrefix" />
        </label>
        <label v-if="isCouponImport">
          生成数量<el-input v-model.number="form.importCount" />
        </label>
        <label v-if="isCouponImport">
          批量生效截止<el-input
            v-model="form.importValidUntil"
            type="datetime-local"
          />
        </label>
      </div>
      <template #footer>
        <el-button @click="showCreate = false">
          取消
        </el-button>
        <el-button
          type="primary"
          @click="create"
        >
          保存草稿
        </el-button>
      </template>
    </el-dialog>
    <el-dialog
      v-model="showAdjust"
      title="库存容量调整"
      width="560px"
    >
      <div class="inventory-risk-summary">
        <p>当前容量：{{ selectedInventory?.total_capacity }}</p>
        <p>已售：{{ selectedInventory?.sold_quantity }} · 已预留：{{ selectedInventory?.reserved_quantity }}</p>
      </div>
      <div class="editor-form">
        <label>调整数量<el-input v-model.number="adjustment.quantityDelta" /></label>
        <label>调整原因<el-input v-model="adjustment.reason" /></label>
        <p>期望版本：{{ selectedInventory?.version }}</p>
      </div>
      <template #footer>
        <el-button @click="showAdjust = false">
          取消
        </el-button>
        <el-button
          type="primary"
          @click="adjustInventory"
        >
          确认调整
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>
