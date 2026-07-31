from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from vav.core.database import session_factory
from vav.models.content import (
    ContentEntry,
    NavigationItem,
    NavigationItemLocalization,
    NavigationMenu,
    SiteSetting,
)
from vav.models.identity import User
from vav.modules.content.domain import ContentEntryType, TranslationStatus
from vav.modules.content.schemas import LocalizationInput
from vav.modules.content.service import content_service
from vav.modules.identity.domain import UserStatus

SYSTEM_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
PAGE_SLOTS = (
    "home",
    "about",
    "services",
    "contact",
    "privacy",
    "terms",
    "refund-policy",
    "ai-disclaimer",
)
MENU_CODES = (
    "main_navigation",
    "user_account_navigation",
    "footer_services",
    "footer_company",
    "footer_legal",
)


async def ensure_system_user() -> None:
    async with session_factory() as session:
        if await session.get(User, SYSTEM_USER_ID) is None:
            session.add(
                User(
                    id=SYSTEM_USER_ID,
                    email="system@vav.invalid",
                    display_email="system@vav.invalid",
                    password_hash=None,
                    status=UserStatus.SUSPENDED,
                    email_verified_at=datetime.now(UTC),
                    preferred_locale="zh-CN",
                    timezone="UTC",
                )
            )
            await session.commit()


async def seed_pages() -> None:
    for slug in PAGE_SLOTS:
        async with session_factory() as session:
            existing = await session.scalar(
                select(ContentEntry).where(
                    ContentEntry.entry_type == ContentEntryType.PAGE,
                    ContentEntry.canonical_slug == slug,
                )
            )
            if existing is not None:
                continue
            await content_service.create(
                session,
                entry_type=ContentEntryType.PAGE,
                internal_name=f"System page: {slug}",
                canonical_slug=slug,
                default_locale="zh-CN",
                localization=LocalizationInput(
                    locale="zh-CN",
                    localized_slug=slug,
                    title=f"[待业务确认] {slug}",
                    excerpt="结构已建立；正式文案、法律审核和上线语言仍待负责人确认。",
                    content_blocks=[],
                    translation_status=TranslationStatus.DRAFT,
                ),
                change_summary="Create draft system page slot",
                actor_id=SYSTEM_USER_ID,
            )


async def seed_navigation_and_settings() -> None:
    async with session_factory() as session:
        for code in MENU_CODES:
            menu = await session.scalar(select(NavigationMenu).where(NavigationMenu.code == code))
            if menu is None:
                session.add(NavigationMenu(code=code, name=code.replace("_", " ").title()))
        values = {
            "site.name": ("VAV", "string", True),
            "site.default_locale": ("zh-CN", "string", True),
            "site.supported_locales": (["zh-CN", "zh-TW", "en"], "array", True),
            "site.contact_email": (None, "nullable_string", True),
            "site.registration_enabled": (True, "boolean", True),
            "site.maintenance_mode": (False, "boolean", True),
            "site.launch_language_decision": ("undecided", "decision_status", False),
        }
        for key, (value, value_type, is_public) in values.items():
            if await session.get(SiteSetting, key) is None:
                session.add(
                    SiteSetting(
                        setting_key=key,
                        value=value,
                        value_type=value_type,
                        is_public=is_public,
                        updated_by=SYSTEM_USER_ID,
                    )
                )
        await session.commit()

    async with session_factory() as session:
        menu = await session.scalar(
            select(NavigationMenu).where(NavigationMenu.code == "main_navigation")
        )
        if menu is not None:
            existing_item = await session.scalar(
                select(NavigationItem.id).where(NavigationItem.menu_id == menu.id)
            )
            if existing_item is None:
                for order, (route, labels) in enumerate(
                    (
                        ("home", ("首页", "首頁", "Home")),
                        ("about", ("关于 VAV", "關於 VAV", "About VAV")),
                        ("services", ("服务", "服務", "Services")),
                        ("contact", ("合作联系", "合作聯絡", "Contact")),
                    )
                ):
                    item = NavigationItem(
                        menu_id=menu.id,
                        internal_name=route,
                        link_type="route",
                        route_name=route,
                        sort_order=order,
                    )
                    session.add(item)
                    await session.flush()
                    for locale, label in zip(("zh-CN", "zh-TW", "en"), labels, strict=True):
                        session.add(
                            NavigationItemLocalization(
                                navigation_item_id=item.id,
                                locale=locale,
                                label=label,
                            )
                        )
                await session.commit()


async def seed_cms() -> None:
    await ensure_system_user()
    await seed_pages()
    await seed_navigation_and_settings()
    print("CMS seed complete: draft page slots, navigation and safe public settings")


if __name__ == "__main__":
    asyncio.run(seed_cms())
