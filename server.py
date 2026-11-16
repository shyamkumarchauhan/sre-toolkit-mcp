"""SRE Toolkit MCP server.

A small, read-only Model Context Protocol server for on-call engineers. It gives an
AI assistant (Claude Code, Claude Desktop, VS Code, Cursor and others) a few safe
checks it can run during an incident, plus a runbook resource and an incident
summary prompt, so it shows all three MCP primitives.

Run it locally over stdio:
    python server.py
Or as a Streamable HTTP server:
    python server.py --http

Nothing here changes a system. Network checks only reach hosts listed in the
ALLOWED_HOSTS environment variable, so the model cannot be talked into probing
internal addresses it was never meant to see.
"""
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("sre-toolkit")

ALLOWED_HOSTS = {h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Report a redirect instead of following it, so a 30x cannot lead to a host outside the allowlist."""

    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _check_allowed(host: str) -> None:
    if host.lower() not in ALLOWED_HOSTS:
        # ToolError messages reach the model; any other exception is reported as a generic crash.
        raise ToolError(f"{host} is not in ALLOWED_HOSTS. Add it to the server's environment to allow checks.")


@mcp.tool()
def http_check(url: str, timeout_seconds: float = 5.0) -> dict:
    """Request a URL once and report the HTTP status code and latency in milliseconds."""
    host = urlparse(url).hostname or ""
    _check_allowed(host)
    start = time.perf_counter()
    try:
        with _opener.open(urllib.request.Request(url, method="GET"), timeout=timeout_seconds) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    except (urllib.error.URLError, TimeoutError) as error:
        return {"url": url, "ok": False, "error": str(getattr(error, "reason", error))}
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    return {"url": url, "ok": status < 500, "status": status, "latency_ms": latency_ms}


@mcp.tool()
def tls_expiry(host: str, port: int = 443) -> dict:
    """Return when the TLS certificate served by host:port expires, and how many days are left."""
    _check_allowed(host)
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                not_after = tls.getpeercert()["notAfter"]
    except OSError as error:
        raise ToolError(f"Could not read the certificate from {host}:{port}: {error}") from error
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), tz=timezone.utc)
    days_left = (expires - datetime.now(timezone.utc)).days
    return {"host": host, "expires_utc": expires.isoformat(), "days_left": days_left, "renew_soon": days_left < 21}


@mcp.tool()
def dns_lookup(name: str) -> dict:
    """Resolve a hostname to its IPv4 and IPv6 addresses."""
    _check_allowed(name)
    try:
        addresses = sorted({info[4][0] for info in socket.getaddrinfo(name, None)})
    except socket.gaierror as error:
        raise ToolError(f"{name} did not resolve: {error}") from error
    return {"name": name, "addresses": addresses}


@mcp.tool()
def error_budget(slo_target_percent: float, window_days: int, bad_minutes: float) -> dict:
    """Work out how much of an availability error budget is spent.

    slo_target_percent: for example 99.9
    window_days: the SLO window, for example 30
    bad_minutes: minutes of unavailability so far in the window
    """
    if not 0 < slo_target_percent < 100:
        raise ToolError("slo_target_percent must be between 0 and 100")
    budget_minutes = window_days * 24 * 60 * (1 - slo_target_percent / 100)
    spent = bad_minutes / budget_minutes * 100
    return {
        "budget_minutes": round(budget_minutes, 1),
        "spent_minutes": bad_minutes,
        "spent_percent": round(spent, 1),
        "remaining_minutes": round(max(budget_minutes - bad_minutes, 0), 1),
        "freeze_releases": spent >= 100,
    }


@mcp.tool()
def burn_rate(error_rate_percent: float, slo_target_percent: float) -> dict:
    """Compare the current error rate with the SLO and say how fast the budget is burning.

    A burn rate of 1 spends the budget exactly over the SLO window. The common
    multi-window alert pages at 14.4 (2% of a 30-day budget in one hour).
    """
    allowed = 100 - slo_target_percent
    rate = error_rate_percent / allowed
    return {"burn_rate": round(rate, 2), "page_now": rate >= 14.4, "ticket": 6 <= rate < 14.4}


@mcp.resource("runbook://{service}")
def runbook(service: str) -> str:
    """A first-response runbook template for a service."""
    return f"""# {service}: first response

1. Confirm impact: which users, which regions, since when (UTC).
2. Check the last change: deploys, config and feature flags in the past 2 hours.
3. Check the four golden signals: latency, traffic, errors, saturation.
4. Check dependencies: database, cache, queues, third-party APIs.
5. Mitigate first (roll back, fail over, scale), find the root cause later.
6. Post an update every 30 minutes, even if nothing changed.
"""


@mcp.prompt()
def incident_summary(service: str, timeline: str) -> str:
    """Draft a stakeholder update from an incident timeline."""
    return (
        f"You are the incident communications lead for {service}. Using only the timeline below, "
        "write a status update for non-technical stakeholders: current status, customer impact, "
        "what we know, next steps with an owner and the next update time. Do not guess a root cause. "
        f"Maximum 120 words.\n\nTimeline:\n{timeline}"
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http" if "--http" in sys.argv else "stdio")
