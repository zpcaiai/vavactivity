import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import AdminDataTable from "../src/tables/AdminDataTable.vue";
describe("admin patterns", () => { it("preserves table semantics and masks sensitive cells", () => { const wrapper = mount(AdminDataTable, { props: { caption: "发布审核", rowKey: "id", columns: [{ key: "name", label: "名称", priority: "primary" }, { key: "secret", label: "秘密", sensitive: true }], rows: [{ id: "1", name: "版本 A", secret: "never render" }] } }); expect(wrapper.find("caption").text()).toBe("发布审核"); expect(wrapper.text()).not.toContain("never render"); expect(wrapper.text()).toContain("••••"); }); });

describe("admin audit table", () => {
  it("renders audit headers and values as meaningful Chinese copy", () => {
    const wrapper = mount(AdminDataTable, {
      props: {
        caption: "认证审计",
        rowKey: "id",
        columns: [
          { key: "event_type", label: "event_type" },
          { key: "severity", label: "severity" },
          { key: "actor_type", label: "actor_type" },
          { key: "target_type", label: "target_type" },
          { key: "metadata", label: "metadata" },
          { key: "occurred_at", label: "occurred_at" },
        ],
        rows: [{
          id: "audit-1",
          event_type: "auth.login.failed",
          severity: "warning",
          actor_type: "user",
          target_type: "content_entry",
          metadata: { attempt_count: 2, status: "failed" },
          occurred_at: "2026-08-11T11:12:33.174558Z",
        }],
      },
    });

    expect(wrapper.text()).toContain("事件类型");
    expect(wrapper.text()).toContain("严重程度");
    expect(wrapper.text()).toContain("操作者类型");
    expect(wrapper.text()).toContain("操作对象类型");
    expect(wrapper.text()).toContain("附加信息");
    expect(wrapper.text()).toContain("发生时间（UTC+8）");
    expect(wrapper.text()).toContain("用户登录失败");
    expect(wrapper.text()).toContain("警告");
    expect(wrapper.text()).toContain("内容条目");
    expect(wrapper.text()).toContain("尝试次数：2；状态：失败");
    expect(wrapper.text()).toContain("2026-08-11 19:12:33（UTC+8）");
    expect(wrapper.text()).not.toContain("[object Object]");
  });
});
