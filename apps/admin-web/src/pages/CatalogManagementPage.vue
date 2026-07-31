<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { catalogApi } from "@/features/catalog/api";

interface CatalogRow {
  id: string;
  sku_id?: string;
  product_code?: string;
  internal_name?: string;
  product_type?: string;
  sku_count?: number;
  status?: string;
  version?: number;
  price_book_code?: string;
  name?: string;
  inventory_policy?: string;
  total_capacity?: number | null;
  reserved_quantity?: number;
  sold_quantity?: number;
  promotion_code?: string;
  display_code?: string;
  currency_code?: string;
  unit_amount_minor?: number;
}

const route = useRoute();
const router = useRouter();
const section = computed(() => String(route.meta.catalogSection ?? "products"));
const rows = ref<CatalogRow[]>([]);
const loading = ref(false);
const error = ref("");
const showCreate = ref(false);
const showAdjust = ref(false);
const selectedInventory = ref<CatalogRow | null>(null);
const adjustment = ref({ quantityDelta: 0, reason: "" });
const form = ref({
  code: "",
  internalName: "",
  name: "",
  productType: "digital_service",
  locale: "zh-CN",
  priority: 0,
  promotionType: "percentage",
  applicationMode: "automatic",
  percentage: 1000,
  promotionId: ""
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

async function create() {
  error.value = "";
  let body: Record<string, unknown>;
  if (section.value === "products") {
    body = {
      product_code: form.value.code.toUpperCase(),
      product_type: form.value.productType,
      fulfillment_type: fulfillmentByProductType[form.value.productType],
      internal_name: form.value.internalName,
      default_locale: form.value.locale,
      localizations: [{
        locale: form.value.locale,
        slug: form.value.code.toLowerCase().replaceAll("_", "-"),
        name: form.value.name,
        description_blocks: [],
        translation_status: "draft"
      }]
    };
  } else if (section.value === "price-books") {
    body = {
      price_book_code: form.value.code.toUpperCase(),
      name: form.value.name,
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
        percentage_basis_points: form.value.percentage
      },
      valid_from: new Date().toISOString()
    };
  } else {
    body = {
      promotion_id: form.value.promotionId,
      code: form.value.code
    };
  }
  try {
    await catalogApi(endpoint.value, {
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

onMounted(() => void load());
watch(section, () => void load());
</script>

<template>
  <section v-loading="loading">
    <header class="page-toolbar">
      <div>
        <p class="admin-kicker">
          CATALOG CONTROL PLANE
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
        prop="product_code"
        label="商品编码"
      />
      <el-table-column
        prop="price_book_code"
        label="价格簿编码"
      />
      <el-table-column
        prop="promotion_code"
        label="优惠编码"
      />
      <el-table-column
        prop="display_code"
        label="优惠码"
      />
      <el-table-column
        prop="currency_code"
        label="币种"
      />
      <el-table-column
        prop="unit_amount_minor"
        label="最小单位金额"
      />
      <el-table-column
        prop="internal_name"
        label="内部名称"
      />
      <el-table-column
        prop="name"
        label="名称"
      />
      <el-table-column
        prop="product_type"
        label="类型"
      />
      <el-table-column
        prop="inventory_policy"
        label="库存策略"
      />
      <el-table-column
        prop="total_capacity"
        label="总容量"
      />
      <el-table-column
        prop="reserved_quantity"
        label="预留"
      />
      <el-table-column
        prop="sold_quantity"
        label="已售"
      />
      <el-table-column
        prop="status"
        label="状态"
      />
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
        <label v-if="section === 'promotions'">
          折扣基点（1000 = 10%）<el-input v-model.number="form.percentage" />
        </label>
        <label v-if="section === 'coupons'">
          优惠活动 UUID<el-input v-model="form.promotionId" />
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
