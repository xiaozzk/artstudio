"""Headless Blender driver for the protocol-13 end-to-end check.

Loads the user's normal preferences (so the enabled `addon` module is loaded),
starts the MCP socket server explicitly — background mode does not run the
auto-start timer — reports what it found, then idles so the caller can talk to
the server over localhost:9876.
"""
import sys
import time

import bpy

print("E2E_ADDON_MODULES:", sorted(
    m for m in bpy.context.preferences.addons.keys() if "mcp" in m.lower() or m == "addon"
))
print("E2E_BLENDER:", bpy.app.version_string)
print("E2E_OPERATOR_PRESENT:", hasattr(bpy.ops.blendermcp, "start_server"))
try:
    print("E2E_START_RESULT:", bpy.ops.blendermcp.start_server())
except Exception as exc:  # noqa: BLE001 - report, do not mask
    print("E2E_START_ERROR:", repr(exc))
scene = bpy.context.scene
print("E2E_SERVER_RUNNING:", getattr(scene, "blendermcp_server_running", None))
print("E2E_SERVER_PORT:", getattr(scene, "blendermcp_port", None))
print("E2E_SCENE_OBJECTS:", len(bpy.data.objects))
sys.stdout.flush()

for _ in range(240):  # stay alive ~4 minutes for the caller
    time.sleep(1)