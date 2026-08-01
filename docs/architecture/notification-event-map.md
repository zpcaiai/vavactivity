# 通知事件映射

| 领域 | 事件 | 收件人解析 | 分类 | 默认渠道 | 模板 |
| --- | --- | --- | --- | --- | --- |
| Identity | `auth.registration.created` | `event_user` | account | email | verify-email |
| Identity | `auth.password.changed` | `event_user` | security | in_app + email | password-changed |
| Identity | `auth.refresh_token.reuse_detected` | `event_user` | security/urgent | in_app + email | suspicious-session |
| Commerce | `order.created` | `order_owner` | order | in_app + email | order-created |
| Commerce | `payment.succeeded` | `order_owner` | payment | in_app + email | payment-succeeded |
| Commerce | `payment.failed` | `order_owner` | payment | in_app + email | payment-failed |
| Activity | `activity.registration.confirmed` | `activity_registration_user` | activity | in_app + email | registration-confirmed |
| Activity | `activity.waitlist.promotion_offered` | `activity_waitlist_user` | activity/high | in_app + email | waitlist-promotion |
| Activity | `activity.cancelled` | `activity_registration_user` | activity/high | in_app + email | activity-cancelled |
| Course | `course.enrollment.activated` | `course_enrollment_user` | course | in_app + email | enrollment-activated |
| Course | `course.content.released` | `course_enrollment_user` | course | in_app | content-released |
| Counseling | `counseling.appointment.confirmed` | `counseling_appointment_user` | counseling | in_app + email | appointment-confirmed |
| Counseling | `counseling.appointment.cancelled` | `counseling_appointment_user` | counseling/high | in_app + email | appointment-cancelled |
| AI | `ai.referral.created` | `ai_referral_user` | ai_assistant/high | in_app | referral-created |

事件适配层只读取当前业务所有权。Payload 经加密保存，只能提供模板 Schema 声明的变量；
未知事件或版本进入 Dead Letter。单向活动选择不会映射为对方通知。
