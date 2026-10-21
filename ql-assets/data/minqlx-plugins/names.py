# minqlx - Extends Quake Live's dedicated server with extra functionality and scripting.
# Copyright (C) 2015 Mino <mino@minomino.org>

# This file is part of minqlx.

# minqlx is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# minqlx is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with minqlx. If not, see <http://www.gnu.org/licenses/>.

import minqlx
import re

VERSION = "1.1.0"

_re_remove_excessive_colors = re.compile(r"(?:\^.)+(\^.)")
_name_key = "minqlx:players:{}:colored_name"

class names(minqlx.Plugin):
    def __init__(self):
        self.add_hook("player_connect", self.handle_player_connect)
        self.add_hook("player_loaded", self.handle_player_loaded)
        self.add_hook("player_disconnect", self.handle_player_disconnect)
        self.add_hook("userinfo", self.handle_userinfo)
        self.add_command(("name", "setname"), self.cmd_name, usage="<name>", client_cmd_perm=0)

        self.set_cvar_once("qlx_enforceSteamName", "1")

        self.steam_names = {}
        self.name_set = set()

    def handle_player_connect(self, player):
        self.steam_names[player.steam_id] = player.clean_name
    
    def handle_player_loaded(self, player):
        name_key = _name_key.format(player.steam_id)
        if name_key in self.db:
            db_name = self.db[name_key]
            if not self.get_cvar("qlx_enforceSteamName", bool) or self.clean_text(db_name).lower() == player.clean_name.lower():
                self._assign_name(player, db_name)

    def handle_player_disconnect(self, player, reason):
        self.steam_names.pop(player.steam_id, None)
        self.name_set.discard(player.steam_id)

    def handle_userinfo(self, player, changed):
        if "name" not in changed:
            return
        sid = player.steam_id
        # Only this player's synchronous name assignment is ours.
        if sid in self.name_set:
            self.name_set.discard(sid)
            return
        current_clean = self.clean_text(changed["name"])
        baseline = self.steam_names.setdefault(sid, current_clean)
        name_key = _name_key.format(sid)
        # Keep observing external Redis additions, edits and deletions per name event.
        registered = self.db.get(name_key)
        if registered is None:
            self.steam_names[sid] = current_clean
        elif baseline == current_clean:
            if not self.get_cvar("qlx_enforceSteamName", bool) or self.clean_text(registered).lower() == current_clean.lower():
                changed["name"] = registered
                return changed
        else:
            self.steam_names[sid] = current_clean
            del self.db[name_key]
            player.tell("Your registered name has been reset.")

    def cmd_name(self, player, msg, channel):
        name_key = _name_key.format(player.steam_id)
        
        if len(msg) < 2:
            if name_key not in self.db:
                return minqlx.RET_USAGE
            else:
                del self.db[name_key]
                player.tell("Your registered name has been removed.")
                return minqlx.RET_STOP_ALL
        
        name = self.clean_excessive_colors(" ".join(msg[1:]))
        if len(name.encode()) > 36:
            player.tell("The name is too long. Consider using fewer colors or a shorter name.")
            return minqlx.RET_STOP_ALL
        elif self.clean_text(name).lower() != player.clean_name.lower() and self.get_cvar("qlx_enforceSteamName", bool):
            player.tell("The new name must match your current Steam name.")
            return minqlx.RET_STOP_ALL
        elif "\\" in name:
            player.tell("The character '^6\\^7' cannot be used. Sorry for the inconvenience.")
            return minqlx.RET_STOP_ALL
        elif not self.clean_text(name).strip():
            player.tell("Blank names cannot be used. Sorry for the inconvenience.")
            return minqlx.RET_STOP_ALL

        # A command after reload has only the current player snapshot available.
        # Do not replace an existing original-client baseline with our alias.
        self.steam_names.setdefault(player.steam_id, player.clean_name)
        name = "^7" + name
        self._assign_name(player, name)
        self.db[name_key] = name
        player.tell("The name has been registered. To make me forget about it, a simple ^6{}name^7 will do it."
            .format(self.get_cvar("qlx_commandPrefix")))
        return minqlx.RET_STOP_ALL

    def _assign_name(self, player, name):
        if player.cvars.get("name") == name:
            return
        self.name_set.add(player.steam_id)
        try:
            player.name = name
        finally:
            # client_command is synchronous; blocked/no-event/error writes must
            # never leave a marker that consumes a later genuine client rename.
            self.name_set.discard(player.steam_id)

    def clean_excessive_colors(self, name):
        """Removes excessive colors and only keeps the ones that matter."""
        def sub_func(match):
            return match.group(1)

        return _re_remove_excessive_colors.sub(sub_func, name)

