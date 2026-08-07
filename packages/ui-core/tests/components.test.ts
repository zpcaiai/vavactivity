import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import VButton from "../src/components/VButton.vue";
import VModal from "../src/components/VModal.vue";
import VStatusBadge from "../src/components/VStatusBadge.vue";

describe("accessible foundation components", () => {
  it("prevents duplicate actions while loading", async () => {
    const wrapper = mount(VButton, { props: { loading: true } });
    await wrapper.trigger("click");
    expect(wrapper.emitted("click")).toBeUndefined();
    expect(wrapper.attributes("aria-busy")).toBe("true");
  });

  it("does not represent status by color alone", () => {
    const wrapper = mount(VStatusBadge, { props: { status: "danger", label: "发布失败" } });
    expect(wrapper.text()).toContain("×");
    expect(wrapper.text()).toContain("发布失败");
  });

  it("moves focus into a modal, closes on escape and restores focus", async () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const wrapper = mount(VModal, { attachTo: document.body, props: { open: false, title: "确认操作" } });
    await wrapper.setProps({ open: true });
    await nextTick();
    expect(document.activeElement?.tagName).toBe("BUTTON");
    const dialog = document.querySelector<HTMLElement>("[role='dialog']");
    expect(dialog).not.toBeNull();
    dialog?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(wrapper.emitted("close")).toHaveLength(1);
    await wrapper.setProps({ open: false });
    expect(document.activeElement).toBe(opener);
    wrapper.unmount(); opener.remove(); vi.restoreAllMocks();
  });
});
