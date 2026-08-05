from fastapi import APIRouter

from vav.modules.activities.router import router as activities_router
from vav.modules.ai_assistant.admin_router import router as ai_assistant_admin_router
from vav.modules.ai_assistant.router import router as ai_assistant_router
from vav.modules.catalog.router import router as catalog_router
from vav.modules.commerce.router import router as commerce_router
from vav.modules.content.router import router as content_router
from vav.modules.counseling.router import router as counseling_router
from vav.modules.courses.router import router as courses_router
from vav.modules.health.router import router as health_router
from vav.modules.identity.router import router as identity_router
from vav.modules.knowledge.router import router as knowledge_router
from vav.modules.matchmaking_interactions.admin_router import (
    router as matchmaking_interactions_admin_router,
)
from vav.modules.matchmaking_interactions.router import (
    router as matchmaking_interactions_router,
)
from vav.modules.matchmaking_profiles.admin_router import (
    router as matchmaking_profiles_admin_router,
)
from vav.modules.matchmaking_profiles.router import router as matchmaking_profiles_router
from vav.modules.memberships.admin_router import router as memberships_admin_router
from vav.modules.memberships.admin_router import version_router as membership_versions_admin_router
from vav.modules.memberships.router import router as memberships_router
from vav.modules.notifications.admin_router import router as notifications_admin_router
from vav.modules.notifications.router import router as notifications_router
from vav.modules.privacy.admin_router import router as privacy_admin_router
from vav.modules.privacy.router import router as privacy_router
from vav.modules.recommendations.admin_router import router as recommendations_admin_router
from vav.modules.recommendations.router import router as recommendations_router
from vav.modules.relationships.admin_router import router as relationships_admin_router
from vav.modules.relationships.router import router as relationships_router
from vav.modules.system.router import router as system_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(system_router, prefix="/system", tags=["system"])
api_router.include_router(identity_router, tags=["identity"])
api_router.include_router(content_router, tags=["content"])
api_router.include_router(catalog_router, tags=["catalog"])
api_router.include_router(commerce_router, tags=["commerce"])
api_router.include_router(activities_router, tags=["activities"])
api_router.include_router(ai_assistant_router, tags=["ai-assistant"])
api_router.include_router(ai_assistant_admin_router, tags=["ai-assistant-admin"])
api_router.include_router(courses_router, tags=["courses"])
api_router.include_router(counseling_router, tags=["counseling"])
api_router.include_router(knowledge_router, tags=["knowledge"])
api_router.include_router(notifications_router, tags=["notifications"])
api_router.include_router(notifications_admin_router, tags=["notifications-admin"])
api_router.include_router(privacy_router, tags=["privacy"])
api_router.include_router(privacy_admin_router, tags=["privacy-admin"])
api_router.include_router(matchmaking_profiles_router, tags=["matchmaking-profiles"])
api_router.include_router(matchmaking_profiles_admin_router, tags=["matchmaking-profiles-admin"])
api_router.include_router(recommendations_router, tags=["recommendations"])
api_router.include_router(recommendations_admin_router, tags=["recommendations-admin"])
api_router.include_router(matchmaking_interactions_router, tags=["matchmaking-interactions"])
api_router.include_router(
    matchmaking_interactions_admin_router, tags=["matchmaking-interactions-admin"]
)
api_router.include_router(relationships_router, tags=["relationships"])
api_router.include_router(relationships_admin_router, tags=["relationships-admin"])
api_router.include_router(memberships_router, tags=["memberships"])
api_router.include_router(memberships_admin_router, tags=["memberships-admin"])
api_router.include_router(membership_versions_admin_router, tags=["memberships-admin"])
