<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { catalogApi } from "@/features/catalog/api";

interface Product {
  id: string;
  product_code: string;
  product_type: string;
  internal_name: string;
  status: string;
  default_locale: string;
  version: number;
  localizations: Record<string, {
    slug: string;
    name: string;
    short_description: string | null;
    description_blocks: Array<Record<string, unknown>>;
    seo_title: string | null;
    seo_description: string | null;
    cover_media_id: string | null;
    translation_status: string;
  }>;
}

interface Sku {
  id: string;
  sku_code: string;
  internal_name: string;
  billing_type: string;
  inventory_policy: string;
  status: string;
  version: number;
}

interface Price {
  id: string;
  currency_code: string;
  unit_amount_minor: number;
  status: string;
  valid_from: string;
}

const route = useRoute();
const productId = computed(() => String(route.params.id));
const product = ref<Product | null>(null);
const skus = ref<Sku[]>([]);
const error = ref("");
const busy = ref(false);
const showSku = ref(false);
const showPrice = ref(false);
const showInventory = ref(false);
const showLocalization = ref(false);
const selectedSku = ref<Sku | null>(null);
const pricesBySku = ref<Record<string, Price[]>>({});
const localizationForm = ref({
  locale: "zh-CN",
  slug: "",
  name: "",
  shortDescription: "",
  seoTitle: "",
  seoDescription: "",
  translationStatus: "draft"
});
const skuForm = ref({
  code: "",
  name: "",
  billingType: "one_time",
  inventoryPolicy: "unlimited",
  referenceId: "",
  ticketType: "general",
  serviceCode: ""
});
const priceForm = ref({
  priceBookId: "",
  currency: "USD",
  amountMinor: 0,
  interval: "month",
  intervalCount: 1
});
const inventoryForm = ref({
  totalCapacity: 0,
  safetyStock: 0,
  oversellingAllowed: false,
  oversellLimit: 0,
  reason: ""
});

async function load() {
  busy.value = true;
  error.value = "";
  try {
    product.value = await catalogApi<Product>(`/admin/catalog/products/${productId.value}`);
    const result = await catalogApi<{ items: Sku[] }>(
      `/admin/catalog/products/${productId.value}/skus`
    );
    skus.value = result.items;
    pricesBySku.value = Object.fromEntries(
      await Promise.all(result.items.map(async (sku) => {
        const priceResult = await catalogApi<{ items: Price[] }>(
          `/admin/catalog/skus/${sku.id}/prices`
        );
        return [sku.id, priceResult.items] as const;
      }))
    );
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "加载失败";
  } finally {
    busy.value = false;
  }
}

function openLocalization(locale = "zh-CN") {
  const existing = product.value?.localizations[locale];
  localizationForm.value = {
    locale,
    slug: existing?.slug ?? `${product.value?.product_code.toLowerCase().replaceAll("_", "-")}-${locale.toLowerCase()}`,
    name: existing?.name ?? "",
    shortDescription: existing?.short_description ?? "",
    seoTitle: existing?.seo_title ?? "",
    seoDescription: existing?.seo_description ?? "",
    translationStatus: existing?.translation_status ?? "draft"
  };
  showLocalization.value = true;
}

async function saveLocalization() {
  if (!product.value) {
    return;
  }
  const existing = product.value.localizations[localizationForm.value.locale];
  try {
    await catalogApi(
      `/admin/catalog/products/${product.value.id}/localizations/${localizationForm.value.locale}`,
      {
        method: "PUT",
        body: JSON.stringify({
          locale: localizationForm.value.locale,
          slug: localizationForm.value.slug,
          name: localizationForm.value.name,
          short_description: localizationForm.value.shortDescription || null,
          description_blocks: existing?.description_blocks ?? [],
          seo_title: localizationForm.value.seoTitle || null,
          seo_description: localizationForm.value.seoDescription || null,
          cover_media_id: existing?.cover_media_id ?? null,
          translation_status: localizationForm.value.translationStatus,
          expected_version: product.value.version,
          reason: `Update ${localizationForm.value.locale} product localization after editorial review`
        })
      }
    );
    showLocalization.value = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "商品翻译保存失败";
  }
}

function fulfillmentConfiguration() {
  const type = product.value?.product_type;
  if (type === "activity_ticket") {
    return { activity_id: skuForm.value.referenceId, ticket_type: skuForm.value.ticketType };
  }
  if (type === "course" || type === "course_bundle") {
    return { course_id: skuForm.value.referenceId };
  }
  if (type === "counseling_session" || type === "counseling_package") {
    return {
      counseling_service_id: skuForm.value.referenceId,
      session_count: 1,
      validity_days: 180
    };
  }
  if (type === "ai_credit_package" || type === "ai_subscription") {
    return { credit_count: 20, validity_days: 90 };
  }
  if (type === "membership") {
    return { membership_tier: "premium", duration_days: 365 };
  }
  return { service_code: skuForm.value.serviceCode || skuForm.value.code.toLowerCase() };
}

async function createSku() {
  try {
    await catalogApi(`/admin/catalog/products/${productId.value}/skus`, {
      method: "POST",
      body: JSON.stringify({
        sku_code: skuForm.value.code.toUpperCase(),
        internal_name: skuForm.value.name,
        billing_type: skuForm.value.billingType,
        fulfillment_configuration: fulfillmentConfiguration(),
        inventory_policy: skuForm.value.inventoryPolicy
      })
    });
    showSku.value = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "SKU 创建失败";
  }
}

function openPrice(sku: Sku) {
  selectedSku.value = sku;
  showPrice.value = true;
}

function openInventory(sku: Sku) {
  selectedSku.value = sku;
  showInventory.value = true;
}

async function configureInventory() {
  if (!selectedSku.value) {
    return;
  }
  try {
    await catalogApi(`/admin/catalog/inventory/${selectedSku.value.id}`, {
      method: "PUT",
      body: JSON.stringify({
        total_capacity: inventoryForm.value.totalCapacity,
        safety_stock: inventoryForm.value.safetyStock,
        overselling_allowed: inventoryForm.value.oversellingAllowed,
        oversell_limit: inventoryForm.value.oversellLimit,
        reason: inventoryForm.value.reason
      })
    });
    showInventory.value = false;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "库存配置失败";
  }
}

async function setSkuStatus(sku: Sku, action: string) {
  try {
    await catalogApi(`/admin/catalog/skus/${sku.id}/${action}`, {
      method: "POST",
      body: JSON.stringify({
        reason: `Administration SKU ${action} after fulfillment review`
      })
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "SKU 状态变更失败";
  }
}

async function createPrice() {
  if (!selectedSku.value) {
    return;
  }
  try {
    const price = await catalogApi<Price>(`/admin/catalog/skus/${selectedSku.value.id}/prices`, {
      method: "POST",
      body: JSON.stringify({
        price_book_id: priceForm.value.priceBookId,
        currency_code: priceForm.value.currency,
        unit_amount_minor: priceForm.value.amountMinor,
        billing_type: selectedSku.value.billing_type,
        billing_interval: selectedSku.value.billing_type === "recurring"
          ? priceForm.value.interval
          : null,
        billing_interval_count: selectedSku.value.billing_type === "recurring"
          ? priceForm.value.intervalCount
          : null,
        valid_from: new Date().toISOString()
      })
    });
    await catalogApi(`/admin/catalog/prices/${price.id}/activate`, {
      method: "POST",
      body: JSON.stringify({
        reason: "Activate newly reviewed price from the product editor"
      })
    });
    showPrice.value = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "价格创建失败";
  }
}

async function setPriceStatus(price: Price, action: "activate" | "expire") {
  try {
    await catalogApi(`/admin/catalog/prices/${price.id}/${action}`, {
      method: "POST",
      body: JSON.stringify({
        reason: `Administration price ${action} after pricing review`
      })
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "价格状态变更失败";
  }
}

async function transition(action: string) {
  try {
    await catalogApi(`/admin/catalog/products/${productId.value}/${action}`, {
      method: "POST",
      body: JSON.stringify({
        reason: `Administration product center ${action} after catalog review`
      })
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "状态变更失败";
  }
}

onMounted(() => void load());
</script>

<template>
  <section v-loading="busy">
    <header class="page-toolbar">
      <div>
        <p class="admin-kicker">
          PRODUCT / SKU / PRICE
        </p>
        <h2>{{ product?.internal_name }}</h2>
        <p>{{ product?.product_code }} · {{ product?.status }}</p>
      </div>
      <div class="toolbar-actions">
        <el-button
          v-if="product?.status === 'draft'"
          @click="transition('submit-review')"
        >
          提交审核
        </el-button>
        <el-button
          v-if="product?.status === 'in_review'"
          v-permission="'catalog.products.publish'"
          type="primary"
          @click="transition('publish')"
        >
          上架
        </el-button>
        <el-button @click="showSku = true">
          新建 SKU
        </el-button>
        <el-button @click="openLocalization(product?.default_locale ?? 'zh-CN')">
          编辑多语言
        </el-button>
      </div>
    </header>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
    />
    <div
      v-if="product"
      class="localization-status-list"
    >
      <el-button
        v-for="locale in ['zh-CN', 'zh-TW', 'en']"
        :key="locale"
        size="small"
        @click="openLocalization(locale)"
      >
        {{ locale }} · {{ product.localizations[locale]?.translation_status ?? "missing" }}
      </el-button>
    </div>
    <el-table :data="skus">
      <el-table-column
        prop="sku_code"
        label="SKU"
      />
      <el-table-column
        prop="internal_name"
        label="名称"
      />
      <el-table-column
        prop="billing_type"
        label="计费"
      />
      <el-table-column
        prop="inventory_policy"
        label="库存策略"
      />
      <el-table-column
        prop="status"
        label="状态"
      />
      <el-table-column label="操作">
        <template #default="{ row }">
          <el-button
            size="small"
            @click="openPrice(row)"
          >
            新建价格
          </el-button>
          <el-button
            v-if="row.inventory_policy !== 'unlimited'"
            size="small"
            @click="openInventory(row)"
          >
            配置库存
          </el-button>
          <el-button
            v-if="row.status !== 'active'"
            size="small"
            type="primary"
            @click="setSkuStatus(row, 'activate')"
          >
            启用
          </el-button>
        </template>
      </el-table-column>
      <el-table-column
        label="价格"
        min-width="220"
      >
        <template #default="{ row }">
          <div
            v-for="price in pricesBySku[row.id] ?? []"
            :key="price.id"
            class="price-status-row"
          >
            <span>{{ price.currency_code }} {{ price.unit_amount_minor }} · {{ price.status }}</span>
            <el-button
              v-if="price.status === 'draft'"
              link
              type="primary"
              @click.stop="setPriceStatus(price, 'activate')"
            >
              启用
            </el-button>
            <el-button
              v-if="price.status === 'active'"
              link
              @click.stop="setPriceStatus(price, 'expire')"
            >
              失效
            </el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
    <el-dialog
      v-model="showLocalization"
      title="商品多语言内容"
      width="720px"
    >
      <div class="editor-form">
        <label>语言<el-select
          v-model="localizationForm.locale"
          @change="openLocalization(localizationForm.locale)"
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
        </el-select></label>
        <label>Slug<el-input v-model="localizationForm.slug" /></label>
        <label>公开名称<el-input v-model="localizationForm.name" /></label>
        <label>简短描述<el-input
          v-model="localizationForm.shortDescription"
          type="textarea"
        /></label>
        <label>SEO 标题<el-input v-model="localizationForm.seoTitle" /></label>
        <label>SEO 描述<el-input
          v-model="localizationForm.seoDescription"
          type="textarea"
        /></label>
        <label>翻译状态<el-select v-model="localizationForm.translationStatus">
          <el-option
            label="草稿"
            value="draft"
          />
          <el-option
            label="需要审核"
            value="review_required"
          />
          <el-option
            label="已就绪"
            value="ready"
          />
          <el-option
            label="已过期"
            value="outdated"
          />
        </el-select></label>
      </div>
      <template #footer>
        <el-button @click="showLocalization = false">
          取消
        </el-button>
        <el-button
          type="primary"
          @click="saveLocalization"
        >
          保存翻译
        </el-button>
      </template>
    </el-dialog>
    <el-dialog
      v-model="showSku"
      title="新建 SKU"
      width="640px"
    >
      <div class="editor-form">
        <label>SKU 编码<el-input v-model="skuForm.code" /></label>
        <label>内部名称<el-input v-model="skuForm.name" /></label>
        <label>计费类型<el-select v-model="skuForm.billingType">
          <el-option
            label="一次性"
            value="one_time"
          />
          <el-option
            label="周期订阅"
            value="recurring"
          />
          <el-option
            label="免费"
            value="free"
          />
        </el-select></label>
        <label>库存策略<el-select v-model="skuForm.inventoryPolicy">
          <el-option
            label="无限"
            value="unlimited"
          />
          <el-option
            label="有限库存"
            value="finite"
          />
          <el-option
            label="服务容量"
            value="service_capacity"
          />
        </el-select></label>
        <label>业务对象 UUID<el-input v-model="skuForm.referenceId" /></label>
        <label>数字服务编码<el-input v-model="skuForm.serviceCode" /></label>
      </div>
      <template #footer>
        <el-button @click="showSku = false">
          取消
        </el-button>
        <el-button
          type="primary"
          @click="createSku"
        >
          保存
        </el-button>
      </template>
    </el-dialog>
    <el-dialog
      v-model="showPrice"
      title="创建不可变价格草稿"
      width="640px"
    >
      <div class="editor-form">
        <label>Price Book UUID<el-input v-model="priceForm.priceBookId" /></label>
        <label>币种<el-select v-model="priceForm.currency">
          <el-option
            label="CNY"
            value="CNY"
          />
          <el-option
            label="USD"
            value="USD"
          />
          <el-option
            label="TWD"
            value="TWD"
          />
          <el-option
            label="HKD"
            value="HKD"
          />
        </el-select></label>
        <label>最小货币单位金额<el-input v-model.number="priceForm.amountMinor" /></label>
      </div>
      <template #footer>
        <el-button @click="showPrice = false">
          取消
        </el-button>
        <el-button
          type="primary"
          @click="createPrice"
        >
          保存价格草稿
        </el-button>
      </template>
    </el-dialog>
    <el-dialog
      v-model="showInventory"
      title="配置库存或服务容量"
      width="640px"
    >
      <div class="editor-form">
        <label>总容量<el-input v-model.number="inventoryForm.totalCapacity" /></label>
        <label>安全库存<el-input v-model.number="inventoryForm.safetyStock" /></label>
        <label>超卖上限<el-input v-model.number="inventoryForm.oversellLimit" /></label>
        <label>调整原因<el-input v-model="inventoryForm.reason" /></label>
      </div>
      <template #footer>
        <el-button @click="showInventory = false">
          取消
        </el-button>
        <el-button
          type="primary"
          @click="configureInventory"
        >
          保存配置
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>
