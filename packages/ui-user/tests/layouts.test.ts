import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import UserPageLayout from "../src/layouts/UserPageLayout.vue";

describe("user layouts", () => { it("provides one primary heading and registered width", () => { const wrapper = mount(UserPageLayout, { props: { title: "隐私中心", width: "reading" } }); expect(wrapper.findAll("h1")).toHaveLength(1); expect(wrapper.attributes("data-width")).toBe("reading"); }); });
