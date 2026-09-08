from fastapi.testclient import TestClient

import app as application
from app import TUNNEL_ORIGIN_HOST, tunnel_route_allowed, tunnel_websocket_allowed


def test_tunnel_allows_only_overlay_read_routes():
    assert tunnel_route_allowed("GET", "/overlay")
    assert tunnel_route_allowed("HEAD", "/overlay")
    assert tunnel_route_allowed("GET", "/api/state")
    assert tunnel_route_allowed("GET", "/api/config")
    assert tunnel_route_allowed("GET", "/static/overlay.js")
    assert tunnel_route_allowed("GET", "/artwork/cover.jpg")
    assert tunnel_route_allowed("GET", "/font-assets/catalog.css")
    assert tunnel_route_allowed("GET", "/font-assets/abc.woff2")


def test_tunnel_blocks_configuration_and_writes():
    assert not tunnel_route_allowed("GET", "/config")
    assert not tunnel_route_allowed("GET", "/docs")
    assert not tunnel_route_allowed("PUT", "/api/config")
    assert not tunnel_route_allowed("POST", "/api/config/reset")


def test_tunnel_websocket_allowlist_only_exposes_the_read_only_feed():
    assert tunnel_websocket_allowed("/ws")
    assert not tunnel_websocket_allowed("/ws/control")
    assert not tunnel_websocket_allowed("/config")


def test_http_allowlist_is_not_applied_to_websockets():
    """``BaseHTTPMiddleware`` never sees a handshake, so the guard lives in the
    endpoint.  Without it any future WebSocket route would be public."""
    client = TestClient(application.app)
    with client.websocket_connect("/ws", headers={"Host": TUNNEL_ORIGIN_HOST}) as socket:
        assert socket.receive_json()["type"] == "state"
