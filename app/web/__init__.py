from fastapi import APIRouter

from app.web.games import router as games_router
from app.web.settings import router as settings_router
from app.web.system import router as system_router
from app.web.tickets import router as tickets_router
from app.web.twitch import router as twitch_router
from app.web.wizard import router as wizard_router

api_router = APIRouter()
for _router in (
    system_router,
    wizard_router,
    settings_router,
    tickets_router,
    games_router,
    twitch_router,
):
    api_router.include_router(_router)

__all__ = ["api_router"]
