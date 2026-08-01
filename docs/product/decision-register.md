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

## 决策记录格式

每次决策需记录：键、结论、负责人、批准人、依据、影响模块、生效日期、回退方式。更改 `project-manifest.yaml` 时必须同步更新本表和相关 ADR。
