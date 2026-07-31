from fastapi import APIRouter

from vav.modules.health.router import router as health_router
from vav.modules.system.router import router as system_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(system_router, prefix="/system", tags=["system"])
