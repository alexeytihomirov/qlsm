# demo_native_autorecord.py - arms/disarms minqlxtended's own native
# per-player demo capture (see ql-server-core/docs/superpowers/specs/
# 2026-08-17-native-multi-pov-demo-capture-design.md) directly via
# minqlxtended.demo_arm()/demo_disarm() - no HTTP, no separate process, no
# eBPF (that pipeline is addons/server-demo/, untouched by this addon; both
# can coexist until the operator decides to cut over).
#
# game_countdown arms recording (mirrors demo_hook_autorecord.py's own
# match_id/map convention: UTC "%Y%m%dT%H%M%SZ", self.game.map). game_end
# disarms - it does NOT build the .qlmatch, because the C side's two-stage
# cut + snapshot index run asynchronously on a finalize thread AFTER
# game_end (see Task 6a/6b). The actual manifest/zip build happens on
# demo_match_finalized(match_id), fired once every file for that match has
# reached final form (cut/copy-through + indexed). That handler does the
# real work off the game thread via @minqlx.thread, following the same
# pattern demo_hook_autorecord.py's own _post() already uses in this
# codebase.
#
# The manifest/window/zip logic itself lives in demo_native_manifest.py, a
# pure module with no minqlx import (see tests/test_demo_native_manifest.py)
# - this file stays a thin wrapper: parse hook args, track match/player
# metadata minqlx already gives cheap access to, call into that module.
#
# CVARs:
#   qlx_nativeDemoRecordEnabled  "0"  - opt-in per instance

import os
import time

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

try:
    from demo_native_manifest import build_match_package
except ImportError:
    from .demo_native_manifest import build_match_package


class demo_native_autorecord(minqlx.Plugin):
    def __init__(self):
        self.set_cvar_once("qlx_nativeDemoRecordEnabled", "0")

        self.add_hook("game_countdown", self.on_game_countdown, priority=minqlx.Priority.LOWEST)
        self.add_hook("game_end", self.on_game_end, priority=minqlx.Priority.LOWEST)
        self.add_hook("demo_recording_started", self.on_demo_recording_started, priority=minqlx.Priority.LOWEST)
        self.add_hook("demo_match_finalized", self.on_demo_match_finalized, priority=minqlx.Priority.LOWEST)

        # Currently-armed match_id, used only to route
        # demo_recording_started events (which do NOT carry match_id
        # themselves) to the right entry below.
        self._match_id = None

        # match_id -> {"map": str, "names_by_path": {final_path: raw name}}.
        # Keyed by match_id, NOT held in flat self._map/self._names_by_path
        # scalars, because demo_match_finalized(match_id) fires
        # asynchronously on the finalize thread (Task 6a/6b's two-stage
        # cut + index can take a while for a long match) - a NEW match's
        # game_countdown can legitimately fire and re-arm before the
        # PREVIOUS match's demo_match_finalized arrives. Flat scalars would
        # have already been overwritten by the new match by then, silently
        # mislabelling the old match's .qlmatch with the new match's map/
        # names. Entries are created on game_countdown and consumed (popped)
        # on that same match_id's demo_match_finalized, so this never grows
        # past "number of matches currently between countdown and finalize"
        # (normally 0-1, at most a couple if finalize is unusually slow).
        self._pending = {}

    def _enabled(self):
        return self.get_cvar("qlx_nativeDemoRecordEnabled", bool) is True

    def _demo_dir(self):
        # Mirrors demo_match.c's own final_path construction exactly
        # (demo_seg_build_final(): "%s/%s/...", fs_homepath, sv_demoDir or
        # "demos") rather than hardcoding a guess - both cvars are plain
        # engine cvars, readable the same way demo_hook_autorecord.py reads
        # "mapname"/"net_port". sv_demoDir defaults to "demos" in upstream
        # demos.c's own Cvar_Get() registration, matched here for the case a
        # build somehow doesn't expose it (should not normally happen since C
        # registers it unconditionally at startup).
        #
        # These get_cvar() reads run on the finalize thread, not the game
        # thread. That is within the demo_match_finalized contract: a cvar is a
        # stable process-wide string, unlike live game state (players(), Player,
        # Entity/GameClient, client_t), which this handler must not touch - see
        # DemoMatchFinalizedDispatcher's comment in
        # qlds-scripts/patch-minqlxtended-demo-bindings.py.
        homepath = (self.get_cvar("fs_homepath") or "").strip()
        subdir = (self.get_cvar("sv_demoDir") or "").strip() or "demos"
        if not homepath:
            self.logger.warning("demo_native_autorecord: fs_homepath cvar empty, cannot locate demo dir")
            return None
        return os.path.join(homepath, subdir)

    def on_game_countdown(self):
        if not self._enabled():
            return minqlx.Return.NONE
        if not hasattr(minqlx, "demo_arm"):
            self.logger.warning(
                "demo_native_autorecord: minqlxtended build has no demo_arm binding "
                "(native multi-POV demo capture patch not applied/compiled); "
                "skipping native demo recording for this match")
            return minqlx.Return.NONE
        match_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        try:
            map_name = self.game.map or "unknown"
        except Exception:
            map_name = self.get_cvar("mapname") or "unknown"
        self._match_id = match_id
        self._pending[match_id] = {"map": map_name, "names_by_path": {}}
        minqlx.demo_arm(match_id, map_name)
        return minqlx.Return.NONE

    def on_demo_recording_started(self, slot, path, name):
        # Just tracking for later name resolution - the file itself is not
        # touched here. C already computed and owns `path` (the eventual
        # final .dm_91 path); the bytes are still the raw, uncut capture
        # upstream is writing under fs_homepath/sv_demoDir at this moment
        # (tmpfs staging was retired with the minqlxtended v1.0.0 port -
        # upstream's Demo_Request() picks the capture path now), so there is
        # nothing to read or package yet. No per-file sidecar JSON is
        # written here: it would only
        # duplicate index/*.snaps.json's own client_num/first_server_time/
        # last_server_time/game_start_server_time (Task 6b already writes
        # that once the file reaches final form), and this handler fires
        # before any of those fields are known.
        entry = self._pending.get(self._match_id)
        if entry is not None:
            entry["names_by_path"][path] = name
        return minqlx.Return.NONE

    def on_game_end(self, data):
        if not self._enabled():
            return minqlx.Return.NONE
        if not hasattr(minqlx, "demo_disarm"):
            # No matching warning here: on_game_countdown already logged
            # once for this match (demo_arm/demo_disarm land together, see
            # the patch script's all-or-nothing anchor check) - nothing was
            # armed, so there is nothing to disarm.
            return minqlx.Return.NONE
        minqlx.demo_disarm()
        # Files are not ready yet - the two-stage cut + snapshot index run
        # asynchronously on the finalize thread. Wait for
        # demo_match_finalized instead of building anything here.
        return minqlx.Return.NONE

    def on_demo_match_finalized(self, match_id):
        # Popped FIRST, unconditionally - before either early-return check
        # below. A prior version returned early on !_enabled()/no demo_dir
        # before popping: since files can already exist on disk for a match
        # that WAS actually recorded (armed while enabled, then the cvar
        # flipped off, or _demo_dir() failed transiently, before this event
        # arrived), that either leaked this entry in self._pending forever
        # or - worse - silently dropped a .qlmatch for a match that really
        # was captured, with no log line at all. Popping first means both
        # early-return paths below still lose the .qlmatch build for THIS
        # event (nothing to do about that - see the guards themselves), but
        # never leak the tracking entry, and we can at least log what
        # happened instead of going silent.
        entry = self._pending.pop(match_id, None)
        if not self._enabled():
            self.logger.warning(
                "demo_native_autorecord: match_id=%s finalized while disabled; "
                "not building a .qlmatch for it", match_id)
            return minqlx.Return.NONE
        demo_dir = self._demo_dir()
        if not demo_dir:
            self.logger.warning(
                "demo_native_autorecord: match_id=%s finalized but demo dir "
                "unavailable; not building a .qlmatch for it", match_id)
            return minqlx.Return.NONE
        # Looked up by the EVENT's own match_id, not any current-match
        # scalar - see the __init__ comment on self._pending for why. Falls
        # back to best-effort defaults (empty tracked names -> the manifest
        # module's own filename-parsing fallback kicks in; "unknown" map)
        # if this plugin instance never saw that match's countdown at all
        # (e.g. a mid-match plugin reload) rather than dropping the pack.
        map_name = (entry or {}).get("map") or "unknown"
        names_by_path = dict((entry or {}).get("names_by_path") or {})
        self._build_package(demo_dir, match_id, map_name, names_by_path)
        return minqlx.Return.NONE

    # This is the DemoMatchFinalizedDispatcher call site, which itself
    # already runs on the finalize thread (not the game thread - see Task
    # 5's report), so this Python handler runs synchronously on minqlx's
    # dispatch of that event, off the game thread already. It still must
    # not block whatever's calling it (the finalize thread has its own
    # work to get back to), so the actual glob/read-N-files/zip work is
    # offloaded again, one more hop, via @minqlx.thread - the same
    # established pattern this codebase already uses for I/O-bound plugin
    # work (see demo_hook_autorecord.py's own _post()).
    @minqlx.thread
    def _build_package(self, demo_dir, match_id, map_name, names_by_path):
        try:
            manifest, zip_path, ordered = build_match_package(demo_dir, match_id, map_name, names_by_path)
        except Exception as exc:
            self.logger.warning("demo_native_autorecord: package build failed for %s: %s", match_id, exc)
            return
        if zip_path is None:
            self.logger.warning(
                "demo_native_autorecord: no finalized .dm_91 files found for match %s in %s, no .qlmatch written",
                match_id, demo_dir,
            )
            return
        self.logger.info(
            "demo_native_autorecord: wrote %s (%d POV(s), window %s)",
            zip_path, len(ordered), manifest["window"],
        )
