import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import LanguageGateway from "./LanguageGateway.vue";

describe("LanguageGateway", () => {
  it("offers all supported languages without declaring a launch default", () => {
    const wrapper = mount(LanguageGateway, {
      global: {
        stubs: { RouterLink: { template: "<a><slot /></a>" } }
      }
    });
    expect(wrapper.text()).toContain("简体中文");
    expect(wrapper.text()).toContain("繁體中文");
    expect(wrapper.text()).toContain("English");
    expect(wrapper.text()).toContain("首发语言尚待业务确认");
  });
});
