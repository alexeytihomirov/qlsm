import assert from "node:assert/strict";
import { test } from "node:test";
import { mergeReplays } from "./match-to-replay.js";

function baseMeta(overrides = {}) {
  return {
    map_name: "bloodrun",
    gametype: "duel",
    match_start_server_time: 1000,
    recording_start_server_time: 1000,
    roster: [
      { clientNum: 0, name: "A" },
      { clientNum: 1, name: "B" },
    ],
    ...overrides,
  };
}

test("mergePickups prefers an exact entity-sourced pickup over an unsourced PVS-heuristic duplicate of the same spot", () => {
  const povReplays = [
    {
      clientNum: 0,
      replay: {
        meta: baseMeta(),
        events: [
          // POV 0 never had player 1 in view close enough to confirm the pickup
          // itself - only the PVS heuristic's own "item vanished near someone"
          // guess (no `source` field, exactly what StaticItemTracker emits).
          {
            event: "pickup",
            game_time_ms: 100,
            item: "item_armor_body",
            x: 100,
            y: 200,
            z: 300,
            action: "pickup",
            clientNum: 1,
          },
        ],
      },
    },
    {
      clientNum: 1,
      replay: {
        meta: baseMeta(),
        events: [
          // POV 1 is the picker's own demo: exact entity/ps-sourced pickup.
          {
            event: "pickup",
            game_time_ms: 100,
            item: "item_armor_body",
            x: 100,
            y: 200,
            z: 300,
            action: "pickup",
            clientNum: 1,
            source: "ps",
          },
        ],
      },
    },
  ];

  const merged = mergeReplays(povReplays);
  const pickups = merged.events.filter((e) => e.event === "pickup");
  assert.equal(pickups.length, 1, "the two observations of one physical pickup collapse into one event");
  assert.equal(pickups[0].source, "ps");
});
