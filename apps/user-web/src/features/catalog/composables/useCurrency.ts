import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

const supported = ["CNY", "USD", "TWD", "HKD"] as const;
export type CatalogCurrency = (typeof supported)[number];

function isCurrency(value: unknown): value is CatalogCurrency {
  return typeof value === "string" && supported.includes(value as CatalogCurrency);
}

export function useCurrency() {
  const route = useRoute();
  const router = useRouter();
  const queryCurrency = route.query.currency;
  const stored = window.localStorage.getItem("vav.catalog.currency");
  const currency = ref<CatalogCurrency>(
    isCurrency(queryCurrency)
      ? queryCurrency
      : isCurrency(stored)
        ? stored
        : "USD"
  );

  watch(currency, async (value) => {
    window.localStorage.setItem("vav.catalog.currency", value);
    await router.replace({ query: { ...route.query, currency: value } });
  });

  return {
    currency,
    currencies: computed(() => supported)
  };
}
