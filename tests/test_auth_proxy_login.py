"""Login behaviour of auth_proxy.py in front of a dashboard that has its OWN login.

Run:  python -m unittest tests.test_auth_proxy_login -v      (needs aiohttp)

The fake upstream mimics the Hermes dashboard: it owns /login, /auth/password-login and
/api/auth/me, and 302s unauthenticated HTML loads to /login?next=%2F.
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from aiohttp import ClientSession, CookieJar, web
from aiohttp.test_utils import TestServer

PROXY_FILE = Path(__file__).resolve().parent.parent / "auth_proxy.py"
DASH_USER, DASH_PASS = "dash-user", "dash-pass"
PROXY_USER, PROXY_PASS = "proxy-user", "proxy-pass"


def load_proxy(extra_env):
    """Fresh copy of auth_proxy.py with the given environment (module state is read at import)."""
    env = {"DASHBOARD_USER": PROXY_USER, "DASHBOARD_PASSWORD": PROXY_PASS}
    env.update(extra_env)
    with mock.patch.dict(os.environ, env, clear=False):
        for key in ("HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "HERMES_PROXY_LOGIN"):
            if key not in extra_env:
                os.environ.pop(key, None)
        spec = importlib.util.spec_from_file_location("auth_proxy_under_test", PROXY_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    module.start_gateway = lambda: None  # never spawn `hermes gateway run` in tests
    return module


def fake_dashboard():
    def authed(request):
        return request.cookies.get("hermes_session_at") == "ok"

    async def me(request):
        return web.json_response({"user": DASH_USER}) if authed(request) else web.Response(status=401)

    async def login_page(request):
        return web.Response(text="DASHBOARD-LOGIN-PAGE", content_type="text/html")

    async def password_login(request):
        body = await request.json()
        if body.get("username") == DASH_USER and body.get("password") == DASH_PASS:
            resp = web.json_response({"ok": True})
            resp.set_cookie("hermes_session_at", "ok", httponly=True)
            resp.set_cookie("hermes_session_provider", "basic", httponly=True)
            return resp
        return web.Response(status=401)

    async def anything(request):
        if authed(request):
            return web.Response(text="DASHBOARD-HOME", content_type="text/html")
        if request.path.startswith("/api/"):
            return web.Response(status=401)
        raise web.HTTPFound("/login?next=%2F")

    app = web.Application()
    app.router.add_get("/api/auth/me", me)
    app.router.add_get("/login", login_page)
    app.router.add_post("/auth/password-login", password_login)
    app.router.add_route("*", "/{tail:.*}", anything)
    return app


class Harness:
    def __init__(self, env):
        self.env = env

    async def __aenter__(self):
        self.upstream = TestServer(fake_dashboard())
        await self.upstream.start_server()
        self.module = load_proxy(self.env)
        self.module.UPSTREAM = f"http://127.0.0.1:{self.upstream.port}"
        self.proxy = TestServer(self.module.create_app())
        await self.proxy.start_server()
        self.base = f"http://127.0.0.1:{self.proxy.port}"
        self.http = ClientSession(cookie_jar=CookieJar(unsafe=True))
        return self

    async def __aexit__(self, *exc):
        await self.http.close()
        await self.proxy.close()
        await self.upstream.close()

    async def browse(self, path, max_hops=8):
        """Follow redirects like a browser; returns (final_body, [paths visited])."""
        chain, url = [], self.base + path
        for _ in range(max_hops):
            async with self.http.get(url, allow_redirects=False) as resp:
                chain.append(url.replace(self.base, ""))
                if resp.status in (301, 302, 303, 307, 308):
                    url = self.base + resp.headers["Location"] if resp.headers["Location"].startswith("/") else resp.headers["Location"]
                    continue
                return await resp.text(), chain
        return "TOO-MANY-REDIRECTS", chain

    async def dashboard_login(self, user=DASH_USER, password=DASH_PASS):
        async with self.http.post(self.base + "/auth/password-login", json={"username": user, "password": password}) as resp:
            return resp.status


DASHBOARD_LOGIN_ENV = {"HERMES_DASHBOARD_BASIC_AUTH_USERNAME": DASH_USER}


class DashboardOwnsLogin(unittest.IsolatedAsyncioTestCase):
    """HERMES_DASHBOARD_BASIC_AUTH_USERNAME set: the dashboard's /login must be reachable."""

    async def test_unauthenticated_browser_reaches_the_dashboards_login_page(self):
        async with Harness(DASHBOARD_LOGIN_ENV) as h:
            body, chain = await h.browse("/")
            self.assertEqual(body, "DASHBOARD-LOGIN-PAGE", f"stuck on {chain}")

    async def test_after_dashboard_login_the_browser_gets_the_dashboard_not_a_loop(self):
        async with Harness(DASHBOARD_LOGIN_ENV) as h:
            self.assertEqual(await h.dashboard_login(), 200)
            body, chain = await h.browse("/")
            self.assertEqual(body, "DASHBOARD-HOME", f"loop: {chain}")

    async def test_proxy_cookie_login_no_longer_leads_to_a_loop(self):
        # The old flow: log in at the proxy, get the proxy cookie, then bounce off the dashboard.
        async with Harness(DASHBOARD_LOGIN_ENV) as h:
            body, chain = await h.browse("/")
            self.assertNotIn("Agent Console", body, f"proxy login form shadows the dashboard's: {chain}")

    async def test_wrong_dashboard_password_is_rejected(self):
        async with Harness(DASHBOARD_LOGIN_ENV) as h:
            self.assertEqual(await h.dashboard_login(password="nope"), 401)

    async def test_gateway_restart_needs_a_dashboard_session(self):
        async with Harness(DASHBOARD_LOGIN_ENV) as h:
            async with h.http.post(h.base + "/api/gateway/restart") as resp:
                self.assertEqual(resp.status, 401)
            await h.dashboard_login()
            async with h.http.post(h.base + "/api/gateway/restart") as resp:
                self.assertEqual(resp.status, 200)

    async def test_health_stays_public(self):
        async with Harness(DASHBOARD_LOGIN_ENV) as h:
            async with h.http.get(h.base + "/api/health") as resp:
                self.assertEqual(resp.status, 200)

    async def test_forwarded_api_without_session_is_still_refused_by_the_dashboard(self):
        async with Harness(DASHBOARD_LOGIN_ENV) as h:
            async with h.http.get(h.base + "/api/anything") as resp:
                self.assertEqual(resp.status, 401)


class LegacyProxyLoginUnchanged(unittest.IsolatedAsyncioTestCase):
    """No dashboard login configured: the proxy keeps its own cookie login exactly as before."""

    async def test_legacy_mode_still_shows_the_proxy_form(self):
        async with Harness({}) as h:
            body, chain = await h.browse("/")
            self.assertIn("Agent Console", body, chain)

    async def test_legacy_mode_proxy_login_then_dashboard(self):
        async with Harness({}) as h:
            async with h.http.post(h.base + "/login", data={"username": PROXY_USER, "password": PROXY_PASS}, allow_redirects=False) as resp:
                self.assertEqual(resp.status, 302)
            await h.dashboard_login()  # fake dashboard session, so the upstream does not bounce
            body, _ = await h.browse("/")
            self.assertEqual(body, "DASHBOARD-HOME")

    async def test_legacy_mode_wrong_password_is_rejected(self):
        async with Harness({}) as h:
            async with h.http.post(h.base + "/login", data={"username": PROXY_USER, "password": "x"}, allow_redirects=False) as resp:
                self.assertEqual(resp.status, 302)
                self.assertIn("error=1", resp.headers["Location"])

    async def test_explicit_proxy_login_mode_forces_the_old_behaviour(self):
        async with Harness({**DASHBOARD_LOGIN_ENV, "HERMES_PROXY_LOGIN": "proxy"}) as h:
            body, _ = await h.browse("/")
            self.assertIn("Agent Console", body)


if __name__ == "__main__":
    unittest.main()
