# Knowledge pack 0.5.0: data area, shared pieces, D08 and D43

This release carries the four data-area decisions agreed on 26 October 2026 and two full entries, D08 and D43. **Stockouts and lost sales are out of scope** by decision (`pack.stockouts`): D43 checks that the target is defined once and used consistently. D10, D09, D11 and D37 follow on the same pattern. Every threshold, curve, score and cap is a **placeholder** for the SME workshop.

## 1. What's in the folder

| File | Holds |
|---|---|
| `pack.yaml` | Manifest: combination rule, trigger-based gate semantics, verdict order with *Readiness not confirmed*, stockouts switch (out of scope), volume weighting, latest-period reservation for D10, minimum-data default, release tags |
| `shared/data_stage.yaml` | Data-stage tag (raw source, model-ready, unknown) and absent-row meaning (no sale, missing data, unknown): hints, Gate 1 questions, effects on scoring |
| `shared/zero_classification.yaml` | One classification of every zero run: 9 classes with owners, thresholds, outputs and limits. The two stockout classes are kept but have no owner and are never scored |
| `vocab/data_validation.yaml` | Word lists and code patterns for D08: validation tools, zero-fill and gap handling, coercion, dedupe, calendars, units, document and log terms |
| `vocab/target_definition.yaml` | Word lists and code patterns for D43: target keys, fit and evaluation calls, target-type terms, returns, cancellations, clipping, definition phrases |
| `diagnostics/D08.yaml` | Full D08 entry: boundaries, 9 condition measures, 25 control signals, scoring, templates, gap requests, review checklist |
| `diagnostics/D43.yaml` | Full D43 entry (gate): boundaries, gate policy with six triggers, 6 condition measures, 14 control signals, scoring, templates, gap requests, review checklist |
| `library/recommendations.yaml` | R-DA-01 to R-DA-08 (D08) and R-DA-10 to R-DA-15 (D43), with effort, What-if target and root cause |
| `tools/check_pack.py` | Consistency checks, including gate policies and cross-entry references (run in CI before any pack release) |
| `tools/worked_example.py`, `tools/worked_example_D43.py` | Recompute section 3 from the YAML, so the examples can't drift from the pack |

## 2. How D08 is scored

1. **Gate 1** confirms each data file's stage and, for sales history, what an absent row means.
2. **Zero classification** runs once on the target series. D08 takes only the `missing_filled_with_zero` class; the other classes go to D10, D37 and D43, or are context.
3. **Condition:** each measure is computed per table, weighted by volume, and turned into 0–100 with its curve. On a raw extract, an issue doesn't count if a `handled_by` signal was found; on a model-ready table every issue counts. The condition score is the mean of the measures, never above the lowest critical one.
4. **Control:** the scoring list gives a base score (first match) and caps (all matches). Code-based absence findings count only if the shared code actually loads or prepares data (`control_context`).
5. **Combined:** the lower of condition and control. If only one side has evidence, it scores alone and is labelled.
6. The result is **provisional** while any absence or flagged negative awaits review, or while the code isn't confirmed as the deployed version.

### 2b. How D43 is scored, and when the gate trips

Condition and control combine exactly as for D08. What's specific to D43 is the gate.

- **Only listed triggers can fail the gate** (`gate_policy`). The gate trips when D43's combined score is below the floor (40) and at least one trigger is below the floor with its requirement met:
  - the model is trained on one column and its accuracy is measured on another (confirmed automatically when the lineage traces both columns to their sources);
  - code, configs and documents name different targets (after review);
  - nobody can state the target (after the absence is confirmed);
  - the versions of the target the client shares disagree by more than about 4.5% of volume;
  - forecasts can't be matched to actuals at all;
  - forecasts and actuals look like different units (after review).
- **Everything else lowers the score but can't fail the gate:** returns, cancellations, clipping at zero, and an ambiguous target name.
- **A trigger awaiting review** holds the verdict at *Readiness not confirmed*.
- **No evidence at all** also gives *Readiness not confirmed*, never *Not ready*.

## 3. Worked example: Retailer X

200 weekly series; weeks 31–32 missing for 190 of them; 0.3% duplicate rows in the raw extract; `prep.py` de-duplicates (line 41) and zero-fills gaps with `asfreq("W").fillna(0)` (line 48). Output of `python tools/worked_example.py`:

```
A  model-ready table only            condition  70  control None  ->  D08 = 70 (controls not evidenced)
B  model-ready table + prep.py       condition  70  control   40  ->  D08 = 40
C  raw extract + prep.py             condition  70  control   40  ->  D08 = 40
D  raw extract + better pipeline     condition 100  control   80  ->  D08 = 80
```

- **A:** the classifier finds the two simultaneous zero weeks, so the gap share is 1.8% and the curve gives 70. No code was shared, so the targeted request asks for the pipeline code.
- **B and C:** the same pipeline gives the same score whichever file was shared. The cap of 40 comes from `zero_fill_hides_missing_data`.
- **D:** gaps are interpolated with an indicator and checked with pandera, so the raw-data issues are handled and the condition side is 100.

### 3b. D43 cases

Output of `python tools/worked_example_D43.py`:

```
1 Clean; 4% returns netted               cond   90  ctrl   85  D43   85   gate: passes
2 Accuracy measured on shipments         cond   24  ctrl   30  D43   24   gate: TRIPPED -> Not ready
3 20% returns, net sales clipped         cond   80  ctrl   70  D43   70   gate: passes
4 Column 'qty', nothing defines it       cond None  ctrl   65  D43   65   gate: passes (condition not measured)
5a Deck says till sales, code shipments  cond None  ctrl   35  D43   35   gate: pending review -> Readiness not confirmed
5b Same, after practitioner confirms     cond None  ctrl   35  D43   35   gate: TRIPPED -> Not ready
6 Nothing about the target shared        cond None  ctrl None  D43 None   gate: no evidence -> Readiness not confirmed
```

- **Case 2:** the model learns till-sales units but its accuracy is computed against shipments, and the two disagree on 8% of volume. Both triggers fire.
- **Case 3:** heavy returns are a finding and cost points, but they are not a gate failure.
- **Case 5:** the same evidence gives a different verdict before and after review. That is deliberate: a conflict involving a document can't fail the gate on its own.

## 4. Schema extensions to build spec §5.2

All are additive; the D12 entry stays valid.

| Where | New field | Purpose |
|---|---|---|
| Entry | `release` (v1, later) on the entry, every measure and every signal | Only v1 items need planted tests for v1 |
| Entry | `boundaries.owns` / `boundaries.leaves` | States penalise-once ownership in the entry itself |
| Entry | `combination` | Points to the pack's data-area rule |
| Entry | `control_context` | Code-based absence findings need code that actually prepares data |
| `data_route` | `tables` with weights; `table_combination` | Measures run per table and combine by weight |
| Measure | `owner`, `critical`, `curve`, `components`, `stages`, `min_data`, `handled_by`, `never_handled_by`, `outputs`, `insight`, `recommendation` | Condition side, with links to the controls that handle each issue |
| Signal | `polarity: neutral` and `polarity: context` | Detection that is neither good nor bad until a derived test decides |
| Signal | `absence: true`, `requires_context` | Absence findings stay provisional and only count where they make sense |
| Signal | `match: all` | Several detectors must all match (for example an import and a call) |
| Signal | `derived.any_of` / `derived.all_of`, `level_rule: weakest_input` | Derived tests over several inputs; level never stronger than the weakest input |
| Signal | `contradiction` | Document figure versus measured figure; measured wins |
| Entry | `gap_request.condition` / `gap_request.control` | The targeted request asks for the side that is missing |
| Entry | `gate_policy` (gate diagnostics only): `triggers` with `kind`, `requires`, `values` | The materiality trigger: only these findings can fail the gate |
| Signal | `gate_trigger: true` | Marks a signal listed in the gate policy; the checker keeps the two in step |
| Signal | `pass_when` | A threshold on the signal's own value (replaces self-referencing `derived`) |
| Measure | `score_map` with `value: category` | Categorical measures (grain and unit alignment) instead of a curve |
| Entry | `scope_exclusions`, `applies_to_forecast_types` | States what an entry deliberately doesn't cover |

## 5. Engine requirements (engine track)

- **New data_calc measures** in `scoring/measures.py`: `zero_runs`, `gap_share`, `duplicate_rows`, `conflicting_records`, `out_of_range`, `parse_errors`, `calendar_consistency`, `schema_drift`, `key_integrity` (v1); `unit_level_jumps` (later).
- **`code_call` block parameters:** method `chain`, `followed_by_lines`, `followed_by_any`, `preceded_by_any`, `args_present`, `args_absent`, `arg_absent`, `unless`, and `assert_or_raise_with`. Most data-area patterns need chains and short sequences on one variable.
- **`sql_pattern` parameters:** fill functions after a LEFT, RIGHT or FULL join to a calendar table; `ROW_NUMBER` with partition and filter; `QUALIFY`.
- **`log_stats` parameters:** share of runs with an event; failure followed by a publish event in the same run.
- **Stage handling:** inventory and review sheet carry `data_stage` and `absent_row_semantics`; with both stages shared, each series-period issue is counted once.
- **D43 measures:** `target_reconciliation`, `grain_alignment`, `unit_alignment`, `returns_share`, `cancellation_share` (v1); `definition_drift` (later).
- **Lineage:** `trace_to_column` on `code_call`, so the column passed to a fit call and the column passed to an evaluation call can each be traced to a source column and compared.
- **Gate evaluation:** implements `gate_policy` (combined score below the floor, plus a trigger below the floor with its requirement met; pending triggers give *Readiness not confirmed*).
- **Combination:** condition and control are computed separately and stored in `results.json` (`condition_score`, `control_score`, `combined_label`), so the dashboard can show why a score is low.

## 6. Planted tests (v1: Z, S and D cases for the shared steps and D08; T cases for D43)

| # | Planted case | Expected |
|---|---|---|
| Z1 | Weeks 31–32 at zero in 190 of 200 series | `missing_filled_with_zero`, owner D08 |
| Z2 | As Z1, but the event calendar has a store closure those weeks | `planned_closure`, no defect |
| Z3 | 60 leading zeros, launch date after them | `pre_launch`, owner D37, Verified |
| Z4 | 10 trailing zero weeks | `post_discontinuation`, owner D37 |
| Z5 | 3-week zero run in a steady series that recovers | `stockout_candidate`, no owner, not scored, not reported (stockouts out of scope) |
| Z6 | As Z5 with stockout flags false | `stockout_confirmed`, not scored; and not misread as `missing_filled_with_zero` |
| Z7 | Intermittent series (ADI about 3), scattered zeros | `intermittent_zero`, no defect, `zero_heavy` true |
| Z8 | Latest week at zero in every series | `partial_latest_period`, owner D10, not D08 |
| Z9 | Only 15 series | Simultaneous periods not computed; reported, not scored |
| S1 | File name matches a `to_csv` path in shared code | Hint: model-ready |
| S2 | Transaction grain with `doc_no` and `posting_date` | Hint: raw source |
| S3 | Strong hints both ways | Unknown, treated as model-ready, flagged |
| S4 | Both stages shared, same gap in each | Counted once |
| D1 | `asfreq().fillna(0)` and simultaneous gaps (regression case 4) | `zero_fill_hides_missing_data`, cap 40 |
| D2 | `resample().sum()` without `min_count`, simultaneous gaps | Same as D1 |
| D3 | `reindex(fill_value=0)`, source writes no rows for no sale, no simultaneous gaps | `zero_fill_matches_source`; no cap; gaps handled |
| D4 | Zero-fill in code, no data shared | `zero_fill_unverified`, review question, no cap |
| D5 | `to_numeric(errors="coerce").fillna(0)` (regression case 4) | `silent_coercion`, cap 50 |
| D6 | `to_numeric(errors="coerce")` then rejected rows written to file | Exempt; no cap |
| D7 | `read_csv(on_bad_lines="skip")` | `bad_lines_skipped`, cap 50 |
| D8 | `drop_duplicates()` without subset; conflicting rows in raw data | Conflicts still count (condition); no control cap |
| D9 | `sort_values` then `drop_duplicates(subset=[sku, store, week], keep="last")` | Conflicts handled |
| D10 | Negative sales with a returns column | Excluded from `out_of_range`; routed to D43 |
| D11 | Sunday and Monday week anchors in one table | `calendar_consistency` counts |
| D12 | pandera imported, never called | `validation_import_only`, 60, flagged |
| D13 | Great Expectations checkpoint; logs show checks in 95% of runs | Control 90 |
| D14 | Log: validation FAIL, then forecast published in the same run | `validation_failures_ignored`, cap 50 |
| D15 | Shared code is model training only | Control "not evidenced", not "not found" |
| D16 | dbt `schema.yml` with `not_null` and `unique` on the sales model | `schema_check_config`, 80 |
| D17 | Document says 99.5% complete; measured gaps 4% | Contradiction flagged; measured wins |
| D18 | Two extracts, one column renamed, no change record | `schema_drift` = 1, score 75 |
| D19 | 6 periods per series | `gap_share` not computed, not scored 0 |
| D20 | Gaps only in the 50 smallest series | Volume share far below count share; both reported |
| D21 | Gaps only in the latest week | D10, not D08 |
| D22 | Direction: add validation, or add zero-fill on missing data | Score never moves the wrong way |
| T1 | `model.fit(X, df["pos_units"])` and `mean_absolute_error(df["pos_units"], pred)` | `target_same_in_training_and_evaluation`; type pos_sell_out |
| T2 | Fit on `pos_units`, evaluate on `shipped_qty` | `target_mismatch_training_evaluation`, cap 30, gate trigger |
| T3 | Fit on `actual`, which lineage traces to the same source column as the evaluation column | No mismatch (renames resolve) |
| T4 | Prophet: `df.rename(columns={"net_sales": "y"})` | `target_identified`, column net_sales, net |
| T5 | Config `target: shipments_units`; deck says "we forecast till sales" | `definitions_conflict`, blocked for review; gate pending |
| T6 | Target column `qty`, no config or document defines it | `target_ambiguous`, cap 65; review question |
| T7 | Training code present, no target traceable, nothing in configs or documents | `target_undefined`, 30; gate trips only after the absence is confirmed |
| T8 | No training code, no documents | Control "not evidenced"; `target_undefined` void |
| T9 | History and archive actuals differ on 6% of volume | `target_reconciliation` about 31; gate trigger |
| T10 | History weekly (Sunday), forecasts weekly (Monday) | `grain_alignment` anchor_mismatch, 45; not a trigger |
| T11 | Forecasts at SKU-DC, history at SKU-store, no mapping | level_mismatch_unmapped, 25; gate trigger |
| T12 | Forecasts about 12 times actuals across most series | unit_mismatch_suspected, 30; blocked for review |
| T13 | 10% negative target volume with a `returns` column | `returns_share` counts (D43); excluded from D08 `out_of_range` |
| T14 | `y.clip(lower=0)` on net sales | `target_clipped_at_zero`, cap 70 |
| T15 | Orders with status column; cancelled lines filtered in SQL | `cancellations_excluded`; `cancellation_share` handled on raw data |
| T16 | Stockout flags shared | No D43 effect; stockout classes not scored or reported |

## 7. Edits needed in other materials

| Material | Edit |
|---|---|
| Build spec §4.1 | Inventory gains `data_stage` and `absent_row_semantics` |
| Build spec §4.3 | Verdict values gain *Readiness not confirmed*; each data diagnostic stores `condition_score`, `control_score`, `combined_label` |
| Build spec §5.2 | Add the schema extensions in section 4 |
| Build spec §6 | Add `zero_runs` and the new block parameters in section 5 |
| Build spec §7.2 and Framework sheet step 4.1 | For the data area, "data takes precedence" becomes "lower of condition and control" |
| Build spec §7.3 | Gate trips only on evidence of a problem; no evidence gives *Readiness not confirmed* |
| Build spec §9.3 and Gate 1 description | Review sheet gains the data-stage and absent-row questions |
| Build spec §12.2 | Regression case 4 split: zero-filled history is D08; the latest period is D10 |
| Build spec §4.4 | Optional columns: `sales_history.source` (target version), `row_type`, `status`, `returns`; `past_forecasts.actual` |
| Build spec §7.3 | Gate trips need a listed trigger (entry `gate_policy`); a trigger awaiting review gives *Readiness not confirmed* |
| Workbook, Diagnostic tools sheet | D43 "What it checks": "Checks the model is trained and judged on one clearly defined target: the same quantity, unit and grain, with the same treatment of returns and cancellations, across data, code and documents." Stockouts removed |
| Walkthrough Appendix B and talk track | Remove stockouts and lost sales from D43 |
| Deck slide 4 | Verdict list gains *Readiness not confirmed* |

If the contracts are already frozen, these go through the change log.

## 8. Placeholders for the SME workshop

- Nine D08 curves; ten control scores; five caps.
- Zero classification: the simultaneity thresholds (0.6 share, 3× median, 20 series, 0.5 of a run), discontinued run length, steady-series zero share, stockout window and recovery ratio.
- Zero-fill materiality (0.5% of volume); validation coverage in logs (90% of runs); document-versus-measured tolerance (2 points); latest-period reservation (1 period).
- Table weights in D08 (target 2, inputs 1, reference 1, calendar 0.5).
- D43: four curves, two score maps, reconciliation tolerance (1% or 1 unit), unit band (0.67–1.5) and factor tolerance (5%), unmapped share (20%), six control scores, five caps.
- **Whether D43 keeps 6 points and its gate status** now that stockouts are out (section 9).

## 9. Known limits and open points

- **Stockouts are now unmeasured anywhere in the framework.** No other diagnostic owns censored demand, so a retailer with heavy stockouts can score well on D43 while the model learns understated demand. D24 may show under-forecasting, but won't attribute it. Setting `pack.stockouts.report_observation: true` reports estimated lost sales as an unscored observation without changing any score.
- **D43 will rarely fail the gate.** Its triggers are now definition failures, which are serious but uncommon. Ask the SMEs whether D43 still earns 6 points (the most in the Data area) and a gate.
- `target_type_use_mismatch` (does the target match the decision it feeds?) is tagged *later*: it interprets documents and edges towards the business-fit question that is out of scope for v1.

- An isolated zero-filled gap in a single series can't be told from a stockout or a real zero without the raw extract or the code.
- `validation_misses_target`, `unit_level_jumps` and `unit_conversion_applied` are tagged *later*: they need more testing for false positives.
- Imputation without an indicator column counts as handled in v1. Partial credit is a later refinement.
- The evidence level of derived signals (Verified data plus Verified code gives a derived conclusion) follows `level_rule: weakest_input`. That matches spec §7.1, but it means some data-area findings will show as Inferred. Worth confirming at the workshop.

## 10. Next

D10 (freshness and completeness), using the zero class `partial_latest_period` and the log handler. Then D09, D11 and D37.
