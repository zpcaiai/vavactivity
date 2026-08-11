import { describe, expect, it } from "vitest";

import {
  adminColumnMinWidth,
  formatAdminDate,
  localizeAdminLabel,
  localizeAdminValue,
} from "../src/display";

describe("admin Chinese display", () => {
  it("formats timestamps in UTC+8", () => {
    expect(formatAdminDate("2026-08-11T08:28:23.720Z")).toBe("2026-08-11 16:28:23（UTC+8）");
  });

  it("adds the timezone to date headers", () => {
    expect(localizeAdminLabel("updated_at", "更新时间")).toBe("更新时间（UTC+8）");
    expect(localizeAdminLabel("trigger_at")).toBe("触发时间（UTC+8）");
    expect(localizeAdminLabel("unmapped_field", "Unmapped Field")).toBe("字段（Unmapped Field）");
  });

  it("localizes common enum and locale values", () => {
    expect(localizeAdminValue("active", "status")).toBe("启用");
    expect(localizeAdminValue("course_bundle", "product_type")).toBe("课程组合");
    expect(localizeAdminValue("zh-CN", "default_locale")).toBe("简体中文");
    expect(localizeAdminValue(true, "featured")).toBe("是");
  });

  it("renders record content with Chinese field labels", () => {
    expect(localizeAdminValue({ status: "pending", updated_at: "2026-08-11T00:00:00Z" })).toContain("状态：待处理");
    expect(localizeAdminValue({ status: "pending", updated_at: "2026-08-11T00:00:00Z" })).toContain("更新时间（UTC+8）：2026-08-11 08:00:00（UTC+8）");
  });

  it("uses meaningful Chinese labels for authentication audit columns", () => {
    expect(localizeAdminLabel("id")).toBe("编号");
    expect(localizeAdminLabel("event_type")).toBe("事件类型");
    expect(localizeAdminLabel("severity")).toBe("严重程度");
    expect(localizeAdminLabel("actor_type")).toBe("操作者类型");
    expect(localizeAdminLabel("actor_user_id")).toBe("操作者用户编号");
    expect(localizeAdminLabel("target_type")).toBe("操作对象类型");
    expect(localizeAdminLabel("target_id")).toBe("操作对象编号");
    expect(localizeAdminLabel("reason")).toBe("操作原因");
    expect(localizeAdminLabel("metadata")).toBe("附加信息");
    expect(localizeAdminLabel("occurred_at")).toBe("发生时间（UTC+8）");
  });

  it("translates authentication audit values and structured metadata", () => {
    expect(localizeAdminValue("auth.login.succeeded", "event_type")).toBe("用户登录成功");
    expect(localizeAdminValue("auth.login.failed", "event_type")).toBe("用户登录失败");
    expect(localizeAdminValue("auth.registration.created", "event_type")).toBe("用户注册完成");
    expect(localizeAdminValue("content.entry.submit_review", "event_type")).toBe("内容已提交审核");
    expect(localizeAdminValue("content.site_setting.rolled_back", "event_type")).toBe("网站设置已回滚");
    expect(localizeAdminValue("reschedule_requested", "status")).toBe("等待确认改期");
    expect(localizeAdminValue("info", "severity")).toBe("信息");
    expect(localizeAdminValue("warning", "severity")).toBe("警告");
    expect(localizeAdminValue("user", "actor_type")).toBe("用户");
    expect(localizeAdminValue("admin", "actor_type")).toBe("管理员");
    expect(localizeAdminValue("content_entry", "target_type")).toBe("内容条目");
    expect(localizeAdminValue({}, "metadata")).toBe("—");
    expect(localizeAdminValue({ status: "failed", attempt_count: 2 }, "metadata")).toBe(
      "状态：失败；尝试次数：2",
    );
  });

  it("keeps audit identifiers and descriptions readable", () => {
    expect(adminColumnMinWidth("actor_user_id")).toBe(220);
    expect(adminColumnMinWidth("reason")).toBe(280);
    expect(adminColumnMinWidth("occurred_at")).toBe(220);
    expect(
      localizeAdminValue(
        "Administration workflow: submit-review content after editorial review",
        "reason",
      ),
    ).toBe("管理流程：编辑复核后提交内容审核");
  });
});
