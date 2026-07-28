"""Every private API route must retain an explicit authentication dependency."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.routing import APIRoute

from src.auth import get_current_user, require_admin
from src.main import app

PUBLIC_ROUTES = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/health/ready"),
    ("POST", "/api/v1/auth/activate"),
    ("GET", "/api/v1/push/vapid-public-key"),
}


def _dependency_calls(route: APIRoute) -> set[Callable[..., Any]]:
    calls: set[Callable[..., Any]] = set()
    stack = list(route.dependant.dependencies)
    while stack:
        dependency = stack.pop()
        if dependency.call is not None:
            calls.add(dependency.call)
        stack.extend(dependency.dependencies)
    return calls


def _api_routes() -> list[APIRoute]:
    routes: list[APIRoute] = []
    for included in app.routes:
        router = getattr(included, "original_router", None)
        if router is None:
            continue
        routes.extend(route for route in router.routes if isinstance(route, APIRoute))
    return routes


def test_every_non_public_route_declares_current_or_admin_user() -> None:
    observed_public: set[tuple[str, str]] = set()
    unprotected: list[str] = []
    for route in _api_routes():
        dependencies = _dependency_calls(route)
        authenticated = get_current_user in dependencies or require_admin in dependencies
        for method in route.methods:
            key = (method, route.path)
            if key in PUBLIC_ROUTES:
                observed_public.add(key)
            elif not authenticated:
                unprotected.append(f"{method} {route.path}")

    assert observed_public == PUBLIC_ROUTES
    assert unprotected == []
