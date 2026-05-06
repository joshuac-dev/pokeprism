#!/usr/bin/env bash
# reset_observed_play_data.sh
#
# Safe local maintenance script: clears all Observed Play development/test data
# so a clean corpus of real battle logs can be uploaded.
#
# ONLY truncates observed-play tables and clears the observed-play archive.
# Does NOT touch cards, card_performance, matches, match_events, simulator,
# Coach/AI, Neo4j, pgvector, audit state, deck data, or any other tables.
#
# Usage:
#   ./scripts/reset_observed_play_data.sh --yes
#
set -euo pipefail

CONFIRM_FLAG="${1:-}"
if [[ "$CONFIRM_FLAG" != "--yes" ]]; then
  echo ""
  echo "ERROR: This script will permanently delete all Observed Play data."
  echo "       Run with --yes to confirm:"
  echo ""
  echo "         ./scripts/reset_observed_play_data.sh --yes"
  echo ""
  exit 1
fi

echo ""
echo "========================================================"
echo " Observed Play Data Reset"
echo "========================================================"
echo ""
echo "Tables to truncate (RESTART IDENTITY CASCADE):"
echo "  observed_play_memory_items"
echo "  observed_play_memory_ingestions"
echo "  observed_card_mentions"
echo "  observed_card_resolution_rules"
echo "  observed_play_events"
echo "  observed_play_logs"
echo "  observed_play_import_batches"
echo ""
echo "Archive paths to clear:"
echo "  /data/ptcgl_logs/archive/*"
echo "  /data/ptcgl_logs/inbox/*"
echo "  /data/ptcgl_logs/tmp/*"
echo "  /data/ptcgl_logs/failed/*"
echo ""

# ── 1. Verify tables exist ────────────────────────────────────────────────────
echo "Step 1: Verifying tables exist..."
TABLES_FOUND=$(docker compose exec -T postgres psql -U pokeprism -d pokeprism -tAc "
SELECT string_agg(tablename, ',' ORDER BY tablename)
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN (
    'observed_play_memory_items',
    'observed_play_memory_ingestions',
    'observed_card_mentions',
    'observed_card_resolution_rules',
    'observed_play_events',
    'observed_play_logs',
    'observed_play_import_batches'
  );
")
echo "  Found: $TABLES_FOUND"
EXPECTED_COUNT=7
ACTUAL_COUNT=$(echo "$TABLES_FOUND" | tr ',' '\n' | grep -c '.')
if [[ "$ACTUAL_COUNT" -ne "$EXPECTED_COUNT" ]]; then
  echo "ERROR: Expected $EXPECTED_COUNT tables but found $ACTUAL_COUNT. Aborting."
  exit 1
fi
echo "  All 7 tables confirmed."
echo ""

# ── 2. Pre-reset counts ───────────────────────────────────────────────────────
echo "Step 2: Pre-reset row counts..."
docker compose exec -T postgres psql -U pokeprism -d pokeprism -c "
SELECT 'observed_play_import_batches' AS table_name, count(*) FROM observed_play_import_batches
UNION ALL SELECT 'observed_play_logs', count(*) FROM observed_play_logs
UNION ALL SELECT 'observed_play_events', count(*) FROM observed_play_events
UNION ALL SELECT 'observed_card_mentions', count(*) FROM observed_card_mentions
UNION ALL SELECT 'observed_card_resolution_rules', count(*) FROM observed_card_resolution_rules
UNION ALL SELECT 'observed_play_memory_ingestions', count(*) FROM observed_play_memory_ingestions
UNION ALL SELECT 'observed_play_memory_items', count(*) FROM observed_play_memory_items
ORDER BY table_name;
"
echo ""

# ── 3. Truncate tables ────────────────────────────────────────────────────────
echo "Step 3: Truncating observed-play tables..."
docker compose exec -T postgres psql -U pokeprism -d pokeprism -c "
TRUNCATE TABLE
  observed_play_memory_items,
  observed_play_memory_ingestions,
  observed_card_mentions,
  observed_card_resolution_rules,
  observed_play_events,
  observed_play_logs,
  observed_play_import_batches
RESTART IDENTITY CASCADE;
"
echo "  Truncate complete."
echo ""

# ── 4. Clear archive/inbox/tmp/failed ────────────────────────────────────────
echo "Step 4: Clearing observed-play archive and upload staging directories..."
docker compose exec -T backend sh -lc '
for dir in /data/ptcgl_logs/archive /data/ptcgl_logs/inbox /data/ptcgl_logs/tmp /data/ptcgl_logs/failed; do
  if [ -d "$dir" ]; then
    count=$(find "$dir" -mindepth 1 -maxdepth 4 -type f | wc -l)
    echo "  Clearing $dir ($count files)..."
    find "$dir" -mindepth 1 -delete
    echo "  Done."
  else
    echo "  $dir does not exist, skipping."
  fi
done
'
echo ""

# ── 5. Post-reset counts ──────────────────────────────────────────────────────
echo "Step 5: Post-reset row counts (all should be 0)..."
docker compose exec -T postgres psql -U pokeprism -d pokeprism -c "
SELECT 'observed_play_import_batches' AS table_name, count(*) FROM observed_play_import_batches
UNION ALL SELECT 'observed_play_logs', count(*) FROM observed_play_logs
UNION ALL SELECT 'observed_play_events', count(*) FROM observed_play_events
UNION ALL SELECT 'observed_card_mentions', count(*) FROM observed_card_mentions
UNION ALL SELECT 'observed_card_resolution_rules', count(*) FROM observed_card_resolution_rules
UNION ALL SELECT 'observed_play_memory_ingestions', count(*) FROM observed_play_memory_ingestions
UNION ALL SELECT 'observed_play_memory_items', count(*) FROM observed_play_memory_items
ORDER BY table_name;
"

echo ""
echo "Step 6: Remaining files under /data/ptcgl_logs..."
docker compose exec -T backend sh -lc 'find /data/ptcgl_logs -type f | sort'
echo "  (should be empty)"
echo ""

echo "========================================================"
echo " Reset complete. All Observed Play data cleared."
echo " You can now upload real battle logs."
echo "========================================================"
echo ""
