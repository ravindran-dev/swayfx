#!/usr/bin/env python3
"""
Waybar "now playing" module for modules-left, right after sway/workspaces.

Combines two independent streams into one continuously-updated waybar
custom-module JSON line (the standard way these animate - each stdout line
replaces the module's displayed text):

  - playerctl --follow: MPRIS track metadata + play/pause status, works
    uniformly across browsers, Spotify, mpv, VLC, anything MPRIS-compliant,
    with no per-player integration needed.
  - cava: a live audio waveform of whatever's actually coming out of the
    speakers, rendered as 8 compact Unicode block characters (▁▂▃▄▅▆▇█).

cava is deliberately NOT run continuously in the background - it's started
only while a player is actually in the Playing state and killed the moment
it isn't (paused, stopped, or no player at all), so this doesn't cost an
idle audio-capture stream sitting open all the time on a laptop this
session has already gone to some effort to keep power-efficient.
"""
import asyncio
import json
import shutil
import sys

CAVA_CONFIG = "/home/ravi/.config/waybar/media-visualizer-cava.conf"
BARS = "▁▂▃▄▅▆▇█"
MAX_LABEL = 20
FIELD_SEP = "\x1f"  # ASCII unit separator - won't collide with real track text
# Resting-state glyph shown when no MPRIS player exists at all (app closed/
# quit, not just paused) - level 1 rather than the flattest level 0 so it
# still reads as a wave shape at rest, not a blank dash. No title text
# alongside it: there's no track to name.
STATIC_WAVE = BARS[1] * 8

state = {"status": None, "title": None, "artist": None}
cava_proc = None
cava_task = None


def render(wave=""):
    status = state["status"]
    title = state["title"] or "Unknown"
    artist = state["artist"]

    if status != "Playing":
        # Just the resting line - no title/artist - for BOTH no player at
        # all AND a player that exists but isn't actively playing. Details
        # only earn their space once something is actually audible; a
        # paused track sitting there with its full title was taking up the
        # same width as playing but conveying less, squeezing the fixed
        # inter-module gap everywhere else on the bar.
        tooltip = "Nothing playing" if not status else (
            title + (f"\nby {artist}" if artist else "") + f"\n{status}")
        cls = "idle" if not status else "paused"
        print(json.dumps({"text": STATIC_WAVE, "class": cls, "tooltip": tooltip}),
              flush=True)
        return

    label = f"{title} — {artist}" if artist else title
    if len(label) > MAX_LABEL:
        label = label[:MAX_LABEL - 1] + "…"

    text = f"{wave}  {label}" if wave else label
    cls = "playing"
    tooltip = title + (f"\nby {artist}" if artist else "") + f"\n{status}"
    print(json.dumps({"text": text, "class": cls, "tooltip": tooltip}), flush=True)


async def stop_cava():
    global cava_proc, cava_task
    if cava_task is not None:
        cava_task.cancel()
        cava_task = None
    if cava_proc is not None:
        proc, cava_proc = cava_proc, None
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=1)
        except asyncio.TimeoutError:
            proc.kill()


async def run_cava():
    global cava_proc
    cava_proc = await asyncio.create_subprocess_exec(
        "cava", "-p", CAVA_CONFIG,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    while True:
        line = await cava_proc.stdout.readline()
        if not line:
            break
        try:
            levels = [int(v) for v in line.decode().strip().split(";") if v.strip()]
        except ValueError:
            continue
        wave = "".join(BARS[max(0, min(v, 7))] for v in levels)
        render(wave)


async def sync_cava_to_status():
    global cava_task
    should_run = state["status"] == "Playing" and shutil.which("cava") is not None
    running = cava_task is not None and not cava_task.done()
    if should_run and not running:
        cava_task = asyncio.create_task(run_cava())
    elif not should_run and running:
        await stop_cava()
        render()


async def handle_playerctl_line(line):
    parts = line.split(FIELD_SEP)
    if len(parts) != 3:
        return
    status, title, artist = parts
    state["status"] = status or None
    state["title"] = title or None
    state["artist"] = artist or None
    await sync_cava_to_status()
    # Always render immediately, even when entering Playing: cava's own
    # loop will follow up with wave-bearing renders once its first frame
    # arrives (usually within one frame period), but the title/artist
    # shouldn't sit blank until then - confirmed live that skipping this
    # for the Playing case left the module rendering nothing at all
    # whenever cava's first frame was delayed or cava wasn't installed.
    render()


async def prime_initial_state(fmt):
    """--follow only emits on the NEXT change - without this, a player
    already playing before this script starts stays invisible until
    something about it changes (track, pause/play, ...)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "playerctl", "--format", fmt, "metadata",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        line = out.decode().strip()
        if line:
            await handle_playerctl_line(line)
    except FileNotFoundError:
        print(json.dumps({"text": STATIC_WAVE, "class": "idle",
                           "tooltip": "playerctl not installed"}), flush=True)
        sys.exit(1)


async def watch_playerctl():
    fmt = FIELD_SEP.join(["{{status}}", "{{title}}", "{{artist}}"])
    await prime_initial_state(fmt)

    while True:
        proc = await asyncio.create_subprocess_exec(
            "playerctl", "--follow", "--format", fmt, "metadata",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            await handle_playerctl_line(line.decode().strip())

        # Only reached if --follow's own process actually exits (e.g. it
        # crashes) - restart it. NOT reached when a player just closes:
        # confirmed live that --follow's stdout stays open indefinitely in
        # that case (cava kept running for minutes after the only active
        # player quit, well past this branch), so idle detection for that
        # case can't live here - see watch_no_players() below instead.
        await asyncio.sleep(1.5)


async def watch_no_players():
    """Safety net for the gap above: playerctl -l is cheap and doesn't lie
    about whether anything is currently registered, so poll it lightly and
    force an idle transition (stopping cava) the moment it's empty, rather
    than trusting --follow to ever signal that on its own."""
    while True:
        await asyncio.sleep(2)
        if state["status"] is None:
            continue
        proc = await asyncio.create_subprocess_exec(
            "playerctl", "-l",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        if not out.decode().strip():
            state.update(status=None, title=None, artist=None)
            await sync_cava_to_status()
            render()


async def main():
    render()
    await asyncio.gather(watch_playerctl(), watch_no_players())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
