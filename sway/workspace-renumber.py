#!/usr/bin/env python3
"""
Keeps workspace numbers contiguous (1, 2, 3, ...) as workspaces come and
go, instead of leaving gaps where closed ones used to be. Sway never does
this on its own - workspace "numbers" are just name strings it creates on
request and destroys when they go empty, with no renumbering involved -
so closing the windows on workspace 3 while 1, 3, 5 exist leaves 1 and 5
on the bar, not 1 and 2.

Algorithm: on every workspace/window IPC event, list the currently
existing workspaces, sort by their current numeric name, and rename the
i-th one (1-indexed) to "i" if it isn't already. This ordering is
collision-safe by construction: sorting n distinct positive-integer names
ascending guarantees the i-th one is >= i (i-1 strictly smaller distinct
values precede it), so its target i is always <= its current name -
meaning by the time a rename claims target "i", nothing still holds that
name (anything that could have is either already processed, or belongs to
a later, strictly-larger-named workspace that hasn't been claimed down to
i yet). No temporary renames or collision juggling needed.

Named workspaces (anything that doesn't parse as a plain integer, e.g. if
a workspace were ever manually named "3:web") are left untouched and
don't occupy a numeric slot.
"""
import asyncio
import json

DEBOUNCE_S = 0.25


async def get_workspaces():
    proc = await asyncio.create_subprocess_exec(
        "swaymsg", "-t", "get_workspaces",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        return json.loads(out.decode())
    except json.JSONDecodeError:
        return []


async def rename(old, new):
    proc = await asyncio.create_subprocess_exec(
        "swaymsg", f'rename workspace "{old}" to "{new}"',
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


async def renumber():
    workspaces = await get_workspaces()

    numbered = []
    for ws in workspaces:
        name = ws["name"]
        try:
            numbered.append((int(name), name))
        except ValueError:
            continue  # non-numeric name (e.g. hand-renamed) - leave alone
    numbered.sort(key=lambda p: p[0])

    for i, (_current_num, old_name) in enumerate(numbered, start=1):
        new_name = str(i)
        if old_name != new_name:
            await rename(old_name, new_name)


async def watch():
    await renumber()  # catch up on whatever state exists at startup

    proc = await asyncio.create_subprocess_exec(
        "swaymsg", "-t", "subscribe", "-m", '["workspace", "window"]',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )

    pending = None

    async def debounced_renumber():
        nonlocal pending
        await asyncio.sleep(DEBOUNCE_S)
        pending = None
        await renumber()

    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        # Any workspace or window event can change which workspaces exist
        # (a window close can empty and thus destroy one) - just
        # re-derive full state each time rather than parsing the specific
        # event, and debounce so a burst of closes (e.g. closing several
        # windows at once) triggers one renumber pass, not several.
        if pending is not None:
            pending.cancel()
        pending = asyncio.ensure_future(debounced_renumber())


async def main():
    await watch()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
