import assert from "node:assert/strict";
import { test } from "node:test";
import { ET_PLAYER, MAX_CLIENTS } from "./constants.js";
import { createEntityState, TR_STATIONARY } from "./entity-state.js";
import { demoToReplay } from "./demo-to-replay.js";

// EV_ITEM_PICKUP=15 with one toggle-bit (bit 8) set, matching how the real
// wire delta looks (see entity-events.js's ES_EVENT_BITS=0x300 comment).
const EV_ITEM_PICKUP_RAW = 15 | 0x100;
const ITEM_ARMOR_BODY_INDEX = 3; // QL91_ITEM_CLASSNAMES[3] (constants.js)

function otherPlayerEntity({ clientNum, x, y, z, event = 0, eventParm = 0 }) {
  const ent = createEntityState();
  ent.number = MAX_CLIENTS + clientNum;
  ent.eType = ET_PLAYER;
  ent.pos.trType = TR_STATIONARY;
  ent.pos.trBase = [x, y, z];
  ent.health = 100;
  ent.event = event;
  ent.eventParm = eventParm;
  return ent;
}

/** Minimal fake QLDemoParser: only the surface demoToReplay() actually reads. */
function fakeParser(snapshots) {
  return {
    mapName: () => "bloodrun",
    gametype: () => "duel",
    gamestate: {
      clientNum: 0,
      players: { 0: { n: "A" }, 1: { n: "B" } },
      spectators: {},
    },
    playerRows: () => [{ clientNum: 0 }, { clientNum: 1 }],
    serverCommands: [],
    snapshots,
  };
}

test("entity-observed EV_ITEM_PICKUP on another player's entity emits an exact pickup, not the PVS heuristic", () => {
  const parser = fakeParser([
    // First sighting of clientNum 1's entity: baseline, event=0 - no pickup.
    { serverTime: 1000, entities: [otherPlayerEntity({ clientNum: 1, x: 100, y: 200, z: 300 })] },
    // Fresh EV_ITEM_PICKUP fires on the same entity.
    {
      serverTime: 1025,
      entities: [
        otherPlayerEntity({
          clientNum: 1,
          x: 100,
          y: 200,
          z: 300,
          event: EV_ITEM_PICKUP_RAW,
          eventParm: ITEM_ARMOR_BODY_INDEX,
        }),
      ],
    },
    // Same raw event value carried forward (delta didn't touch it) - must not re-trigger.
    {
      serverTime: 1050,
      entities: [
        otherPlayerEntity({
          clientNum: 1,
          x: 100,
          y: 200,
          z: 300,
          event: EV_ITEM_PICKUP_RAW,
          eventParm: ITEM_ARMOR_BODY_INDEX,
        }),
      ],
    },
  ]);

  const replay = demoToReplay(parser, { povClientNum: 0, mapTable: [], includePickups: true });
  const pickups = replay.events.filter((e) => e.event === "pickup");

  assert.equal(pickups.length, 1, "exactly one pickup event, not zero and not a duplicate");
  const [pickup] = pickups;
  assert.equal(pickup.item, "item_armor_body");
  assert.equal(pickup.clientNum, 1);
  assert.equal(pickup.action, "pickup");
  assert.equal(pickup.source, "entity");
  assert.equal(pickup.game_time_ms, 25);
});

test("a stale non-zero event on an entity's first sighting is not mistaken for a fresh pickup", () => {
  const parser = fakeParser([
    // Entity enters this POV's view already mid-toggle (e.g. re-entering PVS) - no prior raw value to diff against.
    {
      serverTime: 1000,
      entities: [
        otherPlayerEntity({
          clientNum: 1,
          x: 100,
          y: 200,
          z: 300,
          event: EV_ITEM_PICKUP_RAW,
          eventParm: ITEM_ARMOR_BODY_INDEX,
        }),
      ],
    },
    { serverTime: 1025, entities: [otherPlayerEntity({ clientNum: 1, x: 100, y: 200, z: 300 })] },
  ]);

  const replay = demoToReplay(parser, { povClientNum: 0, mapTable: [], includePickups: true });
  const pickups = replay.events.filter((e) => e.event === "pickup");
  assert.equal(pickups.length, 0);
});
