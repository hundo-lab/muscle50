-- Meal Edit: removing an item from a logged meal.
--
-- A logged item owns snapshot nutrition facts, which are append-only and reference the item
-- with ON DELETE RESTRICT, so an item can never be deleted. Removal is recorded here instead:
-- a removed item (and its facts) stays stored for audit, and meal readers skip it. Rows are
-- append-only, like nutrition_facts, so a removal cannot be undone or rewritten.

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS nutrition_meal_item_removals (
    meal_id TEXT NOT NULL,
    item_sequence INTEGER NOT NULL,
    removed_at TEXT NOT NULL,
    -- The item added in the same transaction to take this one's place (`meal replace-item`).
    replaced_by_item_sequence INTEGER,
    PRIMARY KEY (meal_id, item_sequence),
    FOREIGN KEY (meal_id, item_sequence)
        REFERENCES nutrition_meal_items(meal_id, item_sequence) ON DELETE RESTRICT,
    FOREIGN KEY (meal_id, replaced_by_item_sequence)
        REFERENCES nutrition_meal_items(meal_id, item_sequence) ON DELETE RESTRICT,
    CHECK (replaced_by_item_sequence IS NULL OR replaced_by_item_sequence <> item_sequence)
);

CREATE TRIGGER IF NOT EXISTS nutrition_meal_item_removals_prevent_update
BEFORE UPDATE ON nutrition_meal_item_removals
BEGIN
    SELECT RAISE(ABORT, 'nutrition meal item removals are append-only');
END;

CREATE TRIGGER IF NOT EXISTS nutrition_meal_item_removals_prevent_delete
BEFORE DELETE ON nutrition_meal_item_removals
BEGIN
    SELECT RAISE(ABORT, 'nutrition meal item removals are append-only');
END;

INSERT OR IGNORE INTO schema_migrations(version, applied_at_utc)
VALUES (8, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
