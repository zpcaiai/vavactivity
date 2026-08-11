export const ADMIN_TIME_ZONE = "Asia/Shanghai";
export const ADMIN_TIME_ZONE_LABEL = "UTC+8";

const fieldLabels: Record<string, string> = {
  id: "编号",
  code: "代码",
  name: "名称",
  title: "标题",
  description: "说明",
  status: "状态",
  state: "状态",
  type: "类型",
  kind: "类别",
  locale: "语言",
  provider: "服务商",
  channel: "渠道",
  source: "来源",
  visibility: "可见性",
  created_at: "创建时间（UTC+8）",
  createdAt: "创建时间（UTC+8）",
  updated_at: "更新时间（UTC+8）",
  updatedAt: "更新时间（UTC+8）",
  published_at: "发布时间（UTC+8）",
  starts_at: "开始时间（UTC+8）",
  ends_at: "结束时间（UTC+8）",
  valid_from: "生效时间（UTC+8）",
  valid_until: "失效时间（UTC+8）",
  expires_at: "过期时间（UTC+8）",
  occurred_at: "发生时间（UTC+8）",
  requested_at: "申请时间（UTC+8）",
  resolved_at: "处理时间（UTC+8）",
  last_exposed_at: "最近曝光时间（UTC+8）",
  started_at: "开始时间（UTC+8）",
  scheduled_starts_at: "计划开始时间（UTC+8）",
  trigger_at: "触发时间（UTC+8）",
  promotion_offer_expires_at: "邀请到期时间（UTC+8）",
  product_code: "商品编码",
  product_type: "商品类型",
  fulfillment_type: "履约方式",
  internal_name: "内部名称",
  default_locale: "默认语言",
  category_id: "分类编号",
  sku_count: "SKU 数量",
  purchasable_from: "可售开始时间（UTC+8）",
  purchasable_until: "可售截止时间（UTC+8）",
  featured: "精选",
  sort_order: "排序权重",
  version: "版本",
  current_stage_code: "当前阶段",
  record_state: "记录状态",
  identifier: "标识",
  decision: "判定",
  severity: "严重程度",
  event_type: "事件类型",
  actor_type: "操作者类型",
  actor_user_id: "操作者用户编号",
  actor_session_id: "操作者会话编号",
  target_type: "操作对象类型",
  target_id: "操作对象编号",
  request_id: "请求编号",
  reason: "操作原因",
  metadata: "附加信息",
  event_metadata: "附加信息",
  before_state: "变更前状态",
  after_state: "变更后状态",
  ip_address_hash: "IP 地址哈希",
  user_agent_hash: "浏览器标识哈希",
  subject_type: "对象类型",
  request_type: "申请类型",
  attempt_count: "尝试次数",
  translation_status: "翻译状态",
};

const tokenLabels: Record<string, string> = {
  id: "编号", code: "代码", name: "名称", title: "标题", status: "状态", state: "状态",
  type: "类型", kind: "类别", record: "记录", current: "当前", stage: "阶段", source: "来源",
  target: "目标", subject: "对象", event: "事件", request: "申请", response: "响应", reason: "原因",
  actor: "操作者", session: "会话", metadata: "附加信息", before: "变更前", after: "变更后",
  address: "地址", hash: "哈希", agent: "浏览器标识", action: "操作", role: "角色", rbac: "角色权限",
  created: "创建", updated: "更新", published: "发布", requested: "申请", resolved: "处理", occurred: "发生",
  start: "开始", starts: "开始", end: "结束", ends: "结束", valid: "有效", from: "起始", until: "截止",
  expires: "过期", last: "最近", time: "时间", date: "日期", at: "时间", count: "数量", total: "总计",
  active: "启用", enabled: "启用", disabled: "停用", pending: "待处理", approved: "已批准",
  rejected: "已拒绝", completed: "已完成", failed: "失败", draft: "草稿", archived: "已归档",
  public: "公开", private: "私密", internal: "内部", missing: "缺失", verified: "已验证",
  production: "生产", certified: "已认证", not: "未", course: "课程", activity: "活动", counseling: "咨询",
  membership: "会员", digital: "数字", service: "服务", access: "访问", bundle: "组合", package: "套餐",
  subscription: "订阅", ticket: "票务", admission: "准入", appointment: "预约",
  credits: "次数", credit: "次数", entitlement: "权益", ai: "AI", email: "邮件", sms: "短信",
  push: "推送", in: "站内", app: "应用", system: "系统", manual: "手动", automatic: "自动",
  percentage: "百分比", fixed: "固定", amount: "金额", once: "一次性", recurring: "周期性",
  monthly: "每月", yearly: "每年", daily: "每日", weekly: "每周", visible: "可见", hidden: "隐藏",
  low: "低", medium: "中", high: "高", critical: "严重", open: "待处理", closed: "已关闭",
  recorded: "已记录", success: "成功", succeeded: "成功", warning: "警告", info: "信息", blocked: "已阻断", ready: "就绪",
  user: "用户", admin: "管理员", profile: "档案", policy: "策略", rule: "规则", template: "模板",
  delivery: "投递", provider: "服务商", locale: "语言", channel: "渠道", visibility: "可见性",
  default: "默认", language: "语言", product: "商品", fulfillment: "履约", category: "分类",
  price: "价格", inventory: "库存", promotion: "优惠", campaign: "活动", notification: "通知",
  processing: "处理", translation: "翻译", anonymous: "匿名", member: "成员", members: "成员",
  decision: "判定", severity: "严重程度", primary: "主要", metric: "指标", signal: "信号",
  sku: "SKU", scheduled: "计划", trigger: "触发", offer: "邀请", exposed: "曝光", purchasable: "可售",
  auth: "身份认证", login: "登录", registration: "注册", account: "账户", password: "密码", reset: "重置",
  refresh: "刷新", token: "令牌", reuse: "重复使用", detected: "已检测", family: "系列", revoked: "已撤销",
  removed: "已移除", locked: "已锁定", verification: "验证", sent: "已发送", bypassed: "已绕过",
  invitation: "邀请", accepted: "已接受", restored: "已恢复", suspended: "已暂停", assigned: "已分配",
  content: "内容", entry: "条目", submit: "提交", review: "审核", version: "版本",
  changed: "已变更", media: "媒体", deleted: "已删除", navigation: "导航",
  site: "网站", setting: "设置", contact: "联系", submission: "提交记录",
  yes: "是", no: "否", true: "是", false: "否", zh: "中文", en: "英文",
};

const exactValues: Record<string, string> = {
  "zh-CN": "简体中文",
  "zh-TW": "繁体中文",
  en: "英文",
  "en-US": "英文（美国）",
  active: "启用",
  inactive: "停用",
  enabled: "启用",
  disabled: "停用",
  pending: "待处理",
  pending_review: "待运营审核",
  deletion_pending: "等待注销",
  time_proposed: "已提出新时间",
  approved_pending_payment: "已批准，等待支付",
  confirmed: "已确认",
  reschedule_requested: "等待确认改期",
  manual_review: "需要人工复核",
  no_show: "未到场",
  in_review: "审核中",
  approval_required: "待审批",
  changes_required: "需要修改",
  draft: "草稿",
  published: "已发布",
  approved: "已批准",
  rejected: "已拒绝",
  completed: "已完成",
  processed: "已处理",
  processing: "处理中",
  queued: "排队中",
  scheduled: "已计划",
  delivered: "已送达",
  sent: "已发送",
  bounced: "已退回",
  suppressed: "已抑制",
  paused: "已暂停",
  cancelled: "已取消",
  canceled: "已取消",
  expired: "已过期",
  resolved: "已解决",
  invalidated: "已失效",
  quarantined: "已隔离",
  registration_open: "报名开放",
  registration_closed: "报名关闭",
  failed: "失败",
  archived: "已归档",
  public: "公开",
  private: "私密",
  internal: "内部可见",
  missing: "缺失",
  verified: "已验证",
  recorded: "已记录",
  open: "待处理",
  closed: "已关闭",
  success: "成功",
  warning: "警告",
  blocked: "已阻断",
  ready: "就绪",
  course: "课程",
  course_bundle: "课程组合",
  activity_ticket: "活动票务",
  counseling_session: "咨询服务",
  counseling_schedule: "辅导排班",
  counseling_followup: "辅导跟进",
  counseling_package: "咨询套餐",
  ai_credit_package: "AI 次数包",
  ai_subscription: "AI 订阅",
  membership: "会员权益",
  digital_service: "数字服务",
  digital_access: "数字访问",
  event_admission: "活动准入",
  appointment_credits: "预约次数",
  ai_credits: "AI 次数",
  membership_entitlement: "会员权益",
  automatic: "自动",
  manual: "手动",
  percentage: "百分比折扣",
  fixed_amount: "固定金额",
  once: "一次性",
  recurring: "周期计费",
  email: "邮件",
  sms: "短信",
  push: "应用推送",
  in_app: "站内通知",
  low: "低",
  medium: "中",
  high: "高",
  critical: "严重",
  info: "信息",
  system: "系统",
  administrator: "管理员",
  content_entry: "内容条目",
  content_media: "媒体内容",
  auth_login_succeeded: "用户登录成功",
  auth_login_failed: "用户登录失败",
  "auth.login.succeeded": "用户登录成功",
  "auth.login.failed": "用户登录失败",
  "auth.registration.created": "用户注册完成",
  "auth.email_verification.sent": "验证邮件已发送",
  "auth.email_verification.completed": "邮箱验证完成",
  "auth.email_verification.bypassed": "邮箱验证被绕过",
  "auth.account.locked": "账户已锁定",
  "auth.refresh_token.reuse_detected": "检测到刷新令牌重复使用",
  "auth.admin_access.removed": "管理员访问权限已移除",
  "auth.session.refreshed": "会话已刷新",
  "auth.session.revoked": "会话已撤销",
  "auth.session.family_revoked": "会话系列已撤销",
  "auth.password.reset.requested": "已申请重置密码",
  "auth.password.reset.completed": "密码重置完成",
  "auth.password.changed": "密码已修改",
  "user.account.suspended": "用户账户已停用",
  "user.account.restored": "用户账户已恢复",
  "user.account.updated": "用户资料已更新",
  "user.account.deactivation_requested": "用户账户已申请注销",
  "user.sessions.revoked": "用户全部会话已撤销",
  "rbac.role.assigned": "角色已分配",
  "rbac.role.revoked": "角色已撤销",
  "admin.invitation.created": "管理员邀请已创建",
  "admin.invitation.revoked": "管理员邀请已撤销",
  "admin.invitation.accepted": "管理员邀请已接受",
  "admin.account.disabled": "管理员账户已停用",
  "admin.account.restored": "管理员账户已恢复",
  "content.entry.created": "内容条目已创建",
  "content.entry.updated": "内容条目已更新",
  "content.entry.submit_review": "内容已提交审核",
  "content.entry.archived": "内容条目已归档",
  "content.entry.version_restored": "内容版本已恢复",
  "content.translation.updated": "内容翻译已更新",
  "content.media.updated": "媒体内容已更新",
  "content.media.deleted": "媒体内容已删除",
  "content.navigation.updated": "导航内容已更新",
  "content.site_setting.updated": "网站设置已更新",
  "content.site_setting.rolled_back": "网站设置已回滚",
  "counseling.schedule.created": "辅导排班已创建",
  "counseling.schedule.disabled": "辅导排班已停用",
  "counseling.appointment.time_reproposed": "辅导预约已重新提出时间",
  "counseling.followup.created": "辅导跟进已创建",
  "counseling.followup.status_changed": "辅导跟进状态已变更",
  "contact.submission.created": "联系记录已创建",
  "contact.submission.status_changed": "联系记录状态已变更",
  "contact.submission.assigned": "联系记录已分配",
  "contact.submission.resolved": "联系记录已处理",
  "Administration workflow: submit-review content after editorial review": "管理流程：编辑复核后提交内容审核",
  photo_not_clear: "照片不清晰",
  photo_not_personal: "非本人照片",
  photo_contains_contact_information: "照片包含联系方式",
  photo_contains_third_party_without_basis: "照片无依据包含第三方",
  photo_inappropriate_content: "照片内容不适宜",
  photo_suspected_impersonation: "疑似冒用身份",
  photo_duplicate: "重复照片",
  photo_quality_too_low: "照片质量过低",
  manual_review_required: "需要人工审核",
};

const dateFieldPattern = /(?:_at|_date|_time|_from|_until|At|Date|Time)$/;
const isoDatePattern = /^\d{4}-\d{2}-\d{2}(?:[T\s].*)?$/;

function translateTokens(value: string): string | undefined {
  const tokens = value.toLowerCase().split(/[._\s:-]+/).filter(Boolean);
  if (!tokens.length || !tokens.every((token) => token in tokenLabels)) return undefined;
  return tokens.map((token) => tokenLabels[token]).join("");
}

export function isAdminDateField(field: string): boolean {
  return dateFieldPattern.test(field);
}

export function formatAdminDate(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  const source = String(value);
  const normalized = /^\d{4}-\d{2}-\d{2}$/.test(source) ? `${source}T00:00:00+08:00` : source;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return source;
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: ADMIN_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")} ${part("hour")}:${part("minute")}:${part("second")}（${ADMIN_TIME_ZONE_LABEL}）`;
}

export function localizeAdminLabel(field: string, fallback?: string): string {
  if (fieldLabels[field]) return fieldLabels[field];
  if (isAdminDateField(field)) {
    const translated = translateTokens(field.replace(/(?:_at|At)$/, ""));
    return `${translated ?? fallback ?? field}时间（${ADMIN_TIME_ZONE_LABEL}）`;
  }
  if (fallback && /[\u3400-\u9fff]/u.test(fallback)) return fallback;
  const translated = translateTokens(field) ?? translateTokens(fallback ?? "");
  return translated ?? `字段（${fallback ?? field}）`;
}

export function localizeAdminValue(value: unknown, field = ""): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (value instanceof Date || isAdminDateField(field) || (typeof value === "string" && isoDatePattern.test(value))) {
    return formatAdminDate(value);
  }
  if (Array.isArray(value)) return value.length ? value.map((item) => localizeAdminValue(item)).join("、") : "—";
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    return entries.length
      ? entries.map(([key, item]) => `${localizeAdminLabel(key)}：${localizeAdminValue(item, key)}`).join("；")
      : "—";
  }
  const source = String(value);
  if (exactValues[source] !== undefined) return exactValues[source];
  if (/(?:status|state|type|kind|visibility|locale|channel|provider|source|severity|decision)$/i.test(field)) {
    return translateTokens(source) ?? source;
  }
  return source;
}

export function formatAdminTableCell(
  _row: Record<string, unknown>,
  column: { property?: string },
  value: unknown,
): string {
  return localizeAdminValue(value, column.property ?? "");
}

export function adminColumnMinWidth(field: string): number {
  if (field === "severity" || field.endsWith("_type")) return 120;
  if (field === "event_type") return 190;
  if (field === "reason" || field.includes("metadata") || field.endsWith("_state")) return 280;
  if (isAdminDateField(field)) return 220;
  if (field === "id" || field.endsWith("_id")) return 220;
  return 160;
}
