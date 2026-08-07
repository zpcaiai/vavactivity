import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import LoadingState from "./LoadingState.vue";

describe("LoadingState", () => {
  it("announces the supplied loading label", () => {
    const wrapper = mount(LoadingState, { props: { label: "正在载入活动" } });
    expect(wrapper.get('[role="status"]').text()).toContain("正在载入活动");
  });
});

