"""wmm-idea-capture: one tool, capture_idea, that saves Fran's idea to Creator Studio.

Why a plugin tool and not a skill: a skill costs a skill_view round-trip before the model
can act, and a curl from the terminal tool depends on the terminal passing the secret
through (it scrubs a blocklist of env names). A plugin tool runs inside the gateway process,
so it is one tool call per idea and reads CONTENT_CAPTURE_SECRET straight from the Railway
env. The model's reply after the tool result is the confirmation; no extra model call.

Contract (wmm-content web/app/api/capture/telegram/route.ts):
  POST {"text": ...}, Authorization: Bearer <secret>
  200 {"ok": true, "note": {...}}     saved to ct_notes
  200 {"ok": true, "skipped": true}   NOT saved (empty, or under 3 characters)
  401 / 400 / 500 {"error": ...}      NOT saved
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_URL = "https://wmm-content.vercel.app/api/capture/telegram"
TIMEOUT_SECONDS = 20

SCHEMA = {
    "name": "capture_idea",
    "description": (
        "Save one of Fran's ideas to the Creator Studio inbox. Call it when Fran marks a "
        "message as an idea: it starts with 'idea', 'idea:', '/idea' or '💡', or he says "
        "'guarda esto como idea' / 'save this as an idea' (also for a voice note or a note "
        "shared from Google Keep / iPhone Notes). Pass the idea text verbatim (the transcript "
        "for a voice note) without the marker word; do not rewrite or summarize it. One call "
        "per idea. Then confirm in one short line in Fran's language (Spanish: tú, never "
        "voseo). If the result says saved=false, tell him it was NOT saved and quote the status."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The idea, verbatim."},
        },
        "required": ["text"],
    },
}


def _owner_only_refusal() -> str | None:
    """Ideas land in Fran's own inbox, so a paired teammate's chat must not write there."""
    try:
        from gateway.session_context import get_session_env, session_is_messaging_surface
    except Exception:
        return None  # not running under the gateway (CLI, tests): nothing to check
    if not session_is_messaging_surface():
        return None
    owner = os.environ.get("HERMES_OWNER_TELEGRAM_ID", "8635020128").strip()
    user = str(get_session_env("HERMES_SESSION_USER_ID", "") or "").strip()
    if owner and user != owner:
        return "Idea capture saves to Fran's Creator Studio inbox and is only available to Fran."
    return None


def _result(saved: bool, **fields) -> str:
    return json.dumps({"saved": saved, **fields}, ensure_ascii=False)


def capture_idea(params, **_kwargs) -> str:
    text = str((params or {}).get("text") or "").strip()
    if not text:
        return _result(False, error="No idea text was given.")
    refusal = _owner_only_refusal()
    if refusal:
        return _result(False, error=refusal)

    secret = os.environ.get("CONTENT_CAPTURE_SECRET", "").strip()
    url = os.environ.get("CONTENT_CAPTURE_URL", "").strip() or DEFAULT_URL
    if not secret:
        return _result(False, error="CONTENT_CAPTURE_SECRET is not set on the hermes service.")

    request = urllib.request.Request(
        url,
        data=json.dumps({"text": text}).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {secret}",
            "User-Agent": "wmm-gdog-idea-capture/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status, raw = response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        status, raw = err.code, err.read().decode("utf-8", "replace")
    except Exception as err:  # DNS, TLS, timeout: the idea did not reach the inbox
        return _result(False, status=None, error=f"{type(err).__name__}: {err}"[:300])

    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = {}
    if 200 <= status < 300 and body.get("ok") and body.get("note"):
        note = body["note"] if isinstance(body["note"], dict) else {}
        return _result(True, status=status, note_id=note.get("id"))
    if 200 <= status < 300 and body.get("skipped"):
        return _result(False, status=status, error="Creator Studio skipped it (text too short).")
    error = body.get("error") if isinstance(body, dict) else None
    return _result(False, status=status, error=str(error or raw or "no response body")[:300])


def register(ctx):
    ctx.register_tool(
        name="capture_idea",
        toolset="wmm_idea_capture",
        schema=SCHEMA,
        handler=capture_idea,
        emoji="💡",
    )
