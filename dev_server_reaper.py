#!/usr/bin/env python3
"""Kill leaked Next.js dev/start servers left behind by agent sessions.

Agents run `next dev` / `next start` to preview work and often never stop them.
Each idle server holds ~65-215 MB, and Railway bills memory by the GB-hour
(2026-11-13: 12 leaked servers, ~450 MB, days old, cgroup 1.38 GB -> 0.93 GB once killed).

Rule: a process whose command line is a Next server (`next dev`, `next start`,
`next-server`) and that has been running longer than WMM_DEV_SERVER_MAX_AGE_HOURS
(default 4) is stopped together with its wrapper chain (npm exec / sh -c).
Uses /proc only, so it needs no procps. Set WMM_DEV_SERVER_REAPER=0 to disable.
"""
import os
import re
import signal
import sys
import time

NEXT_CMD_RE = re.compile(r"next(\s+|-)(dev|start|server)|next-server|dist/bin/next\s+(dev|start)")


def read_proc(pid, proc="/proc"):
    """Return (ppid, start_ticks, cmdline) for pid, or None if it vanished or is a zombie."""
    try:
        with open(f"{proc}/{pid}/stat") as f:
            stat = f.read()
        # comm may contain spaces/parens: split after the last ')'
        rest = stat[stat.rindex(")") + 2:].split()
        state, ppid, start = rest[0], int(rest[1]), int(rest[19])
        if state == "Z":
            return None
        with open(f"{proc}/{pid}/cmdline", "rb") as f:
            cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        return ppid, start, cmd
    except (OSError, ValueError, IndexError):
        return None


def snapshot(proc="/proc"):
    return {int(p): info for p in os.listdir(proc) if p.isdigit() and (info := read_proc(p, proc))}


def is_next(cmd):
    return bool(NEXT_CMD_RE.search(cmd))


def find_victims(procs, uptime_s, hz, max_age_s, self_pid):
    """PIDs to kill: old Next servers plus any wrapper ancestors that are also Next/npm/sh launchers."""
    old = {
        pid for pid, (_, start, cmd) in procs.items()
        if pid != self_pid and is_next(cmd) and uptime_s - start / hz > max_age_s
    }
    victims = set(old)
    for pid in old:
        parent = procs[pid][0]
        # climb through launcher wrappers (npm exec / sh -c ... next ...) but never past them
        while parent in procs and parent != self_pid and parent != 1:
            cmd = procs[parent][2]
            if is_next(cmd) or cmd.startswith(("npm exec", "sh -c")) and "next" in cmd:
                victims.add(parent)
                parent = procs[parent][0]
            else:
                break
    return victims


def main():
    if os.environ.get("WMM_DEV_SERVER_REAPER", "1").strip().lower() in ("0", "false", "no", "off"):
        return 0
    max_age_s = float(os.environ.get("WMM_DEV_SERVER_MAX_AGE_HOURS", "4")) * 3600
    hz = os.sysconf("SC_CLK_TCK")
    with open("/proc/uptime") as f:
        uptime_s = float(f.read().split()[0])
    victims = find_victims(snapshot(), uptime_s, hz, max_age_s, os.getpid())
    if not victims:
        return 0
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 0)):
        for pid in victims:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        if wait:
            time.sleep(wait)
    print(f"dev-server-reaper: stopped {len(victims)} leaked Next process(es): {sorted(victims)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
