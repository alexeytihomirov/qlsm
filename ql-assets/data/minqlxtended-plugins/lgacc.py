"""
lgacc - Private per-life lightning gun accuracy after each kill or death.

When you kill someone or get killed, you see your LG accuracy for that life
(spawn to kill/death) and your opponent's, as a message only you can see.
Scoreboard counters are only read, never reset.

Needs no engine patch on minqlxtended: per-weapon counters are readable memory.

Commands:
  !lgacc         - Toggle the message on/off
  !lgacc enemy   - Toggle the enemy line on/off
"""

import minqlxtended

WP_LIGHTNING = 6

DB_KEY = "minqlx:players:{}:lgacc:{}"


def _lg_counters(client_id):
    """Return (shots_fired, shots_hit) for the LG, or None if unavailable."""
    try:
        stats = minqlxtended.GameClient(client_id).expanded_stats
        return stats.shots_fired[WP_LIGHTNING], stats.shots_hit[WP_LIGHTNING]
    except (ValueError, TypeError, AttributeError, IndexError):
        return None


def _pct(hits, shots):
    return int(round(100.0 * hits / shots)) if shots else 0


class lgacc(minqlxtended.Plugin):
    def __init__(self):
        self.add_command("lgacc", self.cmd_lgacc, 0)

        self.add_hook("kill", self.handle_kill)
        self.add_hook("player_loaded", self.handle_loaded)
        self.add_hook("player_disconnect", self.handle_disconnect)
        self.add_hook("game_start", self.handle_game_start)

        # {steam_id: {"own": bool, "enemy": bool}}, both default on
        self._prefs = {}
        # {client_id: (shots, hits)} LG counters at the start of the current life
        self._baseline = {}

        for p in self.players():
            self._load_prefs(p)
            self._snapshot(p.id)

    # -------------------------------------------------------------------------
    # Preferences
    # -------------------------------------------------------------------------

    def _load_prefs(self, player):
        sid = player.steam_id
        self._prefs[sid] = {
            key: self.db.get(DB_KEY.format(sid, key)) != "0"
            for key in ("own", "enemy")
        }

    def _set_pref(self, player, key, value):
        self._prefs.setdefault(player.steam_id, {"own": True, "enemy": True})[key] = value
        db_key = DB_KEY.format(player.steam_id, key)
        if value:
            self.db.delete(db_key)
        else:
            self.db[db_key] = "0"

    def _pref(self, player, key):
        return self._prefs.get(player.steam_id, {}).get(key, True)

    def handle_loaded(self, player):
        self._load_prefs(player)
        self._snapshot(player.id)

    def handle_disconnect(self, player, reason):
        self._prefs.pop(player.steam_id, None)
        self._baseline.pop(player.id, None)

    def handle_game_start(self):
        for p in self.players():
            self._snapshot(p.id)

    def cmd_lgacc(self, player, msg, channel):
        if len(msg) == 1:
            on = not self._pref(player, "own")
            self._set_pref(player, "own", on)
            player.tell("^7LG accuracy message: " + ("^2enabled" if on else "^1disabled") + "^7.")
        elif len(msg) == 2 and msg[1].lower() == "enemy":
            on = not self._pref(player, "enemy")
            self._set_pref(player, "enemy", on)
            player.tell("^7LG accuracy enemy line: " + ("^2enabled" if on else "^1disabled") + "^7.")
        else:
            player.tell("^7Usage: ^3!lgacc ^7or ^3!lgacc enemy")
        return minqlxtended.Return.STOP_ALL

    # -------------------------------------------------------------------------
    # Per-life tracking
    # -------------------------------------------------------------------------

    def _snapshot(self, client_id):
        counters = _lg_counters(client_id)
        if counters is not None:
            self._baseline[client_id] = counters

    def _life_stats(self, client_id):
        """Return (shots, hits) since the last snapshot, or None."""
        now = _lg_counters(client_id)
        if now is None:
            return None
        base = self._baseline.get(client_id)
        if base is None:
            return None
        # Counters below the baseline were zeroed (reset_acc, new match).
        # More hits than shots since the baseline means the same thing: the
        # counters were zeroed and have since climbed past a stale baseline.
        if (now[0] < base[0] or now[1] < base[1]
                or now[1] - base[1] > now[0] - base[0]):
            base = (0, 0)
        return now[0] - base[0], now[1] - base[1]

    def handle_kill(self, victim, killer, mod):
        if killer is None or killer.steam_id == victim.steam_id:
            self._snapshot(victim.id)
            return

        is_teamkill = killer.team == victim.team and killer.team in (minqlxtended.Team.RED, minqlxtended.Team.BLUE)
        victim_life = self._life_stats(victim.id)
        killer_life = self._life_stats(killer.id)
        self._snapshot(victim.id)
        self._snapshot(killer.id)

        if is_teamkill or victim_life is None or killer_life is None:
            return

        self._send(killer, killer_life, victim_life)
        self._send(victim, victim_life, killer_life)

    def _send(self, player, own, enemy):
        if not self._pref(player, "own") or not (own[0] or enemy[0]):
            return
        # Full-width percent sign: the QL client treats an ASCII % in printed
        # text as a format code, which corrupts client state (view/movement).
        player.tell("^7You: ^3{}％".format(_pct(own[1], own[0])))
        if self._pref(player, "enemy"):
            player.tell("^7Enemy: ^1{}％".format(_pct(enemy[1], enemy[0])))
