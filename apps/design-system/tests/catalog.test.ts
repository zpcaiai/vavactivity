import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import App from "../src/App.vue";

describe("design system catalog", () => {
  it("exposes landmarks, a skip link, governed states and synthetic records", () => {
    const wrapper = mount(App, { global: { stubs: { Teleport: true } } });
    expect(wrapper.get("a.v-skip-link").attributes("href")).toBe("#main-content");
    expect(wrapper.get("main#main-content").attributes("id")).toBe("main-content");
    expect(wrapper.text()).toContain("部分数据可用");
    expect(wrapper.text()).toContain("示例规则 A");
    expect(wrapper.findAll("h1")).toHaveLength(3);
  });
});
