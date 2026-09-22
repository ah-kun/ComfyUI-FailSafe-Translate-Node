"""HTTP API for syncing FailSafe Translate settings.

Routes:
    GET  /failsafe_translate/settings  -> current settings (secrets masked)
    POST /failsafe_translate/settings  -> update one or more settings (JSON object)
"""

import logging

from aiohttp import web
from server import PromptServer

from . import settings as _settings

logger = logging.getLogger("ComfyUI.FailsafeTranslate")


async def _get_settings(request: web.Request) -> web.Response:
    return web.json_response(_settings.mask(_settings.all()))


async def _post_settings(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response(
            {"ok": False, "error": "invalid json body"}, status=400
        )

    if not isinstance(data, dict):
        return web.json_response(
            {"ok": False, "error": "body must be an object"}, status=400
        )

    changed = _settings.update(data)
    cfg = _settings.all()
    _cache_update_limits(cfg)

    return web.json_response(
        {
            "ok": True,
            "changed": changed,
            "settings": _settings.mask(cfg),
        }
    )


def _cache_update_limits(cfg):
    from .providers import cache

    cache.update_limits(cfg["cache_enabled"], cfg["cache_max_entries"])


def register_routes() -> None:
    """Register the settings endpoints on the ComfyUI app."""
    routes = PromptServer.instance.routes
    # aiohttp RouteTableDef.get/post are decorator factories. Register the
    # handlers by applying the returned decorator; passing the handler as a
    # second positional argument does not register the route correctly.
    routes.get("/failsafe_translate/settings")(_get_settings)
    routes.post("/failsafe_translate/settings")(_post_settings)
    logger.debug("[FailSafeTranslate] settings routes registered")
