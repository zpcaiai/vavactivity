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

## 决策记录格式

每次决策需记录：键、结论、负责人、批准人、依据、影响模块、生效日期、回退方式。更改 `project-manifest.yaml` 时必须同步更新本表和相关 ADR。

