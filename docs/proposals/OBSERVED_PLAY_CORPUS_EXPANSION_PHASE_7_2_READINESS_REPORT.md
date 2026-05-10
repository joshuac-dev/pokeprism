# Phase 7.2 Corpus Expansion Readiness Report

> Read-only corpus audit. No code changes, no ingestion, no migrations.
> Branch: `phase-7-2-corpus-expansion-readiness`
> Date: 2026-05-09
> Baseline commit: `6234d5cd` (Merge branch 'phase-7-2b-matchup-context-preview')

## Phase 7.2c Note

Phase 7.2c has implemented the generic matchup boost mechanism. The readiness gate described in
this report blocks boost ACTIVATION and BROAD ROLLOUT for under-covered pairs. For any matchup
with <3 clean directed logs, matchup_boost=0.0 and retrieval falls back to Phase 7.1d/7.2b behavior.
The readiness gate does NOT block the implementation itself.

---

## 1. Summary Verdict

**`not_ready_needs_more_logs`**

The corpus does not meet Phase 7.2c gates. Salazzle-ex and Charizard-ex each
have only 1 log. No directed cross-matchup pair reaches the minimum of 3 logs
needed for stable matchup ranking signal. Gardevoir and Crustle meet individual
label-count gates but are dominated by mirror-match logs (same archetype on both
sides), providing no cross-matchup training signal.

Phase 7.2c (matchup ranking boost) must not start until at minimum the Salazzle
gap is closed and at least one cross-matchup pair reaches 3 logs.

---

## 2. Baseline Corpus Counts

Captured 2026-05-09 before this branch. No imports were performed.

| Table | Count |
|---|---|
| observed_play_logs | 49 |
| observed_play_events | 10,047 |
| observed_card_mentions | 8,670 |
| observed_play_memory_items | 4,786 |
| observed_play_memory_ingestions | 198 |

All 49 logs: `parse_status=parsed`, `memory_status=ingested`.
Confidence scores: min 0.876, max 0.897, avg 0.888.

---

## 3. Import Candidate Discovery

Searched the following directories for staged import candidates:

```
data/observed_play/import_candidates/
data/observed_play/pending/
data/human_logs/
human_logs/
logs/observed_play/
docs/human_logs/
~/observed_play/
~/human_logs/
```

**Result: None found.** No import candidates are present locally.

No imports were performed.

---

## 4. Archetype Label Distribution

Label counts from `preview_observed_log_archetype_labels` across all 49 logs.
Counts reflect logs where the archetype appears on **either** player side.

| Archetype | Logs | Gate (≥5) | Status |
|---|---|---|---|
| dragapult-ex | 23 | ≥5 | ✅ exceeds gate |
| crustle | 12 | ≥5 | ✅ meets gate |
| gardevoir-ex | 12 | ≥5 | ✅ meets gate |
| salazzle-ex | 1 | ≥5 | ❌ critical gap |
| charizard-ex | 1 | ≥5 | ❌ critical gap |

Logs with **no archetype label on either side**: 4
- `2026-04-28 10.26.md`
- `2026-04-28 23.45.md`
- `2026-04-28 23.59.md`
- `2026-05-01 13.41.md`

Logs with **one side labeled, one missing**: 5
- `2026-04-28 23.01.md` (p1=dragapult-ex, p2=none)
- `2026-04-29 10.56.md` (p1=none, p2=dragapult-ex)
- `2026-05-01 16.18.md` (p1=dragapult-ex, p2=none)
- `2026-05-04 23.27.md` (p1=gardevoir-ex, p2=none)
- `2026-05-05 23.35.md` (p1=dragapult-ex, p2=none)

---

## 5. Per-Log Archetype Labels

| Filename | p1 archetype | p2 archetype |
|---|---|---|
| 2026-04-27 23.32.md | crustle | crustle |
| 2026-04-27 23.58.md | crustle | crustle |
| 2026-04-28 09.52.md | dragapult-ex | dragapult-ex |
| 2026-04-28 10.12.md | dragapult-ex | dragapult-ex |
| 2026-04-28 10.26.md | (none) | (none) |
| 2026-04-28 10.36.md | crustle | crustle |
| 2026-04-28 10.54.md | dragapult-ex | crustle, dragapult-ex |
| 2026-04-28 11.46.md | crustle | crustle |
| 2026-04-28 14.54.md | crustle | crustle |
| 2026-04-28 17.24.md | dragapult-ex | dragapult-ex |
| 2026-04-28 22.20.md | dragapult-ex, salazzle-ex | dragapult-ex, salazzle-ex |
| 2026-04-28 23.01.md | dragapult-ex | (none) |
| 2026-04-28 23.23.md | dragapult-ex | dragapult-ex |
| 2026-04-28 23.45.md | (none) | (none) |
| 2026-04-28 23.59.md | (none) | (none) |
| 2026-04-29 00.13.md | crustle | crustle |
| 2026-04-29 00.45.md | dragapult-ex | dragapult-ex |
| 2026-04-29 10.28.md | dragapult-ex | dragapult-ex |
| 2026-04-29 10.48.md | dragapult-ex | dragapult-ex |
| 2026-04-29 10.56.md | (none) | dragapult-ex |
| 2026-04-29 11.31.md | dragapult-ex | dragapult-ex |
| 2026-04-29 12.27.md | gardevoir-ex | gardevoir-ex |
| 2026-04-29 12.43.md | gardevoir-ex | gardevoir-ex |
| 2026-04-30 14.53.md | gardevoir-ex | gardevoir-ex |
| 2026-04-30 22.31.md | crustle | crustle |
| 2026-05-01 13.41.md | (none) | (none) |
| 2026-05-01 13.51.md | dragapult-ex | dragapult-ex |
| 2026-05-01 14.17.md | dragapult-ex | dragapult-ex |
| 2026-05-01 14.42.md | dragapult-ex | dragapult-ex |
| 2026-05-01 16.18.md | dragapult-ex | (none) |
| 2026-05-01 17.56.md | dragapult-ex | dragapult-ex |
| 2026-05-01 23.43.md | dragapult-ex | dragapult-ex |
| 2026-05-02 00.17.md | dragapult-ex | dragapult-ex |
| 2026-05-02 01.05.md | crustle | crustle |
| 2026-05-02 07.56.md | dragapult-ex | dragapult-ex |
| 2026-05-03 01.43.md | crustle | crustle |
| 2026-05-03 02.15.md | crustle | crustle |
| 2026-05-04 23.27.md | gardevoir-ex | (none) |
| 2026-05-04 23.41.md | gardevoir-ex, charizard-ex | charizard-ex, gardevoir-ex |
| 2026-05-04 23.55.md | gardevoir-ex | gardevoir-ex |
| 2026-05-05 00.05.md | gardevoir-ex | gardevoir-ex |
| 2026-05-05 00.50.md | gardevoir-ex | gardevoir-ex |
| 2026-05-05 13.09.md | gardevoir-ex | gardevoir-ex |
| 2026-05-05 13.19.md | gardevoir-ex | gardevoir-ex |
| 2026-05-05 15.45.md | dragapult-ex, gardevoir-ex | gardevoir-ex, dragapult-ex |
| 2026-05-05 20.47.md | gardevoir-ex | gardevoir-ex |
| 2026-05-05 23.10.md | crustle | crustle |
| 2026-05-05 23.24.md | dragapult-ex | dragapult-ex |
| 2026-05-05 23.35.md | dragapult-ex | (none) |

Note: `2026-04-28 10.54.md` and `2026-05-05 15.45.md` each have two archetypes
on at least one side and cannot cleanly produce a single directed primary key
for one side. These are the only ambiguous-pair logs.

---

## 6. Directed Matchup Pair Distribution

| Directed Pair | Logs | Gate (≥3 for 7.2c) | Status |
|---|---|---|---|
| dragapult-ex\|vs\|dragapult-ex | 17 | n/a (mirror) | mirror match, no cross-matchup signal |
| crustle\|vs\|crustle | 11 | n/a (mirror) | mirror match, no cross-matchup signal |
| gardevoir-ex\|vs\|gardevoir-ex | 9 | n/a (mirror) | mirror match, no cross-matchup signal |
| dragapult-ex\|vs\|crustle | 1 | ≥3 | ❌ below gate |
| gardevoir-ex\|vs\|charizard-ex | 1 | ≥3 | ❌ below gate |
| dragapult-ex\|vs\|gardevoir-ex | 1 | ≥3 | ❌ below gate |
| (incomplete — one side missing) | 9 | — | cannot form directed pair |

**Key finding:** Mirror matches (same archetype on both sides) dominate 37 of
40 fully-labeled directed-pair logs. Cross-matchup logs exist for only 3 distinct
pairs, each with exactly 1 log. No pair meets the ≥3 gate required before
Phase 7.2c matchup ranking is enabled.

The entire corpus of 49 logs contains only 3 cross-matchup logs. This is
insufficient for stable matchup-aware ranking. Matchup ranking boost in 7.2c
would be trained on near-zero cross-matchup signal.

---

## 7. Target Gate Assessment

### 7.1 Gardevoir-ex gap

- Current: 12 logs, all `gardevoir-ex|vs|gardevoir-ex` mirrors (9 paired) or
  incomplete (1 partial).
- Only 1 log with Gardevoir vs a different archetype: `dragapult-ex|vs|gardevoir-ex`.
- Gate for label count (≥5): **met**.
- Gate for cross-matchup signal: **not met** — 0 Gardevoir-vs-Dragapult
  directed pairs from the Gardevoir perspective, 1 from the Dragapult perspective.
- Needed: **5 clean Gardevoir ex logs where opponent is a different archetype**
  (e.g., Gardevoir vs Dragapult, Gardevoir vs Crustle).

### 7.2 Crustle gap

- Current: 12 logs, all `crustle|vs|crustle` mirrors (11 paired) or 1 ambiguous.
- Only 1 cross-matchup log: `dragapult-ex|vs|crustle`.
- Gate for label count (≥5): **met**.
- Gate for cross-matchup signal: **not met** — 0 Crustle-vs-Dragapult
  directed pairs from the Crustle perspective.
- Needed: **5 clean Crustle logs where opponent is a different archetype**
  (e.g., Crustle vs Dragapult, Crustle vs Gardevoir).

### 7.3 Salazzle-ex gap

- Current: 1 log, and both sides show `dragapult-ex` + `salazzle-ex` simultaneously
  (ambiguous multi-label; no clean Salazzle-only side).
- Gate for label count (≥5): **not met**.
- Cross-matchup signal: 0.
- Needed: **5 clean Salazzle ex logs** (ideally with clear single-archetype
  per side).

### 7.4 Charizard-ex gap

- Current: 1 log (`2026-05-04 23.41.md`), which shows `gardevoir-ex` +
  `charizard-ex` on both sides simultaneously (ambiguous multi-label).
- Gate for label count (≥5): **not met**.
- Cross-matchup signal: 0 clean Charizard-vs-X logs.
- Needed: **5 clean Charizard ex logs**.

### 7.5 Priority cross-matchup pair gate

- Gate: ≥3 logs for at least one directed cross-matchup pair.
- Current max: 1 log each for dragapult-ex|vs|crustle, dragapult-ex|vs|gardevoir-ex,
  gardevoir-ex|vs|charizard-ex.
- **Not met.** Priority pair: Gardevoir|vs|Dragapult or Crustle|vs|Dragapult.
- Needed: **2 more logs for any one cross-matchup pair**.

---

## 8. Player Alias Observation

All 49 logs use generic `player_1` / `player_2` aliases. No human-readable
player names are present. This is consistent with PTCG Live export format and
expected behavior. The `_source_log_matchup_metadata` helper in Phase 7.2b
correctly returns `source_log_matchup_key=None` when player-side assignment
cannot be confidently determined from generic aliases.

---

## 9. Ambiguous/Multi-Label Observations

Two logs show multiple archetypes on the same side:

- `2026-04-28 10.54.md`: p2 shows both `crustle` and `dragapult-ex`.
- `2026-04-28 22.20.md`: both sides show `dragapult-ex` and `salazzle-ex`.
- `2026-05-04 23.41.md`: both sides show `gardevoir-ex` and `charizard-ex`.
- `2026-05-05 15.45.md`: both sides show `dragapult-ex` and `gardevoir-ex`.

These ambiguous logs are not counted toward archetype-specific gates because a
single primary archetype cannot be reliably assigned per side.

---

## 10. Recommendation for Phase 7.2c

**Do not start Phase 7.2c matchup ranking boost.**

Minimum requirements before Phase 7.2c:

1. **Salazzle: 4 more clean logs** (to reach ≥5 total with unambiguous labels).
2. **Charizard: 4 more clean logs** (to reach ≥5 total with unambiguous labels).
3. **At least one cross-matchup pair with ≥3 logs.** Recommended:
   - `gardevoir-ex|vs|dragapult-ex`: need 2 more (has 1).
   - `crustle|vs|dragapult-ex`: need 3 more (has 0 from Crustle's perspective).

Optional (improves ranking signal quality before 7.2c):

4. **5 Gardevoir ex logs where opponent is a different archetype.**
5. **5 Crustle logs where opponent is a different archetype.**

Do not count mirror matches (same archetype on both sides) toward cross-matchup
gates. Do not count multi-label ambiguous logs unless the primary archetype per
side is clearly resolvable.

---

## 11. Exact Log Request for User

The following logs are needed before Phase 7.2c. Submit as `.txt` or `.md` files
containing raw PTCG Live battle log exports. One battle per file. Do not commit
raw logs. Use the existing observed-play upload/import path.

**Priority 1 (gate-blocking):**

```
- 5 clean Salazzle ex logs
  (Salazzle ex / Poison-Burn archetype; one clear archetype per side preferred)
- 2+ Gardevoir ex logs where opponent is Dragapult ex
  (target: gardevoir-ex|vs|dragapult-ex ≥ 3 logs total)
```

**Priority 2 (strongly recommended):**

```
- 5 clean Charizard ex logs
  (Charizard ex / Arcanine ex; one clear archetype per side)
- 3+ Crustle logs where opponent is Dragapult ex
  (target: crustle|vs|dragapult-ex ≥ 3 logs total)
- 3+ Gardevoir ex logs where opponent is Crustle
  (target: gardevoir-ex|vs|crustle ≥ 3 logs total)
```

**Preferred format:**

```
- raw PTCG Live battle log export as .txt or .md
- one battle per file
- filename should include archetypes if known
  (e.g., gardevoir-vs-dragapult-2026-05-10.md)
- do not manually edit card names unless correcting obvious export corruption
- include decklist markdown separately when available
```

---

## 12. Scope Confirmation

- No code changes made. ✓
- No retrieval behavior change. ✓
- No migrations. ✓
- No label or matchup persistence beyond existing ingestion tables. ✓
- No hard filtering. ✓
- No candidate-pool expansion. ✓
- No Coach/simulator/AI Player/ingestion/deck-builder changes. ✓
- No raw logs committed. ✓
- No imports performed (no candidates found). ✓
- `docs/AUDIT_STATE.md` untouched. ✓
- `frontend/node_modules` tracked count: 0. ✓
