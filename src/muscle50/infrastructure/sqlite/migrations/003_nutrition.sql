-- Nutrition Core persistence schema.

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS nutrition_meals (
    meal_id TEXT PRIMARY KEY,
    eaten_at TEXT NOT NULL,
    -- Normalized UTC sort key (fixed-width, always includes microseconds) so range
    -- queries and ordering are correct regardless of the offset eaten_at was recorded in.
    -- eaten_at itself keeps the original aware datetime text verbatim for exact round-trip.
    eaten_at_utc_sort_key TEXT NOT NULL,
    meal_type TEXT NOT NULL CHECK (meal_type IN ('breakfast', 'lunch', 'dinner', 'snack', 'other')),
    original_text TEXT NOT NULL CHECK (length(trim(original_text)) > 0),
    parser_version TEXT,
    model_version TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS nutrition_meal_items (
    meal_id TEXT NOT NULL REFERENCES nutrition_meals(meal_id) ON DELETE CASCADE,
    item_sequence INTEGER NOT NULL CHECK (item_sequence > 0),
    food_name TEXT NOT NULL CHECK (length(trim(food_name)) > 0),
    food_profile_id TEXT REFERENCES nutrition_food_profiles(profile_id),
    quantity TEXT,
    quantity_unit TEXT CHECK (quantity_unit IN ('g', 'ml', 'count', 'pack', 'piece', 'animal', 'serving')),
    serving_description TEXT,
    CHECK ((quantity IS NULL) = (quantity_unit IS NULL)),
    PRIMARY KEY (meal_id, item_sequence)
);

CREATE TABLE IF NOT EXISTS nutrition_food_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0)
);

CREATE TABLE IF NOT EXISTS nutrition_food_profile_aliases (
    profile_id TEXT NOT NULL REFERENCES nutrition_food_profiles(profile_id) ON DELETE CASCADE,
    alias TEXT NOT NULL CHECK (length(trim(alias)) > 0),
    PRIMARY KEY (profile_id, alias)
);

-- Facts are append-only. A fact belongs either to a consumed item or to a reusable profile.
-- Decimal values are stored as canonical text so binary floating-point cannot change results.
CREATE TABLE IF NOT EXISTS nutrition_facts (
    fact_id TEXT PRIMARY KEY,
    meal_id TEXT,
    item_sequence INTEGER,
    profile_id TEXT REFERENCES nutrition_food_profiles(profile_id) ON DELETE RESTRICT,
    calories_kcal TEXT,
    protein_g TEXT,
    carbohydrate_g TEXT,
    fat_g TEXT,
    min_calories_kcal TEXT,
    max_calories_kcal TEXT,
    min_protein_g TEXT,
    max_protein_g TEXT,
    min_carbohydrate_g TEXT,
    max_carbohydrate_g TEXT,
    min_fat_g TEXT,
    max_fat_g TEXT,
    basis_quantity TEXT NOT NULL,
    basis_unit TEXT NOT NULL CHECK (basis_unit IN ('g', 'ml', 'count', 'pack', 'piece', 'animal', 'serving')),
    source_type TEXT NOT NULL CHECK (source_type IN (
        'nutrition_label', 'user_provided', 'known_product', 'food_database',
        'visual_estimate', 'language_estimate'
    )),
    source_reference TEXT NOT NULL CHECK (length(trim(source_reference)) > 0),
    confidence TEXT,
    accuracy TEXT NOT NULL CHECK (accuracy IN ('exact', 'estimated')),
    parser_version TEXT,
    model_version TEXT,
    created_at TEXT NOT NULL,
    supersedes_fact_id TEXT REFERENCES nutrition_facts(fact_id),
    FOREIGN KEY (meal_id, item_sequence)
        REFERENCES nutrition_meal_items(meal_id, item_sequence) ON DELETE RESTRICT,
    CHECK (
        (profile_id IS NOT NULL AND meal_id IS NULL AND item_sequence IS NULL)
        OR (profile_id IS NULL AND meal_id IS NOT NULL AND item_sequence IS NOT NULL)
    ),
    CHECK ((min_calories_kcal IS NULL) = (max_calories_kcal IS NULL)),
    CHECK ((min_protein_g IS NULL) = (max_protein_g IS NULL)),
    CHECK ((min_carbohydrate_g IS NULL) = (max_carbohydrate_g IS NULL)),
    CHECK ((min_fat_g IS NULL) = (max_fat_g IS NULL)),
    CHECK (
        calories_kcal IS NOT NULL OR protein_g IS NOT NULL
        OR carbohydrate_g IS NOT NULL OR fat_g IS NOT NULL
        OR min_calories_kcal IS NOT NULL OR min_protein_g IS NOT NULL
        OR min_carbohydrate_g IS NOT NULL OR min_fat_g IS NOT NULL
    ),
    CHECK (
        accuracy = 'estimated'
        OR (
            min_calories_kcal IS NULL AND min_protein_g IS NULL
            AND min_carbohydrate_g IS NULL AND min_fat_g IS NULL
        )
    ),
    CHECK (source_type NOT IN ('visual_estimate', 'language_estimate') OR accuracy = 'estimated'),
    CHECK (supersedes_fact_id IS NULL OR supersedes_fact_id <> fact_id)
);

CREATE INDEX IF NOT EXISTS nutrition_meals_eaten_at_utc_sort_key_idx ON nutrition_meals(eaten_at_utc_sort_key);
CREATE INDEX IF NOT EXISTS nutrition_facts_item_idx ON nutrition_facts(meal_id, item_sequence, created_at);
CREATE INDEX IF NOT EXISTS nutrition_facts_profile_idx ON nutrition_facts(profile_id, created_at);

-- Corrections must be inserts. This also makes cycles impossible because a new
-- fact can only point to an already-existing fact and existing rows cannot change.
CREATE TRIGGER IF NOT EXISTS nutrition_facts_prevent_update
BEFORE UPDATE ON nutrition_facts
BEGIN
    SELECT RAISE(ABORT, 'nutrition facts are append-only');
END;

CREATE TRIGGER IF NOT EXISTS nutrition_facts_prevent_delete
BEFORE DELETE ON nutrition_facts
BEGIN
    SELECT RAISE(ABORT, 'nutrition facts are append-only');
END;

CREATE TRIGGER IF NOT EXISTS nutrition_facts_validate_supersession
BEFORE INSERT ON nutrition_facts
WHEN NEW.supersedes_fact_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM nutrition_facts AS previous
        WHERE previous.fact_id = NEW.supersedes_fact_id
          AND previous.meal_id IS NEW.meal_id
          AND previous.item_sequence IS NEW.item_sequence
          AND previous.profile_id IS NEW.profile_id
          AND previous.basis_unit = NEW.basis_unit
    ) THEN RAISE(ABORT, 'superseded fact must have the same owner and basis unit') END;
END;

-- Canonical Decimal text, positivity, confidence bounds, and point-within-range
-- validation remain repository/domain responsibilities. SQLite REAL casts would
-- lose precision and therefore must not be used to pretend to enforce them here.

INSERT OR IGNORE INTO schema_migrations(version, applied_at_utc)
VALUES (3, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
