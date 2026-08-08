<script setup lang="ts">
import ProductPrice from "./ProductPrice.vue";
import PromotionBadge from "./PromotionBadge.vue";
import type { PricingQuote } from "../types";

defineProps<{
  quote: PricingQuote;
}>();
</script>

<template>
  <aside class="pricing-summary">
    <h3>报价明细</h3>
    <dl>
      <div>
        <dt>小计</dt>
        <dd>
          <ProductPrice
            :amount-minor="quote.subtotal_minor"
            :currency="quote.currency"
          />
        </dd>
      </div>
      <div
        v-for="discount in quote.discounts"
        :key="discount.promotion_code"
      >
        <dt>
          <PromotionBadge :code="discount.promotion_code" />
        </dt>
        <dd>
          −<ProductPrice
            :amount-minor="discount.discount_amount_minor"
            :currency="quote.currency"
          />
        </dd>
      </div>
      <div class="pricing-total">
        <dt>合计</dt>
        <dd>
          <ProductPrice
            :amount-minor="quote.total_minor"
            :currency="quote.currency"
          />
        </dd>
      </div>
    </dl>
    <p>
      报价有效至 {{ new Date(quote.expires_at).toLocaleString() }}。此报价不是付款凭证，也不会自动开通服务。
    </p>
  </aside>
</template>
