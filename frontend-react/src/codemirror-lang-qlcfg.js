import { StreamLanguage } from '@codemirror/language';
import { tags as t } from '@lezer/highlight';
import { autocompletion } from '@codemirror/autocomplete';

export const qlcfgLanguage = StreamLanguage.define({
  startState: function () {
    return {
      afterSet: false // True if 'set' was just processed, expecting a variable name
    };
  },
  token: function (stream, state) {
    if (stream.sol()) { // Start of line
      state.afterSet = false;
    }

    // Comments
    if (stream.match("//")) {
      stream.skipToEnd();
      return "comment";
    }

    // Strings
    if (stream.match(/"(?:[^\\]|\\.)*?"/)) {
      return "string";
    }

    // 'set' keyword
    if (stream.match(/\bset\b/i)) { // Use regex for whole word, case-insensitive match
      state.afterSet = true;
      return "keyword";
    }

    // Variable name after 'set'
    if (state.afterSet) {
      if (stream.match(/[a-zA-Z_][a-zA-Z0-9_]*/)) {
        state.afterSet = false; // Reset after matching the variable
        return "variableName"; // CodeMirror 6 uses camelCase for token types more often
      }
    }

    // If nothing else matches, advance the stream
    stream.next();
    return null;
  },
  languageData: {
    commentTokens: { line: "//" }
  },
  tokenTable: {
    comment: t.lineComment,
    string: t.string,
    keyword: t.keyword,
    variableName: t.variableName
  }
});

// Cvars managed by the app — setting these manually has no effect
const MANAGED_CVARS = {
  sv_lanforcerate: 'Managed by the 99k LAN rate toggle. Default: 0 (99k LAN rate OFF).',
  net_ip: 'Forced to "" by the app (binds all interfaces, required for 99k LAN rate).',
  net_strict: 'Forced to 1 by the app.',
  qlx_redisaddress: 'Forced by the app. TCP hosts: 127.0.0.1:6379. Socket-enabled hosts: /var/run/redis/redis.sock.',
  qlx_redisunixsocket: 'Forced by the app. Set to 1 on socket-enabled hosts; omitted on TCP hosts.',
  qlx_redispassword: 'Forced by the app (self-host only).',
  qlx_redisdatabase: 'Managed by the app. Derived from instance port.',
  fs_homepath: 'Managed by the app.',
  qlx_pluginspath: 'Managed by the app.',
  zmq_rcon_enable: 'Managed by the app.',
  zmq_rcon_port: 'Managed by the app.',
  zmq_rcon_password: 'Managed by the app.',
  zmq_stats_port: 'Managed by the app.',
  zmq_stats_password: 'Managed by the app.',
  net_port: null, // Message depends on context — see linter
  qlx_plugins: 'Managed via the Plugins tab in the UI.',
};

// Strip values from managed cvars in a server.cfg string (set cvar "value" → set cvar "")
const MANAGED_CVAR_SET = new Set(Object.keys(MANAGED_CVARS));
export const stripManagedCvars = (cfg) => {
  if (!cfg) return cfg;
  return cfg.replace(
    /^(\s*set\s+)(\S+)(\s+")(.*?)(".*)/gim,
    (full, prefix, cvar, mid, _value, suffix) =>
      MANAGED_CVAR_SET.has(cvar.toLowerCase()) ? `${prefix}${cvar}${mid}${suffix}` : full
  );
};

// Factory function to create the linter with access to available ports and an error reporting callback
export const createQlCfgLinter = (availablePorts = [], onLintResults = () => { }) => {
  // The actual linter function returned by the factory
  return (view) => {
    let diagnostics = [];
    const setCvarRegex = /^\s*set\s+(\S+)/i; // Captures the cvar name after 'set'

    for (let n = 1; n <= view.state.doc.lines; n++) {
      const line = view.state.doc.line(n);
      const text = line.text; // Use full line text to get accurate positions

      // Check for managed cvars (info diagnostics) — runs first to skip
      // error-level checks (e.g. net_port validation) for app-managed cvars
      const cvarMatch = text.match(setCvarRegex);
      if (cvarMatch) {
        const cvarName = cvarMatch[1];
        const cvarKey = cvarName.toLowerCase();
        let infoMessage = MANAGED_CVARS[cvarKey];
        if (cvarKey === 'net_port') {
          infoMessage = availablePorts.length > 0
            ? 'Managed by the port selection above.'
            : 'Set during deployment and cannot be changed.';
        }
        if (infoMessage) {
          const cvarStartPos = line.from + text.indexOf(cvarName);
          diagnostics.push({
            from: cvarStartPos,
            to: cvarStartPos + cvarName.length,
            severity: 'info',
            message: `This cvar will be ignored. ${infoMessage}`,
          });
          continue;
        }
      }
    }
    // Report linting results (true if errors exist, false otherwise)
    const hasErrors = diagnostics.some(d => d.severity === 'error');
    onLintResults(hasErrors);
    return diagnostics;
  };
};

// Engine/QLDS cvars an operator commonly sets in server.cfg. Descriptions are
// taken from the annotated default server.cfg (qlsm/configs/presets/_builtin/default/server.cfg)
// where available, cross-checked against skills/ql-live/reference (cvar-metadata.md,
// commands-builtin.md) — see that skill before trusting a Steam guide over this list.
const QL_ENGINE_CVARS = {
  sv_hostname: 'Server name shown in the server browser.',
  sv_tags: 'Comma-delimited server tags shown in the browser (in addition to gametype/mod tags).',
  sv_mapPoolFile: 'Map pool file the server uses (see mappool*.txt for the format).',
  g_accessFile: 'File listing 64-bit Steam IDs with admin access or bans.',
  sv_maxClients: 'How many players can connect at once.',
  g_password: 'Server-wide password; blocks connections that don\'t supply it.',
  sv_privateClients: 'Reserved slots usable with sv_privatePassword.',
  sv_privatePassword: 'Password for the reserved sv_privateClients slots.',
  com_hunkMegs: 'Memory hunk size in MB; may need increasing for more players.',
  sv_floodprotect: 'Kicks a player once they reach this many client commands in the flood window (decays by 1/sec).',
  g_floodprot_maxcount: 'Kicks a player when their userinfo flood counter reaches this level.',
  g_floodprot_decay: 'Milliseconds between each decrement of the userinfo flood counter.',
  qlx_owner: 'Steam ID that can use all minqlx commands without being listed in access.txt.',
  g_voteFlags: 'Bitmask of callvote types to disable: map=1, map_restart=2, nextmap=4, gametype=8, kick=16, timelimit=32, fraglimit=64, shuffle=128, teamsize=256, cointoss/random=512, loadouts=1024, end-game voting=2048, ammo=4096, timers=8192.',
  g_allowVote: 'Master switch for all callvotes.',
  g_voteDelay: 'Milliseconds after map load before votes are allowed.',
  g_voteLimit: 'Max votes a player may call per map (0 = unlimited).',
  g_allowVoteMidGame: 'Allows callvotes once the map has already started.',
  g_allowSpecVote: 'Allows spectators to call votes.',
  sv_warmupReadyPercentage: 'Fraction of players that must ready up before the match starts.',
  g_warmupDelay: 'Seconds to wait in warmup before allowing the match to start, so players can connect.',
  g_warmupReadyDelay: 'Forces the match to start this many seconds after someone readies up.',
  g_warmupReadyDelayAction: '1 = force players to spectator after g_warmupReadyDelay, 2 = force ready up.',
  g_inactivity: 'Kicks players inactive for this many seconds (0 = disabled).',
  g_alltalk: '0 = team-only voice chat, 1 = all players can talk to each other, 2 = also hear your own voice (testing).',
  net_strict: 'Quit immediately if the server can\'t bind the configured IP/port.',
  net_ip: 'IP to bind to; blank binds all interfaces.',
  net_port: 'UDP port to bind to; blank starts at 27960 and increments if net_strict is 0.',
  sv_serverType: '0 = Offline, 1 = LAN, 2 = Internet.',
  sv_master: 'Whether the server responds to master-server queries (appears in the browser).',
  sv_fps: 'Server tick rate. Read-only at runtime (CVAR_ROM) — only takes effect from the command line or a minqlx force-set.',
  sv_idleExit: 'Exits the server if idle (no map running) for this many seconds; useful for auto-restart.',
  zmq_rcon_enable: 'Enables the ZeroMQ remote console. Cannot be toggled after launch.',
  zmq_rcon_ip: 'IP the ZMQ rcon socket binds to.',
  zmq_rcon_port: 'TCP port for ZMQ rcon; must differ from the stats port if both are used.',
  zmq_rcon_password: 'Password for the ZMQ rcon socket (can change after launch).',
  zmq_stats_enable: 'Enables the ZeroMQ stats socket.',
  zmq_stats_ip: 'IP the ZMQ stats socket binds to.',
  zmq_stats_port: 'TCP port for the ZMQ stats socket; defaults to the game server\'s IP/port if unset.',
  zmq_stats_password: 'Password for the ZMQ stats socket.',
  serverstartup: 'Command run once the engine finishes initializing — normally a map to start, e.g. "map campgrounds ffa" or "startRandomMap".',
  fs_homepath: 'Writable data directory (configs, plugins, downloads).',
  fs_basepath: 'Read-only base game data directory.',
  fs_game: 'Mod/game directory name (normally baseq3).',
};

// Non-"set" console commands worth suggesting at the start of a .cfg line
// (exec chains another config, vstr/alias/bind are common in server.cfg
// snippets). Descriptions verified against skills/ql-live/reference/data/commands-builtin.json.
const QL_CFG_COMMANDS = {
  set: 'Sets a cvar (no archive flag).',
  seta: 'Sets a cvar with the archive flag (persisted by writeconfig).',
  exec: 'Executes another configuration file.',
  vstr: 'Executes commands stored in a cvar.',
  alias: 'Creates a command alias.',
  bind: 'Binds a key to a command/alias.',
  unbindall: 'Removes all set binds.',
  toggle: 'Inverts a cvar\'s boolean value.',
  reset: 'Resets a cvar to its initial value.',
  clearcvar: 'Clears a cvar\'s value, setting it to "".',
  cvar_restart: 'Restarts the cvar subsystem, clearing most cvar changes.',
  writeconfig: 'Writes a config file with all set cvars and binds.',
  condump: 'Dumps buffered console text to a file.',
  map: 'Loads a map normally.',
  devmap: 'Loads a map in development/cheats mode.',
  reload_mappool: 'Re-reads the map pool file — needed because the pool is otherwise only read at server init.',
};

// qlx_ (and other plugin-owned) cvars aggregated from every plugin manifest
// in ql-assets/data/minqlx-plugins/*.ql-plugin.json. Kept as a static snapshot
// here rather than importing the manifests directly, since the frontend build
// has no access to that backend data directory — re-run this list past the
// manifests if plugin cvars are added/renamed (see also PluginCvarsModal for
// the per-plugin editing UI, which reads the manifests live).
const QLX_PLUGIN_CVARS = {
  qlx_chatRconEnabled: 'chat_rcon — turns !rcon in chat on or off entirely.',
  qlx_chatRconRefPerm: 'chat_rcon — minimum minqlx permission level treated as a referee tier.',
  qlx_chatRconAdminPerm: 'chat_rcon — minimum minqlx permission level treated as the admin tier.',
  qlx_chatRconRefCommands: 'chat_rcon — comma-separated RCON commands referees are allowed to run.',
  qlx_chatRconAdminDeny: 'chat_rcon — comma-separated RCON commands even admins are not allowed to run.',
  qlx_aliasLimitOutputLines: 'aliases — max lines !alias prints before truncating.',
  qlx_balanceUseLocal: 'balance — prefer locally-stored (manually set) ratings over QLStats when available.',
  qlx_balanceLocalExpires: 'balance — seconds until a manually-set local rating expires (0 = never).',
  qlx_balanceUrl: 'balance — host of the QLStats-compatible ratings API.',
  qlx_balanceAuto: 'balance — automatically suggest a balance shuffle when appropriate.',
  qlx_balanceMinimumSuggestionDiff: 'balance — minimum team rating difference before a switch is suggested.',
  qlx_balanceMinimumSuggestionActionDiff: 'balance — minimum team rating difference before a switch is auto-actioned.',
  qlx_balanceApi: 'balance — which rating API/algorithm to query (e.g. elo).',
  qlx_disablePlayerRemoval: 'custom_votes — blocks /cv votes that would kick/remove a player.',
  qlx_disableCvarVoting: 'custom_votes — blocks /cv votes that change server cvars.',
  qlx_disableServerRebootVote: 'custom_votes — blocks the /cv vote type that restarts the server.',
  qlx_cvarVotePermissionRequired: 'custom_votes — minimum permission level required to call a cvar-changing /cv vote.',
  qlx_glasshouse: 'custom_votes — enables the glasshouse ruleset variant.',
  qlx_funSoundDelay: 'fun — seconds to wait before playing the !cookies sound.',
  g_rrInfectedMastermindHealthBonus: 'infectedmm — extra health given to the Mastermind (infected leader).',
  g_rrInfectedMastermindFragBonus: 'infectedmm — frags awarded for the Mastermind role at round end.',
  qlx_lanPlayersOnly: 'lan — reject connections that don\'t come from an allowed LAN subnet.',
  qlx_lanAllowIndirectConnections: 'lan — allow connections routed through the configured LAN router/NAT.',
  qlx_lanSubnets: 'lan — comma-separated list of subnets treated as LAN.',
  qlx_lanRouter: 'lan — router/gateway address used for indirect-connection checks.',
  qlx_lanHostname: 'lan — hostname shown to players for connecting over LAN.',
  qlx_lanInterface: 'lan — network interface used for LAN-only checks.',
  qlx_leaverBan: 'leaverban — turns leaver auto-ban tracking on or off.',
  qlx_leaverBanRollingWindowDays: 'leaverban — days over which leaves are counted before rolling off.',
  qlx_leaverBanMaxLeaves: 'leaverban — leaves within the rolling window before a ban is issued.',
  qlx_statOtherPlayersPermission: 'leaverban — minimum permission level required to check another player\'s leave stats.',
  qlx_leaverBanDiscordWebhook: 'leaverban — optional Discord webhook notified when a leaver ban is issued.',
  qlx_chatlogs: 'log — number of rotated chat log files to keep.',
  qlx_chatlogsSize: 'log — max size in bytes before a chat log file is rotated.',
  qlx_spawnvisDuration: 'maptools — how long !spawnvis markers stay visible.',
  qlx_spawnvisItem: 'maptools — item classname used to mark spawn points for !spawnvis.',
  qlx_motdSound: 'motd — sound file played when the MOTD is shown.',
  qlx_motdHeader: 'motd — header text shown above the message of the day.',
  qlx_enforceSteamName: 'names — requires the in-game name to match (colour codes aside) the player\'s Steam name.',
  qlx_matchRestoreLabEnabled: 'match_restore — turns the checkpoint/restore command set on or off.',
  qlx_matchRestoreNativeClock: 'match_restore — use the engine\'s own match clock instead of the plugin\'s tracked clock.',
  qlx_matchRestoreUnfreezeDelaySec: 'match_restore — seconds to wait after applying a checkpoint before unfreezing play.',
  qlx_queueSetAfkPermission: 'queue — minimum permission level required to mark another player as AFK.',
  qlx_queueAFKTag: 'queue — text appended to a player\'s name while marked AFK.',
  qlx_commandPrefix: 'essentials — prefix players type before a chat command (shared across all plugins).',
  qlx_votepass: 'essentials — automatically passes votes that meet the pass threshold.',
  qlx_votepassThreshold: 'essentials — fraction of yes votes needed to auto-pass a vote.',
  qlx_teamsizeMinimum: 'essentials — lowest teamsize value !teamsize will accept.',
  qlx_teamsizeMaximum: 'essentials — highest teamsize value !teamsize will accept.',
  qlx_enforceMappool: 'essentials — restricts !map and map votes to the configured map pool file.',
  qlx_svfps: 'sv_fps — the sv_fps value this plugin enforces (must be a multiple of 40).',
  qlx_statsHubUnifiedEnabled: 'stream_telemetry_unified — master switch for all telemetry sent by this plugin.',
  qlx_streamTelemetryEnabled: 'stream_telemetry_unified — sends live player position/view-angle telemetry for the stream overlay.',
  qlx_pickupTelemetryEnabled: 'stream_telemetry_unified — sends item-pickup events.',
  qlx_pickupTelemetryDebug: 'stream_telemetry_unified — logs extra debug output for pickup telemetry.',
  qlx_sessionEventsEnabled: 'stream_telemetry_unified — sends player join/leave session events.',
  qlx_statsHubUrl: 'stream_telemetry_unified — ingest URL telemetry is POSTed to (stats-hub or local telemetry-relay).',
  qlx_statsHubToken: 'stream_telemetry_unified — auth token sent with each telemetry POST.',
  qlx_statsHubInterval: 'stream_telemetry_unified — seconds between telemetry sends during normal play.',
  qlx_statsHubIdleInterval: 'stream_telemetry_unified — seconds between telemetry sends when idle/warmup.',
  qlx_statsHubAccuracyInterval: 'stream_telemetry_unified — seconds between accuracy-stat telemetry sends.',
  qlx_statsHubMatchId: 'stream_telemetry_unified — fixed match ID to tag telemetry with.',
  qlx_statsHubServerId: 'stream_telemetry_unified — server ID this instance reports telemetry as.',
  qlx_statsHubTournamentId: 'stream_telemetry_unified — tournament ID this instance\'s telemetry is tagged with.',
  qlx_tournamentAccessEnabled: 'tournament_access — turns the tournament join-gate on or off.',
  qlx_tournamentId: 'tournament_access — ID of the tournament whose roster gates access to this server.',
  qlx_tournamentAccessBypassPerm: 'tournament_access — minimum permission level that bypasses the roster gate.',
  qlx_devAuthOpen: 'tournament_access — disables the roster gate entirely for local/dev testing.',
  qlx_untrackedPlayerAction: 'untracked — 0 = do nothing, 1 = prevent team changes, 2 = prevent connecting.',
  qlx_blockVpnConnections: 'vpnblock — turns VPN/datacentre IP blocking on or off.',
  qlx_vpnBlockRefreshHours: 'vpnblock — how often the known VPN/datacentre IP range list is refreshed.',
  qlx_privatiseVotes: 'votestats — hides \'x voted y\' messages for all players by default.',
  qlx_workshopReferences: 'workshop — comma-separated list of Steam Workshop item IDs to force-download.',
  qlx_serverBrandName: 'branding — custom brand name shown in place of/alongside the server name.',
  qlx_serverBrandTopField: 'branding — custom text shown in the top branding field.',
  qlx_serverBrandBottomField: 'branding — custom text shown in the bottom branding field.',
  qlx_connectMessage: 'branding — message shown to a player when they connect.',
  qlx_loadedMessage: 'branding — message shown once the player has fully loaded in.',
  qlx_countdownMessage: 'branding — message shown during the match countdown.',
  qlx_endOfGameMessage: 'branding — message shown when the game ends.',
  qlx_brandingPrependMapName: 'branding — prepends the map name to the branded display text.',
  qlx_brandingAppendGameType: 'branding — appends the game type to the branded display text.',
  qlx_rainbowBrandName: 'branding — cycles the brand name through rainbow colours.',
  qlx_lobbyEnabled: 'lobby — turns lobby redirect behaviour on or off.',
  qlx_lobbyPublicHost: 'lobby — public hostname/IP players are told to connect to.',
  qlx_lobbyDestinations: 'lobby — configured destination servers (slug list).',
  qlx_lobbyDefaultDest: 'lobby — slug of the destination server used when none is assigned.',
  qlx_lobbyAutoRedirect: 'lobby — automatically redirects players without requiring !go.',
  qlx_lobbyRedirectDelay: 'lobby — seconds to wait before auto-redirecting a player.',
  qlx_lobbyForceSpec: 'lobby — forces players into spectator while in the lobby.',
  qlx_lobbyStayPerm: 'lobby — minimum permission level allowed to stay in the lobby without being redirected.',
  qlx_lobbyConnectMessage: 'lobby — extra message shown to a player on connecting to the lobby.',
  qlx_lobbyTrySteamOpen: 'lobby — attempts a Steam-open connect flow when redirecting.',
  qlx_lobbyInstancesJson: 'lobby — path to a JSON file describing available destination instances.',
  qlx_hubNotifyDelay: 'lobby — seconds before notifying the Hub of a pending tournament match.',
  qlx_hubNotifyCountdown: 'lobby — shows a countdown message before the Hub notify fires.',
};

// Merge order matters: app-managed notes (MANAGED_CVARS) win over plain engine
// docs, since setting those cvars by hand has no effect regardless of what
// they normally do — see stripManagedCvars/the linter above.
export function cvarCompletionOptions(prefix) {
  const seen = new Map();
  const add = (cvar, description, type) => {
    const key = cvar.toLowerCase();
    if (seen.has(key)) return;
    seen.set(key, { label: cvar, detail: type, info: description || undefined, type: 'variable' });
  };
  for (const [cvar, msg] of Object.entries(MANAGED_CVARS)) {
    add(cvar, msg ? `Managed by the app. ${msg}` : 'Managed by the app.', 'app-managed');
  }
  for (const [cvar, description] of Object.entries(QLX_PLUGIN_CVARS)) {
    add(cvar, description, 'plugin cvar');
  }
  for (const [cvar, description] of Object.entries(QL_ENGINE_CVARS)) {
    add(cvar, description, 'engine cvar');
  }
  const lower = prefix.toLowerCase();
  return [...seen.values()].filter(o => o.label.toLowerCase().includes(lower));
}

export function commandCompletionOptions(prefix) {
  const lower = prefix.toLowerCase();
  return Object.entries(QL_CFG_COMMANDS)
    .filter(([name]) => name.toLowerCase().includes(lower))
    .map(([name, description]) => ({ label: name, detail: 'command', info: description, type: 'keyword' }));
}

// Suggests cvar names right after `set ` (with descriptions from the engine
// cvar list and every plugin manifest's cvars), or console commands at the
// start of a line. Returns null inside comments/strings so it stays out of
// the way while editing a value.
function qlCfgCompletionSource(context) {
  const line = context.state.doc.lineAt(context.pos);
  const before = line.text.slice(0, context.pos - line.from);
  if (/\/\//.test(before)) return null; // past a comment marker on this line

  const setMatch = before.match(/^\s*set\s+(\S*)$/i);
  if (setMatch) {
    const word = context.matchBefore(/\S*/);
    const options = cvarCompletionOptions(setMatch[1]);
    if (options.length === 0) return null;
    return { from: word ? word.from : context.pos, options, filter: false };
  }

  const bareWordMatch = before.match(/^\s*(\S*)$/);
  if (bareWordMatch) {
    const word = context.matchBefore(/\S*/);
    const options = commandCompletionOptions(bareWordMatch[1]);
    if (options.length === 0) return null;
    return { from: word ? word.from : context.pos, options, filter: false };
  }

  return null;
}

export const qlCfgCompletion = autocompletion({ override: [qlCfgCompletionSource] });
