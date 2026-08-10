import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import AdminDataTable from "../src/tables/AdminDataTable.vue";
describe("admin patterns", () => { it("preserves table semantics and masks sensitive cells", () => { const wrapper = mount(AdminDataTable, { props: { caption: "发布审核", rowKey: "id", columns: [{ key: "name", label: "名称", priority: "primary" }, { key: "secret", label: "秘密", sensitive: true }], rows: [{ id: "1", name: "版本 A", secret: "never render" }] } }); expect(wrapper.find("caption").text()).toBe("发布审核"); expect(wrapper.text()).not.toContain("never render"); expect(wrapper.text()).toContain("••••"); }); });
