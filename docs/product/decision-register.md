# 待决策登记

下列事项在 `project-manifest.yaml` 中均保持 `undecided`，负责人完成业务、法务或运营确认后，才可记录决策、依据和生效日期。

| 决策键 | 负责人 | 当前状态 | 对实现的约束 |
| --- | --- | --- | --- |
| `payment_legal_entity` | business | undecided | 禁止启用生产收款 |
| `launch_regions` | business | undecided | 不假定税务、币种和地区规则 |
| `launch_languages` | product | undecided | 仅提供简中、繁中、英文能力，不声明首发顺序 |
| `membership_plans` | product | undecided | 不创建生产套餐或价格 |
| `contact_exchange_policy` | trust_and_safety | undecided | 不开放联系方式交换 |
| `video_hosting` | platform | undecided | 不绑定生产视频供应商 |
| `counseling_scheduling_mode` | operations | undecided | 不固化自动或人工确认 |
| `ai_knowledge_authorization` | legal | undecided | 不导入未经确认的知识资料 |
| `pilot_user_group` | product | undecided | 不预设试点人群 |
| `catalog_tax_policy` | finance_and_legal | undecided | 报价税额保持 `null`，不推断含税或未税 |
| `regional_price_books` | product_and_finance | undecided | 仅提供可配置价格簿，不创建生产地区价格 |
| `payment_provider_credentials` | finance_and_platform | undecided | Stripe/PayPal 真实适配器保持禁用；本地 Fake 不得进入生产 |
| `refund_policy` | finance_and_legal | undecided | 默认所有退款都需要独立审批，不自动退款 |
| `subscription_cancellation_policy` | product_and_legal | undecided | 默认仅周期结束取消，立即取消保持禁用 |
| `commerce_terms_versions` | legal | undecided | 不声明正式退款、自动续费或消费者条款已经获批 |
| `activity_eligibility_policy` | product_and_legal | undecided | 规则辅助只能给出建议，不按不透明规则自动拒绝 |
| `activity_participant_visibility` | trust_and_safety | undecided | 仅展示用户明确授权的活动资料 |
| `activity_cancellation_refund_policy` | operations_and_finance | undecided | 取消活动只生成退款或人工处理任务，不在活动事务内同步退款 |
| `activity_contact_exchange_policy` | trust_and_safety | undecided | 互选成功仍不公开联系方式，等待双方确认政策 |
| `activity_no_show_choice_policy` | product_and_trust | undecided | 默认未签到用户不得进入活动后互选 |
| `course_video_hosting` | product_and_platform | undecided | 仅启用可替换 Provider；开发环境使用短时签名 Fake |
| `course_video_download_policy` | product_and_legal | undecided | 视频默认禁止下载，资料按资源级策略 |
| `course_certificate_name_visibility` | product_and_privacy | undecided | 公共验证默认遮盖学员姓名 |
| `course_access_expiry_policy` | product_and_legal | undecided | 到期后禁止新访问，不删除学习与证书历史 |
| `course_membership_access_policy` | product | undecided | 不在课程代码中硬编码任何会员等级访问 |
| `counseling_cancellation_policy` | operations_and_finance | undecided | 默认取消只建立人工处理任务，不自动退款或消费次数 |
| `counseling_no_show_policy` | operations_and_legal | undecided | 默认未到不自动消费次数，需有因人工审核 |
| `counseling_recording_policy` | legal_and_privacy | undecided | 录音、录像与转录默认关闭，未经独立同意不得启用 |
| `counseling_record_retention` | privacy_and_legal | undecided | 记录保持分层加密，不预设生产保留期限 |
| `counseling_professional_scope` | legal_and_service_owner | undecided | 不宣称心理治疗、医疗诊断、危机干预或法律意见 |
| `knowledge_embedding_provider` | platform_and_ai | undecided | 开发/测试只用确定性 Fake，生产必须显式配置真实 Provider |
| `knowledge_query_retention` | privacy_and_legal | undecided | 查询文本保持加密且不声明生产保留期限已批准 |
| `knowledge_public_citation_policy` | legal_and_content | undecided | 未获独立引用许可时只返回内部引用，不公开原文摘录 |
| `ai_memory_policy` | privacy_and_product | undecided | 长期记忆默认关闭，只有单独明确同意后才可跨 Turn 使用；不默认跨会话共享 |
| `ai_conversation_retention` | privacy_and_legal | undecided | 本地使用可配置 365 天占位值，生产不得宣称保留期限已获批准或自动永久保存 |
| `ai_safety_escalation_policy` | trust_and_safety_and_legal | undecided | 高风险停止普通建议并建内部复核；地区紧急指导和外发流程未批准时不得虚构 |
| `ai_model_provider` | platform_and_ai | undecided | 开发/评测使用确定性 Provider；生产必须配置兼容、获批且满足数据地区要求的 Provider |
| `ai_human_referral_policy` | operations_and_legal | undecided | 普通转介需用户确认；高风险仅建受限内部任务，不自动向外部机构发送资料 |
| `notification_email_provider` | platform_and_operations | undecided | 开发只使用 Mailpit/Fake，生产必须显式选择并验证真实 Provider |
| `notification_marketing_consent` | legal_and_product | undecided | 营销默认关闭，不从注册或购买推断同意，正式文案和版本待批准 |
| `notification_retention` | privacy_and_legal | undecided | 本地使用可配置占位期限，生产清理和审计保留期限未获批准 |
| `notification_tracking_policy` | privacy_and_product | undecided | 敏感事务邮件不嵌入营销追踪，点击/打开追踪默认关闭 |
| `notification_campaign_approval` | operations_and_legal | undecided | 所有营销群发保持审批分离；正式人数阈值与升级流程待批准 |
| `privacy_retention_policy` | privacy_and_legal | undecided | 本地仅使用有限期占位策略；生产期限和法域依据未获批准时不得自动永久保留或删除 |
| `privacy_erasure_policy` | privacy_and_legal | undecided | 删除请求生成模块计划并 fail closed；财务、安全和辅导数据的最终处置需法务确认 |
| `privacy_legal_hold_policy` | legal_and_security | undecided | Hold 必须最小范围、授权、到期或复核；不得以无期限 Hold 规避数据权利 |
| `privacy_break_glass_policy` | security_and_privacy | undecided | 紧急访问保持双人审批、短时、最小范围和逐次审计；生产响应流程待批准 |
| `privacy_export_format_policy` | privacy_and_product | undecided | 本地提供加密 JSON/HTML 能力；正式 PDF、附件披露和法域格式待批准 |
| `ai_external_training_policy` | privacy_legal_and_ai | undecided | 外部模型训练默认关闭，不从 AI 使用或长期记忆同意推断授权 |
| `dating_gender_policy` | product_and_legal | undecided | 性别与可认识对象取值来自版本化字典，不在代码中固化任何永久社会政策 |
| `dating_relationship_intent_eligibility` | product | undecided | 是否只允许婚姻导向用户进入推荐池未定，代码保持关系目标为可配置字段 |
| `dating_faith_taxonomy_scope` | product_and_ministry | undecided | 信仰状态与宗派字典可停用但不删除；信仰重要性不得被解释为属灵评分 |
| `dating_profile_default_visibility` | trust_and_safety | undecided | 新档案一律 Strict，字段默认可见性只能收紧不能放宽 |
| `dating_photo_moderation_provider` | platform_and_trust | undecided | 自动检测仅作审核辅助；人脸识别与跨站搜索默认禁用且不得自动判定冒用 |
| `dating_profile_review_staffing` | operations | undecided | 审核员默认无敏感字段、原图与暂停权限；双人复核门槛待运营确认 |

## 决策记录格式

每次决策需记录：键、结论、负责人、批准人、依据、影响模块、生效日期、回退方式。更改 `project-manifest.yaml` 时必须同步更新本表和相关 ADR。

## Batch 14 — recommendation engine

| Decision | Owner | Status | Interim behaviour |
| --- | --- | --- | --- |
| `recommendation_default_feature_weights` | product_and_matchmaking | undecided | The transparent baseline in `features.py` is used and versioned in the active strategy. |
| `recommendation_minimum_score_thresholds` | product_and_matchmaking | undecided | Directional 4000 bps, bidirectional 5000 bps as an engineering default, not a compatibility claim. |
| `recommendation_daily_exposure_limits` | operations_and_product | undecided | 10 per batch, 20 received per day, 50 shown per profile per day. |
| `recommendation_repeat_exposure_cooldown` | product | undecided | 30 days. |
| `recommendation_exploration_policy` | product_and_matchmaking | undecided | 2 exploration slots, +1 in a sparse region, all still fully qualified. |
| `recommendation_cold_start_minimum_exposure` | product | undecided | 5 qualified exposures for a new approved profile. |
| `recommendation_fairness_thresholds` | trust_and_product | undecided | Measured and reported; no automatic rebalancing that would violate a member's stated conditions. |
| `recommendation_experiments_in_production` | product_and_legal | undecided | Disabled; approval required before any treatment can start. |
| `recommendation_ai_explanation_rewrite` | product_and_legal | undecided | Disabled; deterministic templates only. |

## Batch 15 — matchmaking interactions

| Decision | Owner | Status | Interim behaviour |
| --- | --- | --- | --- |
| `matchmaking_direct_profile_like` | product_and_trust | undecided | Disabled. A like requires a valid recommendation item or an approved activity source; liking an arbitrary profile is not reachable. |
| `matchmaking_contact_exchange_policy` | product_privacy_and_legal | undecided | `mutual_confirmation_required`. Automatic exchange after acceptance is implemented but switched off and needs explicit approval. |
| `matchmaking_invitation_expiry_policy` | product | undecided | 7-day TTL; expiry returns the match to `active` and starts a 30-day cooldown. |
| `matchmaking_repeat_invitation_policy` | product | undecided | Resend only after expiry plus cooldown. A decline never permits an automatic resend. |
| `matchmaking_declined_pair_cooldown` | product_and_matchmaking | undecided | 180 days before the pair returns to the recommendation pool. |
| `matchmaking_contact_grant_ttl` | privacy_and_product | undecided | No automatic date expiry; grants end on withdrawal, block, restriction, contact change or relationship end. |
| `matchmaking_skip_cooldowns` | product_and_matchmaking | undecided | `not_now` 30 days, `not_interested` 180 days. Neither becomes a block or a hidden hard preference. |
