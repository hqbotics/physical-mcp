"""HTTP Vision API — expose camera data to any system.

Simple REST endpoints that serve live camera frames and scene summaries.
Runs alongside the MCP server, sharing the same state dict.

Endpoints:
    GET /           → API overview
    GET /frame      → Latest camera frame (JPEG)
    GET /frame/{id} → Frame from specific camera
    GET /scene      → All camera scene summaries (JSON)
    GET /scene/{id} → Scene for specific camera
    GET /changes    → Recent scene changes
"""

from __future__ import annotations

import logging
import time
from typing import Any

from aiohttp import web

logger = logging.getLogger("physical-mcp")


def create_vision_routes(state: dict[str, Any]) -> web.Application:
    """Create aiohttp app with vision API routes.

    Args:
        state: Shared state dict from the MCP server. Contains
            scene_states, frame_buffers, camera_configs, etc.
    """

    routes = web.RouteTableDef()

    @routes.get("/")
    async def index(request: web.Request) -> web.Response:
        """API overview with available cameras and endpoints."""
        cameras = list(state.get("scene_states", {}).keys())
        return web.json_response({
            "name": "physical-mcp",
            "description": "24/7 camera vision API",
            "cameras": cameras,
            "endpoints": {
                "GET /frame": "Latest camera frame (JPEG)",
                "GET /frame/{camera_id}": "Frame from specific camera",
                "GET /scene": "Current scene summaries (JSON)",
                "GET /scene/{camera_id}": "Scene for specific camera",
                "GET /changes": "Recent scene changes",
            },
        })

    @routes.get("/frame")
    @routes.get("/frame/{camera_id}")
    async def get_frame(request: web.Request) -> web.Response:
        """Return latest camera frame as JPEG image."""
        camera_id = request.match_info.get("camera_id", "")
        quality = int(request.query.get("quality", "80"))
        buffers = state.get("frame_buffers", {})

        if not buffers:
            return web.Response(status=503, text="No cameras active")

        # Get specific or first camera
        if camera_id and camera_id in buffers:
            buf = buffers[camera_id]
        elif not camera_id:
            buf = next(iter(buffers.values()))
        else:
            return web.Response(
                status=404, text=f"Camera '{camera_id}' not found"
            )

        frame = await buf.latest()
        if frame is None:
            return web.Response(status=503, text="No frame available yet")

        jpeg_bytes = frame.to_jpeg_bytes(quality=quality)
        return web.Response(
            body=jpeg_bytes,
            content_type="image/jpeg",
            headers={"Cache-Control": "no-cache"},
        )

    @routes.get("/scene")
    async def get_scene(request: web.Request) -> web.Response:
        """Return all camera scene summaries as JSON."""
        scenes = state.get("scene_states", {})
        result = {}
        for cid, scene in scenes.items():
            result[cid] = scene.to_dict()
            cam_cfg = state.get("camera_configs", {}).get(cid)
            if cam_cfg and cam_cfg.name:
                result[cid]["name"] = cam_cfg.name
        return web.json_response({
            "cameras": result,
            "timestamp": time.time(),
        })

    @routes.get("/scene/{camera_id}")
    async def get_scene_camera(request: web.Request) -> web.Response:
        """Return scene summary for a specific camera."""
        camera_id = request.match_info["camera_id"]
        scenes = state.get("scene_states", {})
        if camera_id not in scenes:
            return web.Response(
                status=404, text=f"Camera '{camera_id}' not found"
            )
        result = scenes[camera_id].to_dict()
        cam_cfg = state.get("camera_configs", {}).get(camera_id)
        if cam_cfg and cam_cfg.name:
            result["name"] = cam_cfg.name
        return web.json_response(result)

    @routes.get("/changes")
    async def get_changes(request: web.Request) -> web.Response:
        """Return recent scene changes across cameras."""
        minutes = int(request.query.get("minutes", "5"))
        camera_id = request.query.get("camera_id", "")
        scenes = state.get("scene_states", {})
        result = {}
        for cid, scene in scenes.items():
            if camera_id and cid != camera_id:
                continue
            result[cid] = scene.get_change_log(minutes)
        return web.json_response({"changes": result, "minutes": minutes})

    # ── CORS middleware (no extra deps) ────────────────────────

    @web.middleware
    async def cors_middleware(
        request: web.Request,
        handler: Any,
    ) -> web.Response:
        """Allow any origin — needed for browser extensions, web apps."""
        if request.method == "OPTIONS":
            resp = web.Response()
        else:
            resp = await handler(request)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        return resp

    app = web.Application(middlewares=[cors_middleware])
    app.add_routes(routes)
    return app
