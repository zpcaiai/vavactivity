"""Versioned dating-profile schema manifest and controlled taxonomies.

Business identifiers are the value codes. Display labels live in
``dating_taxonomy_localizations`` and must never drive business rules.
Values are retired with ``enabled: false`` so historical profiles remain
interpretable.
"""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from vav.modules.matchmaking_profiles.domain import FieldSensitivity

SCHEMA_CODE = "vav-dating-profile"
SCHEMA_SEMANTIC_VERSION = "1.0.0"
COMPLETENESS_POLICY_VERSION = "1.0.0"


def _values(*codes: tuple[str, str, str]) -> list[dict[str, Any]]:
    return [
        {"code": code, "enabled": True, "labels": {"zh-CN": zh, "en-US": en}}
        for code, zh, en in codes
    ]


TAXONOMIES: dict[str, list[dict[str, Any]]] = {
    "faith_status": _values(
        ("believer_baptized", "已受洗基督徒", "Baptized believer"),
        ("believer_not_baptized", "信主未受洗", "Believer, not yet baptized"),
        ("seeker", "慕道友", "Seeker"),
        ("returning", "回归教会", "Returning to church"),
        ("prefer_not_to_say", "不便透露", "Prefer not to say"),
    ),
    "church_tradition": _values(
        ("reformed", "改革宗", "Reformed"),
        ("baptist", "浸信会", "Baptist"),
        ("methodist", "卫理公会", "Methodist"),
        ("lutheran", "信义会", "Lutheran"),
        ("pentecostal_charismatic", "五旬节/灵恩", "Pentecostal or charismatic"),
        ("anglican", "圣公会", "Anglican"),
        ("non_denominational", "无宗派", "Non-denominational"),
        ("house_church", "家庭教会", "House church"),
        ("other_tradition", "其他传统", "Other tradition"),
    ),
    "church_participation": _values(
        ("weekly", "每周参加", "Weekly"),
        ("most_weeks", "多数周参加", "Most weeks"),
        ("monthly", "每月参加", "Monthly"),
        ("occasional", "偶尔参加", "Occasionally"),
        ("seeking_church", "正在寻找教会", "Seeking a church"),
        ("not_attending", "暂未参加", "Not attending"),
    ),
    "devotional_life": _values(
        ("daily", "每日灵修", "Daily"),
        ("several_times_week", "每周数次", "Several times a week"),
        ("weekly", "每周一次", "Weekly"),
        ("occasional", "偶尔", "Occasionally"),
        ("building_habit", "正在建立习惯", "Building the habit"),
    ),
    "small_group_participation": _values(
        ("regular_member", "固定小组成员", "Regular member"),
        ("occasional_member", "偶尔参加", "Occasional member"),
        ("leader", "小组带领", "Group leader"),
        ("not_participating", "暂未参加", "Not participating"),
    ),
    "ministry_participation": _values(
        ("worship", "敬拜事奉", "Worship"),
        ("children", "儿童事工", "Children"),
        ("youth", "青年事工", "Youth"),
        ("hospitality", "接待", "Hospitality"),
        ("teaching", "教导", "Teaching"),
        ("missions", "宣教", "Missions"),
        ("administration", "行政服事", "Administration"),
        ("none", "暂无", "None"),
    ),
    "future_church_expectation": _values(
        ("worship_together", "希望同去一间教会", "Worship together"),
        ("serve_together", "希望一同服事", "Serve together"),
        ("family_devotion", "希望有家庭灵修", "Family devotion"),
        ("respect_difference", "尊重不同传统", "Respect differing traditions"),
        ("undecided", "尚未决定", "Undecided"),
    ),
    "marital_status": _values(
        ("never_married", "未婚", "Never married"),
        ("divorced", "离异", "Divorced"),
        ("widowed", "丧偶", "Widowed"),
        ("annulled", "婚姻无效", "Annulled"),
        ("prefer_not_to_say", "不便透露", "Prefer not to say"),
    ),
    "children_status": _values(
        ("no_children", "没有子女", "No children"),
        ("children_living_with_me", "子女与我同住", "Children live with me"),
        ("children_living_elsewhere", "子女不与我同住", "Children live elsewhere"),
        ("shared_arrangement", "共同照顾安排", "Shared arrangement"),
        ("prefer_not_to_say", "不便透露", "Prefer not to say"),
    ),
    "children_count_range": _values(
        ("one", "1 位", "One"),
        ("two", "2 位", "Two"),
        ("three_or_more", "3 位及以上", "Three or more"),
        ("prefer_not_to_say", "不便透露", "Prefer not to say"),
    ),
    "open_to_partner_with_children": _values(
        ("open", "可以接受", "Open"),
        ("open_with_conversation", "愿意先沟通", "Open after conversation"),
        ("prefer_not", "希望不要", "Prefer not"),
        ("undecided", "尚未决定", "Undecided"),
    ),
    "relocation_willingness": _values(
        ("not_willing", "不考虑迁居", "Not willing to relocate"),
        ("same_country", "国内可迁居", "Within the same country"),
        ("same_region", "同一地区可迁居", "Within the same region"),
        ("international", "可跨国迁居", "Internationally"),
        ("open_to_discuss", "可以讨论", "Open to discuss"),
    ),
    "education_level": _values(
        ("secondary", "高中及以下", "Secondary"),
        ("vocational", "专科/职业教育", "Vocational"),
        ("bachelor", "本科", "Bachelor"),
        ("master", "硕士", "Master"),
        ("doctorate", "博士", "Doctorate"),
        ("prefer_not_to_say", "不便透露", "Prefer not to say"),
    ),
    "occupation_category": _values(
        ("education", "教育", "Education"),
        ("healthcare", "医疗健康", "Healthcare"),
        ("technology", "科技", "Technology"),
        ("business", "商业与金融", "Business and finance"),
        ("public_service", "公共服务", "Public service"),
        ("ministry", "全职服事", "Ministry"),
        ("creative", "创意与设计", "Creative"),
        ("trades", "技术工种", "Skilled trades"),
        ("student", "学生", "Student"),
        ("other_occupation", "其他", "Other"),
        ("prefer_not_to_say", "不便透露", "Prefer not to say"),
    ),
    "current_living_arrangement": _values(
        ("living_alone", "独居", "Living alone"),
        ("with_parents", "与父母同住", "Living with parents"),
        ("with_roommates", "与室友同住", "Living with roommates"),
        ("with_children", "与子女同住", "Living with children"),
        ("prefer_not_to_say", "不便透露", "Prefer not to say"),
    ),
    "family_closeness": _values(
        ("very_close", "非常亲密", "Very close"),
        ("close", "亲密", "Close"),
        ("moderate", "一般", "Moderate"),
        ("distant", "较为疏远", "Distant"),
        ("complex", "情况比较复杂", "Complex"),
    ),
    "family_culture": _values(
        ("christian_household", "基督化家庭", "Christian household"),
        ("mixed_faith", "信仰背景不同", "Mixed faith backgrounds"),
        ("traditional", "传统家庭", "Traditional"),
        ("open_communication", "开放沟通", "Open communication"),
        ("intergenerational", "多代同堂", "Intergenerational"),
    ),
    "parental_care_expectation": _values(
        ("financial_support", "经济支持", "Financial support"),
        ("live_nearby", "希望住得近", "Live nearby"),
        ("live_together", "愿意同住", "Live together"),
        ("shared_with_siblings", "与兄弟姐妹分担", "Shared with siblings"),
        ("to_be_discussed", "留待讨论", "To be discussed"),
    ),
    "desire_children": _values(
        ("want_children", "希望生育", "Want children"),
        ("open_to_children", "可以考虑", "Open to children"),
        ("prefer_no_more", "不再生育", "Prefer no more children"),
        ("undecided", "尚未决定", "Undecided"),
        ("prefer_not_to_say", "不便透露", "Prefer not to say"),
    ),
    "parenting_expectation": _values(
        ("faith_formation", "信仰培育", "Faith formation"),
        ("shared_parenting", "共同育儿", "Shared parenting"),
        ("education_focus", "重视教育", "Education focus"),
        ("gentle_discipline", "温和管教", "Gentle discipline"),
        ("extended_family_support", "家族协助", "Extended-family support"),
    ),
    "preferred_future_household": _values(
        ("nuclear", "小家庭", "Nuclear household"),
        ("intergenerational", "多代同住", "Intergenerational"),
        ("near_family", "住在家人附近", "Near family"),
        ("flexible", "灵活安排", "Flexible"),
    ),
    "daily_schedule": _values(
        ("early_riser", "早睡早起", "Early riser"),
        ("standard", "作息规律", "Standard"),
        ("night_owl", "夜型作息", "Night owl"),
        ("shift_work", "轮班", "Shift work"),
    ),
    "diet": _values(
        ("no_restriction", "无特殊要求", "No restriction"),
        ("vegetarian", "素食", "Vegetarian"),
        ("vegan", "纯素", "Vegan"),
        ("halal_style", "清真饮食习惯", "Halal-style"),
        ("health_focused", "注重健康饮食", "Health focused"),
        ("allergy_aware", "有过敏需注意", "Allergy aware"),
    ),
    "exercise_frequency": _values(
        ("daily", "每天", "Daily"),
        ("several_times_week", "每周数次", "Several times a week"),
        ("weekly", "每周一次", "Weekly"),
        ("occasional", "偶尔", "Occasionally"),
        ("rarely", "很少", "Rarely"),
    ),
    "smoking_status": _values(
        ("never", "从不吸烟", "Never"),
        ("former", "已戒烟", "Former smoker"),
        ("occasional", "偶尔", "Occasionally"),
        ("regular", "经常", "Regularly"),
        ("prefer_not_to_say", "不便透露", "Prefer not to say"),
    ),
    "alcohol_use": _values(
        ("never", "不饮酒", "Never"),
        ("social", "社交场合", "Social"),
        ("occasional", "偶尔", "Occasionally"),
        ("regular", "经常", "Regularly"),
        ("prefer_not_to_say", "不便透露", "Prefer not to say"),
    ),
    "social_style": _values(
        ("small_gatherings", "小型聚会", "Small gatherings"),
        ("large_gatherings", "大型聚会", "Large gatherings"),
        ("one_on_one", "一对一相处", "One on one"),
        ("quiet_time", "享受独处", "Quiet time"),
        ("community_service", "社区服务", "Community service"),
    ),
    "leisure_interest": _values(
        ("reading", "阅读", "Reading"),
        ("music", "音乐", "Music"),
        ("outdoors", "户外活动", "Outdoors"),
        ("sports", "运动", "Sports"),
        ("cooking", "烹饪", "Cooking"),
        ("travel", "旅行", "Travel"),
        ("arts", "艺术", "Arts"),
        ("volunteering", "志愿服务", "Volunteering"),
        ("study", "学习进修", "Study"),
    ),
    "pet_preference": _values(
        ("has_pets", "已有宠物", "Has pets"),
        ("likes_pets", "喜欢宠物", "Likes pets"),
        ("no_pets", "不养宠物", "No pets"),
        ("allergic", "宠物过敏", "Allergic"),
    ),
    "travel_frequency": _values(
        ("frequent", "经常旅行", "Frequent"),
        ("occasional", "偶尔旅行", "Occasional"),
        ("rare", "很少旅行", "Rare"),
    ),
    "financial_attitude": _values(
        ("saver", "重视储蓄", "Saver"),
        ("planner", "计划性强", "Planner"),
        ("generous_giving", "乐意奉献", "Generous giving"),
        ("simple_living", "简朴生活", "Simple living"),
        ("shared_budget", "希望共同预算", "Shared budgeting"),
    ),
    "conflict_style": _values(
        ("talk_immediately", "及时沟通", "Talk immediately"),
        ("need_time_first", "需要冷静时间", "Need time first"),
        ("seek_counsel", "寻求辅导", "Seek counsel"),
        ("pray_together", "一起祷告", "Pray together"),
        ("written_reflection", "书面沟通", "Written reflection"),
    ),
    "communication_preference": _values(
        ("in_person", "面对面", "In person"),
        ("voice_call", "语音通话", "Voice call"),
        ("video_call", "视频通话", "Video call"),
        ("written", "文字沟通", "Written"),
    ),
    "relationship_value": _values(
        ("faith_first", "以信仰为根基", "Faith first"),
        ("honesty", "诚实透明", "Honesty"),
        ("commitment", "委身", "Commitment"),
        ("service", "彼此服事", "Service"),
        ("growth", "共同成长", "Growth"),
        ("family_centred", "以家庭为中心", "Family centred"),
    ),
    "gender": _values(
        ("male", "男", "Male"),
        ("female", "女", "Female"),
    ),
    "residence_status": _values(
        ("citizen", "公民", "Citizen"),
        ("permanent_resident", "永久居民", "Permanent resident"),
        ("work_visa", "工作签证", "Work visa"),
        ("student_visa", "学生签证", "Student visa"),
        ("other_status", "其他", "Other"),
        ("prefer_not_to_say", "不便透露", "Prefer not to say"),
    ),
    "age_display_mode": _values(
        ("exact_age", "显示实际年龄", "Exact age"),
        ("age_range", "只显示年龄段", "Age range"),
        ("hidden", "不显示年龄", "Hidden"),
    ),
}


def _field(
    code: str,
    section: str,
    field_type: str,
    *,
    taxonomy: str | None = None,
    required_for_submission: bool = False,
    required_for_recommendation: bool = False,
    sensitivity: FieldSensitivity = FieldSensitivity.RESTRICTED,
    default_visibility: str = "private",
    searchable: bool = False,
    recommendation_eligible: bool = False,
    weight: int = 0,
    value_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = dict(value_schema or {})
    if taxonomy:
        schema["taxonomy"] = taxonomy
    return {
        "field_code": code,
        "section_code": section,
        "field_type": field_type,
        "value_schema": schema,
        "required_for_submission": required_for_submission,
        "required_for_recommendation": required_for_recommendation,
        "sensitivity": sensitivity.value,
        "default_visibility": default_visibility,
        "searchable": searchable,
        "recommendation_eligible": recommendation_eligible,
        "weight": weight,
    }


CP = FieldSensitivity.CONTROLLED_PUBLIC
CF = FieldSensitivity.CONFIDENTIAL
RS = FieldSensitivity.RESTRICTED

FIELD_MANIFEST: list[dict[str, Any]] = [
    # basic ----------------------------------------------------------------
    _field(
        "basic.gender_code",
        "basic",
        "enum",
        taxonomy="gender",
        required_for_submission=True,
        required_for_recommendation=True,
        sensitivity=CP,
        default_visibility="verified_members",
        searchable=True,
        recommendation_eligible=True,
        weight=600,
    ),
    _field(
        "basic.eligible_partner_gender_codes",
        "basic",
        "enum_set",
        taxonomy="gender",
        required_for_submission=True,
        required_for_recommendation=True,
        sensitivity=CF,
        searchable=True,
        recommendation_eligible=True,
        weight=500,
    ),
    _field(
        "basic.age_display_mode",
        "basic",
        "enum",
        taxonomy="age_display_mode",
        required_for_submission=True,
        sensitivity=CP,
        default_visibility="verified_members",
        weight=200,
    ),
    _field(
        "basic.relationship_intent",
        "basic",
        "enum",
        required_for_submission=True,
        required_for_recommendation=True,
        sensitivity=CP,
        default_visibility="verified_members",
        searchable=True,
        recommendation_eligible=True,
        value_schema={
            "values": ["marriage_oriented", "serious_relationship", "getting_to_know", "undecided"]
        },
        weight=600,
    ),
    _field("basic.height_cm", "basic", "integer", sensitivity=CF, weight=100),
    # location -------------------------------------------------------------
    _field(
        "location.country_code",
        "location",
        "string",
        required_for_submission=True,
        required_for_recommendation=True,
        sensitivity=CF,
        default_visibility="verified_members",
        searchable=True,
        recommendation_eligible=True,
        weight=400,
    ),
    _field(
        "location.region_code",
        "location",
        "string",
        sensitivity=CF,
        searchable=True,
        recommendation_eligible=True,
        weight=200,
    ),
    _field(
        "location.city_code",
        "location",
        "string",
        required_for_submission=True,
        sensitivity=CF,
        default_visibility="verified_members",
        searchable=True,
        recommendation_eligible=True,
        weight=300,
    ),
    _field(
        "location.relocation_willingness",
        "location",
        "enum",
        taxonomy="relocation_willingness",
        sensitivity=CF,
        recommendation_eligible=True,
        weight=200,
    ),
    _field(
        "location.residence_status_code",
        "location",
        "enum",
        taxonomy="residence_status",
        weight=100,
    ),
    _field("location.citizenship_codes", "location", "string_set", weight=100),
    _field(
        "location.primary_language_codes",
        "location",
        "string_set",
        required_for_submission=True,
        sensitivity=CF,
        recommendation_eligible=True,
        weight=300,
    ),
    _field("location.additional_language_codes", "location", "string_set", weight=100),
    # faith ----------------------------------------------------------------
    _field(
        "faith.faith_status_code",
        "faith",
        "enum",
        taxonomy="faith_status",
        required_for_submission=True,
        required_for_recommendation=True,
        sensitivity=RS,
        recommendation_eligible=True,
        weight=700,
    ),
    _field("faith.faith_started_year", "faith", "integer", sensitivity=RS, weight=150),
    _field(
        "faith.church_tradition_codes",
        "faith",
        "enum_set",
        taxonomy="church_tradition",
        sensitivity=RS,
        recommendation_eligible=True,
        weight=300,
    ),
    _field(
        "faith.current_church_participation_code",
        "faith",
        "enum",
        taxonomy="church_participation",
        required_for_submission=True,
        sensitivity=RS,
        recommendation_eligible=True,
        weight=350,
    ),
    _field(
        "faith.devotional_life_code",
        "faith",
        "enum",
        taxonomy="devotional_life",
        sensitivity=RS,
        weight=150,
    ),
    _field(
        "faith.small_group_participation_code",
        "faith",
        "enum",
        taxonomy="small_group_participation",
        sensitivity=RS,
        weight=100,
    ),
    _field(
        "faith.ministry_participation_codes",
        "faith",
        "enum_set",
        taxonomy="ministry_participation",
        sensitivity=RS,
        weight=100,
    ),
    _field(
        "faith.marriage_faith_importance",
        "faith",
        "scale",
        sensitivity=RS,
        recommendation_eligible=True,
        value_schema={"minimum": 1, "maximum": 5, "not_a_spiritual_score": True},
        weight=300,
    ),
    _field(
        "faith.future_church_expectation_codes",
        "faith",
        "enum_set",
        taxonomy="future_church_expectation",
        sensitivity=RS,
        weight=150,
    ),
    _field("faith.faith_journey_summary", "faith", "encrypted_text", sensitivity=RS, weight=150),
    # relationship history --------------------------------------------------
    _field(
        "relationship_history.marital_status_code",
        "relationship_history",
        "enum",
        taxonomy="marital_status",
        required_for_submission=True,
        required_for_recommendation=True,
        sensitivity=RS,
        recommendation_eligible=True,
        weight=600,
    ),
    _field(
        "relationship_history.prior_marriage_count",
        "relationship_history",
        "integer",
        sensitivity=RS,
        weight=100,
    ),
    _field(
        "relationship_history.relationship_history_disclosure_level",
        "relationship_history",
        "enum",
        sensitivity=RS,
        value_schema={
            "values": ["after_mutual_match", "after_introduction", "on_request", "not_disclosed"]
        },
        weight=100,
    ),
    _field(
        "relationship_history.has_children",
        "relationship_history",
        "boolean",
        required_for_submission=True,
        sensitivity=RS,
        recommendation_eligible=True,
        weight=400,
    ),
    _field(
        "relationship_history.children_count_range",
        "relationship_history",
        "enum",
        taxonomy="children_count_range",
        sensitivity=RS,
        weight=100,
    ),
    _field(
        "relationship_history.children_living_arrangement_code",
        "relationship_history",
        "enum",
        taxonomy="children_status",
        sensitivity=RS,
        recommendation_eligible=True,
        weight=200,
    ),
    _field(
        "relationship_history.open_to_partner_with_children",
        "relationship_history",
        "enum",
        taxonomy="open_to_partner_with_children",
        sensitivity=RS,
        recommendation_eligible=True,
        weight=200,
    ),
    _field(
        "relationship_history.history_summary",
        "relationship_history",
        "encrypted_text",
        sensitivity=RS,
        weight=100,
    ),
    # family ----------------------------------------------------------------
    _field(
        "family.current_living_arrangement_code",
        "family",
        "enum",
        taxonomy="current_living_arrangement",
        sensitivity=RS,
        weight=150,
    ),
    _field(
        "family.family_closeness_code",
        "family",
        "enum",
        taxonomy="family_closeness",
        sensitivity=RS,
        weight=150,
    ),
    _field(
        "family.family_culture_codes",
        "family",
        "enum_set",
        taxonomy="family_culture",
        sensitivity=RS,
        weight=150,
    ),
    _field(
        "family.parental_care_expectation_codes",
        "family",
        "enum_set",
        taxonomy="parental_care_expectation",
        sensitivity=RS,
        weight=150,
    ),
    _field(
        "family.desire_children_code",
        "family",
        "enum",
        taxonomy="desire_children",
        required_for_submission=True,
        required_for_recommendation=True,
        sensitivity=RS,
        recommendation_eligible=True,
        weight=400,
    ),
    _field(
        "family.parenting_expectation_codes",
        "family",
        "enum_set",
        taxonomy="parenting_expectation",
        sensitivity=RS,
        weight=150,
    ),
    _field(
        "family.preferred_future_household_codes",
        "family",
        "enum_set",
        taxonomy="preferred_future_household",
        sensitivity=RS,
        weight=150,
    ),
    _field("family.family_summary", "family", "encrypted_text", sensitivity=RS, weight=100),
    # lifestyle --------------------------------------------------------------
    _field(
        "lifestyle.daily_schedule_code",
        "lifestyle",
        "enum",
        taxonomy="daily_schedule",
        sensitivity=CF,
        recommendation_eligible=True,
        weight=150,
    ),
    _field(
        "lifestyle.diet_codes", "lifestyle", "enum_set", taxonomy="diet", sensitivity=CF, weight=100
    ),
    _field(
        "lifestyle.exercise_frequency_code",
        "lifestyle",
        "enum",
        taxonomy="exercise_frequency",
        sensitivity=CF,
        weight=100,
    ),
    _field(
        "lifestyle.smoking_status_code",
        "lifestyle",
        "enum",
        taxonomy="smoking_status",
        required_for_submission=True,
        sensitivity=CF,
        recommendation_eligible=True,
        weight=250,
    ),
    _field(
        "lifestyle.alcohol_use_code",
        "lifestyle",
        "enum",
        taxonomy="alcohol_use",
        required_for_submission=True,
        sensitivity=CF,
        recommendation_eligible=True,
        weight=250,
    ),
    _field(
        "lifestyle.social_style_codes",
        "lifestyle",
        "enum_set",
        taxonomy="social_style",
        sensitivity=CF,
        weight=100,
    ),
    _field(
        "lifestyle.leisure_interest_codes",
        "lifestyle",
        "enum_set",
        taxonomy="leisure_interest",
        sensitivity=CF,
        recommendation_eligible=True,
        weight=200,
    ),
    _field(
        "lifestyle.pet_preference_codes",
        "lifestyle",
        "enum_set",
        taxonomy="pet_preference",
        sensitivity=CF,
        weight=100,
    ),
    _field(
        "lifestyle.travel_frequency_code",
        "lifestyle",
        "enum",
        taxonomy="travel_frequency",
        sensitivity=CF,
        weight=100,
    ),
    _field(
        "lifestyle.financial_attitude_codes",
        "lifestyle",
        "enum_set",
        taxonomy="financial_attitude",
        sensitivity=CF,
        weight=100,
        value_schema={"no_bank_or_asset_records": True},
    ),
    _field(
        "lifestyle.conflict_style_codes",
        "lifestyle",
        "enum_set",
        taxonomy="conflict_style",
        sensitivity=CF,
        weight=150,
    ),
    _field(
        "lifestyle.communication_preference_codes",
        "lifestyle",
        "enum_set",
        taxonomy="communication_preference",
        sensitivity=CF,
        weight=150,
    ),
    # education and work -----------------------------------------------------
    _field(
        "education_and_work.education_level_code",
        "education_and_work",
        "enum",
        taxonomy="education_level",
        sensitivity=CF,
        recommendation_eligible=True,
        weight=250,
    ),
    _field(
        "education_and_work.occupation_category_code",
        "education_and_work",
        "enum",
        taxonomy="occupation_category",
        sensitivity=CF,
        recommendation_eligible=True,
        weight=250,
    ),
    # narratives -------------------------------------------------------------
    _field(
        "self_introduction.self_introduction",
        "self_introduction",
        "long_text",
        required_for_submission=True,
        sensitivity=CP,
        default_visibility="verified_members",
        weight=700,
    ),
    _field(
        "self_introduction.faith_journey",
        "self_introduction",
        "long_text",
        sensitivity=RS,
        weight=200,
    ),
    _field(
        "relationship_values.relationship_values",
        "relationship_values",
        "long_text",
        sensitivity=CP,
        weight=200,
    ),
    _field(
        "future_vision.marriage_vision", "future_vision", "long_text", sensitivity=CP, weight=200
    ),
    _field("future_vision.family_vision", "future_vision", "long_text", sensitivity=CP, weight=150),
    _field(
        "self_introduction.strengths_and_growth",
        "self_introduction",
        "long_text",
        sensitivity=CP,
        weight=150,
    ),
    _field(
        "interests.interests_and_lifestyle", "interests", "long_text", sensitivity=CP, weight=150
    ),
    _field(
        "communication.hoped_for_relationship",
        "communication",
        "long_text",
        sensitivity=CP,
        weight=150,
    ),
    # photos and privacy -----------------------------------------------------
    _field(
        "photos.primary_photo",
        "photos",
        "photo",
        required_for_submission=True,
        required_for_recommendation=True,
        sensitivity=RS,
        weight=700,
    ),
    _field(
        "privacy.privacy_settings_confirmed",
        "privacy",
        "boolean",
        required_for_submission=True,
        sensitivity=CP,
        weight=400,
    ),
    _field(
        "privacy.partner_preferences_confirmed",
        "privacy",
        "boolean",
        required_for_submission=True,
        sensitivity=RS,
        weight=300,
    ),
]

SECTION_WEIGHTS: dict[str, int] = {}
for _definition in FIELD_MANIFEST:
    SECTION_WEIGHTS[_definition["section_code"]] = (
        SECTION_WEIGHTS.get(_definition["section_code"], 0) + _definition["weight"]
    )

COMPLETENESS_POLICY: dict[str, Any] = {
    "policy_version": COMPLETENESS_POLICY_VERSION,
    "measures": "form_completion_only",
    # Filling every required field lands exactly on the submission floor;
    # optional detail is what lifts a profile toward recommendation eligibility.
    "required_share_basis_points": 8000,
    "not_a_measure_of": [
        "personal_worth",
        "marriage_value",
        "spiritual_maturity",
        "match_probability",
    ],
    "section_weights": SECTION_WEIGHTS,
    "total_weight": sum(SECTION_WEIGHTS.values()),
}

SUBMISSION_POLICY: dict[str, Any] = {
    "requires_review": True,
    "requires_primary_photo": True,
    "requires_privacy_confirmation": True,
    "adult_only": True,
    "immutable_submitted_version": True,
}

#: Criteria that business, privacy and legal review approved for automated
#: filtering. Anything outside this set is rejected at the API boundary.
APPROVED_PREFERENCE_CRITERIA: dict[str, dict[str, Any]] = {
    "age_range": {"operators": ["range"], "projection_field": "age_years"},
    "country_code": {"operators": ["equals", "in"], "projection_field": "country_code"},
    "region_code": {"operators": ["equals", "in"], "projection_field": "region_code"},
    "city_code": {"operators": ["equals", "in"], "projection_field": "city_code"},
    "relocation_willingness": {"operators": ["in"], "projection_field": "relocation_willingness"},
    "language_codes": {
        "operators": ["contains_any", "contains_all"],
        "projection_field": "language_codes",
    },
    "faith_status_code": {"operators": ["equals", "in"], "projection_field": "faith_codes"},
    "church_tradition_codes": {"operators": ["contains_any"], "projection_field": "faith_codes"},
    "marriage_faith_importance": {
        "operators": ["at_least", "at_most", "range"],
        "projection_field": "faith_codes",
    },
    "marital_status_code": {
        "operators": ["equals", "in"],
        "projection_field": "marital_status_code",
    },
    "has_children": {"operators": ["boolean"], "projection_field": "children_status_code"},
    "open_to_partner_with_children": {
        "operators": ["in"],
        "projection_field": "children_status_code",
    },
    "desire_children_code": {"operators": ["equals", "in"], "projection_field": "lifestyle_codes"},
    "education_level_code": {
        "operators": ["in", "at_least"],
        "projection_field": "lifestyle_codes",
    },
    "daily_schedule_code": {"operators": ["in"], "projection_field": "lifestyle_codes"},
    "smoking_status_code": {"operators": ["in"], "projection_field": "lifestyle_codes"},
    "alcohol_use_code": {"operators": ["in"], "projection_field": "lifestyle_codes"},
    "leisure_interest_codes": {
        "operators": ["contains_any"],
        "projection_field": "lifestyle_codes",
    },
    "communication_preference_codes": {
        "operators": ["contains_any"],
        "projection_field": "lifestyle_codes",
    },
    "relationship_intent": {
        "operators": ["equals", "in"],
        "projection_field": "relationship_intent",
    },
}


def taxonomy_value_codes(taxonomy_code: str, *, include_disabled: bool = False) -> set[str]:
    values = TAXONOMIES.get(taxonomy_code, [])
    return {value["code"] for value in values if include_disabled or value.get("enabled", True)}


def field_definition(field_code: str) -> dict[str, Any] | None:
    for definition in FIELD_MANIFEST:
        if definition["field_code"] == field_code:
            return definition
    return None
