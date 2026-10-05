-- Meal corrections: voiding a logged meal, changing its date/type/time, merging two meals.
--
-- nutrition_meals rows are never updated, so a meal's corrections are appended here instead:
-- a revision row carries the meal's full effective date/time and type after that edit (the
-- latest one wins), a void row takes the meal out of every day total, and a merged-item row
-- links an item copied into the target meal to the item of the (voided) source meal it came
-- from. All three tables are append-only, like nutrition_facts and item removals: a correction
-- cannot be rewritten or undone. No existing table is altered.

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS nutrition_meal_revisions (
    meal_id TEXT NOT NULL REFERENCES nutrition_meals(meal_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK (revision > 0),
    revised_at TEXT NOT NULL,
    eaten_at TEXT NOT NULL,
    -- Same normalized UTC sort key as nutrition_meals.eaten_at_utc_sort_key.
    eaten_at_utc_sort_key TEXT NOT NULL,
    meal_type TEXT NOT NULL CHECK (meal_type IN ('breakfast', 'lunch', 'dinner', 'snack', 'other')),
    PRIMARY KEY (meal_id, revision)
);

-- One void per meal (the primary key): a meal cannot be voided twice and is never unvoided.
CREATE TABLE IF NOT EXISTS nutrition_meal_voids (
    meal_id TEXT PRIMARY KEY REFERENCES nutrition_meals(meal_id) ON DELETE RESTRICT,
    voided_at TEXT NOT NULL,
    reason TEXT CHECK (reason IS NULL OR length(trim(reason)) > 0),
    -- Set when the meal was voided by `nutrition meal merge`: the meal its items were copied into.
    merged_into_meal_id TEXT REFERENCES nutrition_meals(meal_id) ON DELETE RESTRICT,
    CHECK (merged_into_meal_id IS NULL OR merged_into_meal_id <> meal_id)
);

CREATE TABLE IF NOT EXISTS nutrition_meal_merged_items (
    -- The copy in the target meal.
    meal_id TEXT NOT NULL,
    item_sequence INTEGER NOT NULL,
    -- The source item it was copied from; the source meal must be voided.
    source_meal_id TEXT NOT NULL REFERENCES nutrition_meal_voids(meal_id) ON DELETE RESTRICT,
    source_item_sequence INTEGER NOT NULL,
    PRIMARY KEY (meal_id, item_sequence),
    UNIQUE (source_meal_id, source_item_sequence),
    FOREIGN KEY (meal_id, item_sequence)
        REFERENCES nutrition_meal_items(meal_id, item_sequence) ON DELETE RESTRICT,
    FOREIGN KEY (source_meal_id, source_item_sequence)
        REFERENCES nutrition_meal_items(meal_id, item_sequence) ON DELETE RESTRICT,
    CHECK (meal_id <> source_meal_id)
);

CREATE INDEX IF NOT EXISTS nutrition_meal_merged_items_source_idx ON nutrition_meal_merged_items(source_meal_id);

CREATE TRIGGER IF NOT EXISTS nutrition_meal_revisions_prevent_update
BEFORE UPDATE ON nutrition_meal_revisions
BEGIN
    SELECT RAISE(ABORT, 'nutrition meal revisions are append-only');
END;

CREATE TRIGGER IF NOT EXISTS nutrition_meal_revisions_prevent_delete
BEFORE DELETE ON nutrition_meal_revisions
BEGIN
    SELECT RAISE(ABORT, 'nutrition meal revisions are append-only');
END;

-- A voided meal cannot be edited any more.
CREATE TRIGGER IF NOT EXISTS nutrition_meal_revisions_refuse_voided
BEFORE INSERT ON nutrition_meal_revisions
WHEN EXISTS (SELECT 1 FROM nutrition_meal_voids WHERE meal_id = NEW.meal_id)
BEGIN
    SELECT RAISE(ABORT, 'a voided meal cannot be revised');
END;

CREATE TRIGGER IF NOT EXISTS nutrition_meal_voids_prevent_update
BEFORE UPDATE ON nutrition_meal_voids
BEGIN
    SELECT RAISE(ABORT, 'nutrition meal voids are append-only');
END;

CREATE TRIGGER IF NOT EXISTS nutrition_meal_voids_prevent_delete
BEFORE DELETE ON nutrition_meal_voids
BEGIN
    SELECT RAISE(ABORT, 'nutrition meal voids are append-only');
END;

CREATE TRIGGER IF NOT EXISTS nutrition_meal_merged_items_prevent_update
BEFORE UPDATE ON nutrition_meal_merged_items
BEGIN
    SELECT RAISE(ABORT, 'nutrition meal merged items are append-only');
END;

CREATE TRIGGER IF NOT EXISTS nutrition_meal_merged_items_prevent_delete
BEFORE DELETE ON nutrition_meal_merged_items
BEGIN
    SELECT RAISE(ABORT, 'nutrition meal merged items are append-only');
END;

INSERT OR IGNORE INTO schema_migrations(version, applied_at_utc)
VALUES (9, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
