"""List every addon Blender finds on disk whose bl_info names MCP for Blender.

Answers "do I need to reinstall / which entry is the live one": nothing here
starts the socket server, so headless is fine (protocol 13 refuses -b anyway).
"""
import addon_utils

for mod in addon_utils.modules():
    info = getattr(mod, "bl_info", {}) or {}
    label = f"{info.get('name', '?')}"
    if "mcp" not in label.lower() and "mcp" not in mod.__name__.lower():
        continue
    enabled = addon_utils.check(mod.__name__)[1]
    print(f"E2E_ENTRY module={mod.__name__!r} name={label!r} "
          f"version={info.get('version')} file={mod.__file__} enabled={enabled}")