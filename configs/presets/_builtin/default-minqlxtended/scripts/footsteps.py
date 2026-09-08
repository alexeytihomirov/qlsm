"""
footsteps.py - minqlxtended plugin to restore audible footsteps at high client FPS

How it works:
  PM_Footsteps advances an 8-bit walk cycle by bobmove * msec and emits
  EV_FOOTSTEP when bit 7 of (cycle + 64) flips.  bobmove is 0.4 running and
  msec is an integer, so at 500 FPS every command contributes (int)(0.4 * 2)
  == 0, the cycle stops, and other players never hear the mover walk.

  footsteps_hook.so replaces one 26-byte site in qagamex64.so with a jump to a
  trampoline that keeps the fraction the cast throws away.  Cadence then
  matches the true 3.125 steps/s at every framerate.

  The game module is reloaded on every map change, which discards the patch,
  so the plugin re-applies it on the map event, deferred one frame.  Patching
  runs only on the game thread — never from a background thread, which would
  mean rewriting instructions another thread might be executing.

Cvars:
  qlx_footstepsSo - absolute path to footsteps_hook.so (default: next to this file)

Commands:
  !footsteps  - Report whether the patch is installed (perm 1)
"""

import minqlxtended
import ctypes
import os


# Mirrors the FS_* constants in footsteps_hook.c.
STATUS_TEXT = {
    1: "^2patched and active^7",
    0: "^3not patched^7 - qagamex64.so is not mapped yet",
    -1: "^1refused^7 - arithmetic selftest failed",
    -2: "^1not patched^7 - byte pattern not found in this qagame build",
    -3: "^1refused^7 - byte pattern matched more than once",
    -4: "^1not patched^7 - could not make the code page writable",
}


class footsteps(minqlxtended.Plugin):
    def __init__(self):
        super().__init__()

        self.set_cvar_once("qlx_footstepsSo", "")
        self.lib = None

        lib_path = (self.get_cvar("qlx_footstepsSo") or "").strip()
        if not lib_path:
            lib_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "footsteps_hook.so")
        self.lib_path = lib_path

        # Registered before the load attempt, deliberately. If the .so is
        # missing or refuses to load, !footsteps has to still answer and say so:
        # it is the operator's only in-game signal, and a status command that
        # disappears exactly when there is something to report is worse than
        # none. Registering after the try/except would also make the
        # `if self.lib is None` guards below unreachable dead code.
        self.add_hook("map", self.handle_map)
        self.add_command("footsteps", self.cmd_footsteps, 1)

        try:
            self.lib = ctypes.CDLL(lib_path)
        except OSError as e:
            self.msg("^1[footsteps]^7 Failed to load {}: {}".format(lib_path, e))
            return

        self._setup_ctypes()

        status = self.lib.footsteps_patch()
        if status == 1:
            self.msg("^2[footsteps]^7 Remainder hook installed.")
        elif status == 0:
            # Expected when the plugin loads before the first map is up. The
            # map hook installs it as soon as qagame is there.
            minqlxtended.console_print(
                "[footsteps] qagame not mapped yet; will patch on map load\n")
        else:
            self.msg("^1[footsteps]^7 Hook not installed ({}).".format(
                self._status_text(status)))

    def _setup_ctypes(self):
        self.lib.footsteps_patch.argtypes = []
        self.lib.footsteps_patch.restype = ctypes.c_int

        self.lib.footsteps_status.argtypes = []
        self.lib.footsteps_status.restype = ctypes.c_int

        self.lib.footsteps_hits.argtypes = []
        self.lib.footsteps_hits.restype = ctypes.c_uint64

        self.lib.footsteps_edges.argtypes = []
        self.lib.footsteps_edges.restype = ctypes.c_uint64

    def _status_text(self, status):
        return STATUS_TEXT.get(status, "^1unknown status {}^7".format(status))

    def handle_map(self, mapname, factory):
        """Re-apply the patch: the game module is reloaded on every map."""
        if self.lib is None:
            return
        self._repatch()

    @minqlxtended.next_frame
    def _repatch(self):
        """Deferred a frame so the re-patch cannot race the module reload.

        Nothing documents whether the map event is dispatched before or after
        qagamex64.so is remapped.  If it fires first, the scan finds nothing,
        footsteps stay silent for the whole map, and !footsteps reports it with
        no correction path until the next map.  Running on the next frame
        removes the question instead of assuming an answer.  No extra retry hook
        is needed: map fires every map and footsteps_patch() is idempotent.
        """
        status = self.lib.footsteps_patch()
        if status != 1:
            minqlxtended.console_print(
                "[footsteps] patch not installed after map load: {}\n".format(
                    self._status_text(status)))

    def cmd_footsteps(self, player, msg, channel):
        if self.lib is None:
            player.tell("^1[footsteps]^7 Native hook is not loaded.")
            return minqlxtended.Return.STOP_ALL

        status = self.lib.footsteps_status()
        player.tell("^7[footsteps] {}".format(self._status_text(status)))
        player.tell("^7[footsteps] {} bob updates, {} step edges - {}".format(
            self.lib.footsteps_hits(), self.lib.footsteps_edges(), self.lib_path))
        return minqlxtended.Return.STOP_ALL
