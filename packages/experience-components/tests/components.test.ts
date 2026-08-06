import { mount } from "@vue/test-utils";
import { expect, it } from "vitest";
import { ExperienceBreadcrumbs, ExperienceTaskCard } from "../src";
it("marks the current breadcrumb", () => expect(mount(ExperienceBreadcrumbs, { props: { items: [{ label: "首页", href: "/" }, { label: "任务", href: "/tasks" }] } }).find("[aria-current=page]").text()).toBe("任务"));
it("keeps a task status route", () => expect(mount(ExperienceTaskCard, { props: { title: "处理", description: "查看状态", state: "waiting", href: "/status" } }).get("a").attributes("href")).toBe("/status"));
