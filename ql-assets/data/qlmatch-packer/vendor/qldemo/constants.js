export const GENTITYNUM_BITS = 10;
export const MAX_GENTITIES = 1 << GENTITYNUM_BITS;
export const ENTITYNUM_NONE = MAX_GENTITIES - 1;
export const FLOAT_INT_BITS = 13;
export const FLOAT_INT_BIAS = 1 << (FLOAT_INT_BITS - 1);

export const SVC_BAD = 0;
export const SVC_NOP = 1;
export const SVC_GAMESTATE = 2;
export const SVC_CONFIGSTRING = 3;
export const SVC_BASELINE = 4;
export const SVC_SERVERCOMMAND = 5;
export const SVC_DOWNLOAD = 6;
export const SVC_SNAPSHOT = 7;
export const SVC_EOF = 8;

export const ET_GENERAL = 0;
export const ET_PLAYER = 1;
export const ET_ITEM = 2;
export const ET_MISSILE = 3;
export const ET_EVENTS = 13;

export const TEAM_SPECTATOR = "3";

export const MAX_CLIENTS = 64;
export const MAX_MODELS = 256;
export const MAX_SOUNDS = 256;
export const MAX_STATS = 16;
export const MAX_PERSISTANT = 16;
export const MAX_POWERUPS = 16;
export const MAX_WEAPONS = 16;
export const MAX_MAP_AREA_BYTES = 32;
export const PACKET_BACKUP = 32;
export const PACKET_MASK = PACKET_BACKUP - 1;

export const CS_SERVERINFO = 0;
export const CS_SYSTEMINFO = 1;
export const CS_MODELS = 17;
export const CS_SOUNDS = CS_MODELS + MAX_MODELS;
export const CS_PLAYERS = CS_SOUNDS + MAX_SOUNDS;

export const CS_STRING_MAP = {
  0: "serverinfo",
  1: "systeminfo",
  5: "warmup",
  6: "scores1",
  7: "scores2",
  13: "level_start_time",
  686: "1stplayer",
  687: "2ndplayer",
};

export const STAT_HEALTH = 0;
/** dm_91 (UDT LifeStats_73p): armor is stats[4], not stats[1]. */
export const STAT_ARMOR = 4;
export const STAT_WEAPON = 2;
