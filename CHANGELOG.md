# Changelog

## 0.5.0 — data area

The knowledge pack now scores D08 and D43 from the lower of the measured condition and the evidenced controls. A gate trips only when a listed trigger is active and its review requirement is met. A trigger that is still awaiting review produces the verdict **Readiness not confirmed**.

Inventory records for data files can carry `data_stage`, `data_stage_hints`, `absent_row_semantics` and `absent_row_basis`. Until a Gate 1 decision is imported, the engine uses the pack default (`model_ready`, flagged; absent rows `unknown`) and does not apply a proposed hint.

Evidence from `data_calc` carries `values.data_stage`. Review status `blocked_for_gate` counts toward the score and cannot meet a gate trigger until it is confirmed. Stockout zero classes are written only as context while `pack.stockouts.in_scope` is false, and they are not scored.

### Questions for the pack owner

- `pack.yaml` lists D14 and D34 as gates, but this pack does not include those entries. The engine ignores a gate id that has no entry, so a run is not held as "Readiness not confirmed" for a diagnostic that was not shipped. Confirm that this is the intended reading.
- Both vocabulary files declare a top-level `version`. That key is file metadata, so the loader does not treat it as a duplicate term. Confirm no other key is shared on purpose.
- The brief asks for half-up rounding. The worked-example scripts use Python's `round` (half to even). D43 case 2 lands on a half: half-up scores 25 and the script scores 24. The engine follows the script so the published golden value stays 24. Confirm which rounding the pack owner wants.
- `unit_level_jumps` and `definition_drift` are `release: later`. They load and return `not_implemented`. They do not affect the score.
