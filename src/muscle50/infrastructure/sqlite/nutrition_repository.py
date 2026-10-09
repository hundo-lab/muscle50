"""SQLite-backed MealRepository and FoodNutritionRepository implementations."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from muscle50.domain.meal_history import MealHistory, MealMerge, MealRevision, MealVoid, MergedItem
from muscle50.domain.nutrition import (
    GENERAL_MEAL_FOOD_ID,
    GENERAL_MEAL_NAME,
    Accuracy,
    FoodNutritionProfile,
    Meal,
    MealItem,
    MealType,
    NutrientField,
    NutritionFact,
    NutritionProvenance,
    NutritionRange,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
)
from muscle50.infrastructure.decimal_text import decimal_from_text, decimal_to_text
from muscle50.infrastructure.sqlite.database import ActivityRepository

_FACT_INSERT_SQL = """
INSERT INTO nutrition_facts (
    fact_id, meal_id, item_sequence, profile_id,
    calories_kcal, protein_g, carbohydrate_g, fat_g,
    min_calories_kcal, max_calories_kcal,
    min_protein_g, max_protein_g,
    min_carbohydrate_g, max_carbohydrate_g,
    min_fat_g, max_fat_g,
    basis_quantity, basis_unit,
    source_type, source_reference, confidence, accuracy,
    parser_version, model_version, created_at, supersedes_fact_id
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class SqliteMealRepository:
    """SQLite-backed MealRepository.

    ``save`` only creates a brand-new meal: calling it again with an already
    persisted ``meal_id`` is rejected rather than attempting to reconcile item
    or fact state, because nutrition_facts rows must never be mutated or
    dropped. Use ``append_nutrition_fact`` to add facts to a saved meal.

    Items of a saved meal are edited with ``add_items``, ``remove_item`` and ``replace_item``,
    each one ``BEGIN IMMEDIATE`` transaction. A removed item is never deleted (its facts are
    append-only and restrict deletion): a row in nutrition_meal_item_removals hides it from
    every meal read, and its sequence number is never reused.

    A whole meal is corrected with ``void_meal``, ``revise_meal`` and ``merge_meals`` (migration 9),
    again by appending rows only: a voided meal drops out of ``list_eaten_between`` but ``get``
    still returns it, and ``get``/listing use the latest revision's date/time and type.

    Any item's ``food_profile_id`` must already exist in nutrition_food_profiles
    (insert the profile via SqliteFoodNutritionRepository first); otherwise
    ``save`` raises a raw ``sqlite3.IntegrityError`` from the foreign key. The one exception
    is a general meal item (``MealItem.is_general``): every write that inserts one also inserts
    the reserved ``general-meal`` profile (no facts, no aliases) with ``INSERT OR IGNORE`` in the
    same transaction, and refuses with ``ValueError`` when that ID holds anything else.
    """

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def migrate(self) -> None:
        ActivityRepository(self._database_path).migrate()

    def save(self, meal: Meal) -> None:
        with _connect(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM nutrition_meals WHERE meal_id = ?", (meal.meal_id,)
            ).fetchone()
            if existing is not None:
                raise ValueError(f"meal {meal.meal_id!r} already exists; use append_nutrition_fact to add facts")
            connection.execute(
                """
                INSERT INTO nutrition_meals (
                    meal_id, eaten_at, eaten_at_utc_sort_key, meal_type, original_text,
                    parser_version, model_version, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    meal.meal_id,
                    meal.eaten_at.isoformat(),
                    _utc_sort_key(meal.eaten_at),
                    meal.meal_type.value,
                    meal.original_text,
                    meal.parser_version,
                    meal.model_version,
                    meal.notes,
                ),
            )
            for item in meal.items:
                _insert_item(connection, item)

    def get(self, meal_id: str) -> Meal | None:
        with _connect(self._database_path) as connection:
            return _load_meal(connection, meal_id)

    def list_eaten_between(self, start_inclusive: datetime, end_exclusive: datetime) -> tuple[Meal, ...]:
        _require_aware(start_inclusive, "start_inclusive")
        _require_aware(end_exclusive, "end_exclusive")
        start_key = _utc_sort_key(start_inclusive)
        end_key = _utc_sort_key(end_exclusive)
        with _connect(self._database_path) as connection:
            meal_ids = _meal_ids_eaten_between(connection, start_key, end_key)
            meals: list[Meal] = []
            for meal_id in meal_ids:
                meal = _load_meal(connection, meal_id)
                if meal is None:
                    raise RuntimeError(f"meal {meal_id!r} disappeared during listing")
                meals.append(meal)
        return tuple(meals)

    def append_nutrition_fact(self, meal_id: str, item_sequence: int, fact: NutritionFact) -> Meal:
        with _connect(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_not_voided(connection, meal_id)
            item_row = connection.execute(
                "SELECT 1 FROM nutrition_meal_items WHERE meal_id = ? AND item_sequence = ?",
                (meal_id, item_sequence),
            ).fetchone()
            if item_row is None or item_sequence in _removed_sequences(connection, meal_id):
                raise ValueError(f"no meal item {meal_id!r}/{item_sequence} to attach a nutrition fact to")
            connection.execute(
                _FACT_INSERT_SQL,
                _fact_insert_row(fact, meal_id=meal_id, item_sequence=item_sequence, profile_id=None),
            )
            meal = _load_meal(connection, meal_id)
        if meal is None:
            raise RuntimeError(f"meal {meal_id!r} disappeared after appending a nutrition fact")
        return meal

    def next_item_sequence(self, meal_id: str) -> int:
        """The sequence the next added item gets: removed items keep their numbers, so they count."""
        with _connect(self._database_path) as connection:
            return _next_item_sequence(connection, meal_id)

    def add_items(self, meal_id: str, items: tuple[MealItem, ...]) -> Meal:
        """Add items to a saved meal; their sequences must continue from ``next_item_sequence``."""
        with _connect(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_meal(connection, meal_id)
            _insert_new_items(connection, meal_id, items)
            return _reload_meal(connection, meal_id)

    def remove_item(self, meal_id: str, item_sequence: int, removed_at: datetime) -> Meal:
        """Hide one item; refused when it is the meal's last item (a meal is never left empty)."""
        _require_aware(removed_at, "removed_at")
        with _connect(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_meal(connection, meal_id)
            _require_active_item(connection, meal_id, item_sequence)
            if len(_active_sequences(connection, meal_id)) == 1:
                raise ValueError(
                    f"item {item_sequence} is the only item of meal {meal_id!r}; a meal cannot be left empty"
                )
            _insert_removal(connection, meal_id, item_sequence, removed_at, replaced_by=None)
            return _reload_meal(connection, meal_id)

    def replace_item(self, meal_id: str, item_sequence: int, item: MealItem, removed_at: datetime) -> Meal:
        """Add ``item`` and hide ``item_sequence`` in one transaction: both happen or neither."""
        _require_aware(removed_at, "removed_at")
        with _connect(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_meal(connection, meal_id)
            _require_active_item(connection, meal_id, item_sequence)
            _insert_new_items(connection, meal_id, (item,))
            _insert_removal(connection, meal_id, item_sequence, removed_at, replaced_by=item.sequence)
            return _reload_meal(connection, meal_id)

    def history(self, meal_id: str) -> MealHistory | None:
        """The meal's corrections (revisions, void, merges into it); None when there is no such meal."""
        with _connect(self._database_path) as connection:
            return _load_history(connection, meal_id)

    def void_meal(self, meal_id: str, voided_at: datetime, reason: str | None) -> None:
        """Take a meal out of every day total; it stays stored and readable with ``get``."""
        _require_aware(voided_at, "voided_at")
        with _connect(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_meal(connection, meal_id)
            _insert_void(connection, meal_id, voided_at, reason, merged_into=None)

    def revise_meal(self, meal_id: str, revision: MealRevision) -> Meal:
        """Append the meal's new effective date/time and type; it must be the next revision number."""
        _require_aware(revision.revised_at, "revised_at")
        _require_aware(revision.eaten_at, "eaten_at")
        with _connect(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_meal(connection, meal_id)
            latest = connection.execute(
                "SELECT MAX(revision) FROM nutrition_meal_revisions WHERE meal_id = ?", (meal_id,)
            ).fetchone()[0]
            expected = int(latest or 0) + 1
            if revision.revision != expected:
                raise ValueError(f"meal {meal_id!r} changed while editing (expected revision {expected})")
            connection.execute(
                """
                INSERT INTO nutrition_meal_revisions (
                    meal_id, revision, revised_at, eaten_at, eaten_at_utc_sort_key, meal_type
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    meal_id,
                    revision.revision,
                    revision.revised_at.isoformat(),
                    revision.eaten_at.isoformat(),
                    _utc_sort_key(revision.eaten_at),
                    revision.meal_type.value,
                ),
            )
            return _reload_meal(connection, meal_id)

    def merge_meals(
        self,
        target_meal_id: str,
        source_meal_id: str,
        items: tuple[MealItem, ...],
        source_sequences: tuple[int, ...],
        merged_at: datetime,
    ) -> Meal:
        """Add copies of the source's items to the target and void the source, in one transaction.

        ``items[i]`` is the copy of source item ``source_sequences[i]``; the source sequences must be
        exactly the source's active items, and the copies must continue the target's item numbers.
        """
        _require_aware(merged_at, "merged_at")
        if target_meal_id == source_meal_id:
            raise ValueError(f"cannot merge meal {target_meal_id!r} into itself")
        if len(items) != len(source_sequences):
            raise ValueError("every merged item needs the source item it was copied from")
        with _connect(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_meal(connection, target_meal_id)
            _require_meal(connection, source_meal_id)
            if _active_sequences(connection, source_meal_id) != tuple(source_sequences):
                raise ValueError(f"meal {source_meal_id!r} changed while merging")
            _insert_new_items(connection, target_meal_id, items)
            # The mapping rows reference the source's void row, so it comes first.
            _insert_void(connection, source_meal_id, merged_at, None, merged_into=target_meal_id)
            for item, source_sequence in zip(items, source_sequences, strict=True):
                connection.execute(
                    """
                    INSERT INTO nutrition_meal_merged_items (
                        meal_id, item_sequence, source_meal_id, source_item_sequence
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (target_meal_id, item.sequence, source_meal_id, source_sequence),
                )
            return _reload_meal(connection, target_meal_id)


class SqliteFoodNutritionRepository:
    """SQLite-backed FoodNutritionRepository.

    ``save`` only creates a brand-new profile: calling it again with an
    already persisted ``profile_id`` is rejected for the same append-only
    reasons as ``SqliteMealRepository.save``. Use ``append_nutrition_fact``
    to add facts to a saved profile.
    """

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def migrate(self) -> None:
        ActivityRepository(self._database_path).migrate()

    def save(self, profile: FoodNutritionProfile) -> None:
        with _connect(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM nutrition_food_profiles WHERE profile_id = ?", (profile.profile_id,)
            ).fetchone()
            if existing is not None:
                raise ValueError(
                    f"food profile {profile.profile_id!r} already exists; use append_nutrition_fact to add facts"
                )
            connection.execute(
                "INSERT INTO nutrition_food_profiles (profile_id, name) VALUES (?, ?)",
                (profile.profile_id, profile.name),
            )
            for alias in profile.aliases:
                connection.execute(
                    "INSERT INTO nutrition_food_profile_aliases (profile_id, alias) VALUES (?, ?)",
                    (profile.profile_id, alias),
                )
            _insert_facts_in_dependency_order(
                connection, profile.facts, meal_id=None, item_sequence=None, profile_id=profile.profile_id
            )

    def get(self, profile_id: str) -> FoodNutritionProfile | None:
        with _connect(self._database_path) as connection:
            return _load_profile(connection, profile_id)

    def search(self, name_or_alias: str) -> tuple[FoodNutritionProfile, ...]:
        """Case-insensitive exact match against the profile name or any of its aliases."""
        with _connect(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT p.profile_id FROM nutrition_food_profiles p
                LEFT JOIN nutrition_food_profile_aliases a ON a.profile_id = p.profile_id
                WHERE LOWER(p.name) = LOWER(?) OR LOWER(a.alias) = LOWER(?)
                ORDER BY p.profile_id
                """,
                (name_or_alias, name_or_alias),
            ).fetchall()
            profiles: list[FoodNutritionProfile] = []
            for row in rows:
                profile = _load_profile(connection, row["profile_id"])
                if profile is None:
                    raise RuntimeError(f"food profile {row['profile_id']!r} disappeared during search")
                profiles.append(profile)
        return tuple(profiles)

    def list_all(self) -> tuple[FoodNutritionProfile, ...]:
        """Every profile, ordered by profile_id."""
        with _connect(self._database_path) as connection:
            rows = connection.execute("SELECT profile_id FROM nutrition_food_profiles ORDER BY profile_id").fetchall()
            profiles: list[FoodNutritionProfile] = []
            for row in rows:
                profile = _load_profile(connection, row["profile_id"])
                if profile is None:
                    raise RuntimeError(f"food profile {row['profile_id']!r} disappeared during listing")
                profiles.append(profile)
        return tuple(profiles)

    def append_nutrition_fact(self, profile_id: str, fact: NutritionFact) -> FoodNutritionProfile:
        with _connect(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM nutrition_food_profiles WHERE profile_id = ?", (profile_id,)
            ).fetchone()
            if existing is None:
                raise ValueError(f"no food profile {profile_id!r} to attach a nutrition fact to")
            connection.execute(
                _FACT_INSERT_SQL,
                _fact_insert_row(fact, meal_id=None, item_sequence=None, profile_id=profile_id),
            )
            profile = _load_profile(connection, profile_id)
        if profile is None:
            raise RuntimeError(f"food profile {profile_id!r} disappeared after appending a nutrition fact")
        return profile


def _load_meal(connection: sqlite3.Connection, meal_id: str) -> Meal | None:
    meal_row = connection.execute("SELECT * FROM nutrition_meals WHERE meal_id = ?", (meal_id,)).fetchone()
    if meal_row is None:
        return None
    # Removed items stay stored for audit but are no longer part of the meal.
    removed = _removed_sequences(connection, meal_id)
    item_rows = [
        row
        for row in connection.execute(
            "SELECT * FROM nutrition_meal_items WHERE meal_id = ? ORDER BY item_sequence", (meal_id,)
        ).fetchall()
        if row["item_sequence"] not in removed
    ]
    fact_rows = [
        row
        for row in connection.execute(
            "SELECT * FROM nutrition_facts WHERE meal_id = ? ORDER BY item_sequence",
            (meal_id,),
        ).fetchall()
        if row["item_sequence"] not in removed
    ]
    facts_by_item: dict[int, list[NutritionFact]] = {}
    for fact_row in fact_rows:
        facts_by_item.setdefault(fact_row["item_sequence"], []).append(_fact_from_row(fact_row))
    # created_at is stored as ISO text with its original offset; sorting it as SQL text would
    # be wrong across differing offsets (the same trap eaten_at_utc_sort_key exists to avoid).
    # Sort the reconstructed aware datetimes instead, once the row count per item is tiny.
    for facts in facts_by_item.values():
        facts.sort(key=lambda fact: (fact.provenance.created_at, fact.fact_id))
    items = tuple(
        _item_from_row(item_row, tuple(facts_by_item.get(item_row["item_sequence"], ())))
        for item_row in item_rows
    )
    # `nutrition meal edit` appends revisions instead of updating the meal row; the latest one
    # holds the effective date/time and type. A database before migration 9 has none.
    eaten_at, meal_type = meal_row["eaten_at"], meal_row["meal_type"]
    if _has_table(connection, "nutrition_meal_revisions"):
        revision = connection.execute(
            "SELECT eaten_at, meal_type FROM nutrition_meal_revisions WHERE meal_id = ? ORDER BY revision DESC LIMIT 1",
            (meal_id,),
        ).fetchone()
        if revision is not None:
            eaten_at, meal_type = revision["eaten_at"], revision["meal_type"]
    return Meal(
        meal_id=meal_row["meal_id"],
        eaten_at=datetime.fromisoformat(eaten_at),
        meal_type=MealType(meal_type),
        original_text=meal_row["original_text"],
        parser_version=meal_row["parser_version"],
        model_version=meal_row["model_version"],
        notes=meal_row["notes"],
        items=items,
    )


def _removed_sequences(connection: sqlite3.Connection, meal_id: str) -> frozenset[int]:
    # The read-only reader never migrates, so a database not yet at migration 8 has no
    # removals table; it can have no removed items either.
    has_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'nutrition_meal_item_removals'"
    ).fetchone()
    if has_table is None:
        return frozenset()
    rows = connection.execute(
        "SELECT item_sequence FROM nutrition_meal_item_removals WHERE meal_id = ?", (meal_id,)
    ).fetchall()
    return frozenset(row["item_sequence"] for row in rows)


def _active_sequences(connection: sqlite3.Connection, meal_id: str) -> tuple[int, ...]:
    removed = _removed_sequences(connection, meal_id)
    rows = connection.execute(
        "SELECT item_sequence FROM nutrition_meal_items WHERE meal_id = ? ORDER BY item_sequence", (meal_id,)
    ).fetchall()
    return tuple(row["item_sequence"] for row in rows if row["item_sequence"] not in removed)


def _next_item_sequence(connection: sqlite3.Connection, meal_id: str) -> int:
    row = connection.execute(
        "SELECT MAX(item_sequence) FROM nutrition_meal_items WHERE meal_id = ?", (meal_id,)
    ).fetchone()
    return int(row[0] or 0) + 1


def _require_meal(connection: sqlite3.Connection, meal_id: str) -> None:
    if connection.execute("SELECT 1 FROM nutrition_meals WHERE meal_id = ?", (meal_id,)).fetchone() is None:
        raise ValueError(f"no meal with id {meal_id!r}")
    _require_not_voided(connection, meal_id)


def _require_not_voided(connection: sqlite3.Connection, meal_id: str) -> None:
    if _has_table(connection, "nutrition_meal_voids") and connection.execute(
        "SELECT 1 FROM nutrition_meal_voids WHERE meal_id = ?", (meal_id,)
    ).fetchone() is not None:
        raise ValueError(f"meal {meal_id!r} is voided; a voided meal cannot be changed")


def _has_table(connection: sqlite3.Connection, name: str) -> bool:
    # Read-only readers never migrate, so tables of later migrations may be missing.
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


def _meal_ids_eaten_between(connection: sqlite3.Connection, start_key: str, end_key: str) -> list[str]:
    """Meals whose effective time is in [start, end), ordered by it; voided meals are left out.

    A database before migration 9 has no revisions or voids and is listed exactly as before.
    """
    has_revisions = _has_table(connection, "nutrition_meal_revisions")
    has_voids = _has_table(connection, "nutrition_meal_voids")
    if not has_revisions and not has_voids:
        rows = connection.execute(
            """
            SELECT meal_id FROM nutrition_meals
            WHERE eaten_at_utc_sort_key >= ? AND eaten_at_utc_sort_key < ?
            ORDER BY eaten_at_utc_sort_key, meal_id
            """,
            (start_key, end_key),
        ).fetchall()
        return [row["meal_id"] for row in rows]
    sort_key = (
        """COALESCE((SELECT r.eaten_at_utc_sort_key FROM nutrition_meal_revisions r
                     WHERE r.meal_id = m.meal_id ORDER BY r.revision DESC LIMIT 1),
                    m.eaten_at_utc_sort_key)"""
        if has_revisions
        else "m.eaten_at_utc_sort_key"
    )
    not_voided = (
        "WHERE NOT EXISTS (SELECT 1 FROM nutrition_meal_voids v WHERE v.meal_id = m.meal_id)" if has_voids else ""
    )
    rows = connection.execute(
        f"""
        WITH effective AS (SELECT m.meal_id, {sort_key} AS sort_key FROM nutrition_meals m {not_voided})
        SELECT meal_id FROM effective WHERE sort_key >= ? AND sort_key < ? ORDER BY sort_key, meal_id
        """,
        (start_key, end_key),
    ).fetchall()
    return [row["meal_id"] for row in rows]


def _require_active_item(connection: sqlite3.Connection, meal_id: str, item_sequence: int) -> None:
    exists = connection.execute(
        "SELECT 1 FROM nutrition_meal_items WHERE meal_id = ? AND item_sequence = ?", (meal_id, item_sequence)
    ).fetchone()
    if exists is None:
        raise ValueError(f"meal {meal_id!r} has no item {item_sequence}")
    if item_sequence in _removed_sequences(connection, meal_id):
        raise ValueError(f"item {item_sequence} of meal {meal_id!r} was already removed")


def _insert_new_items(connection: sqlite3.Connection, meal_id: str, items: tuple[MealItem, ...]) -> None:
    if not items:
        raise ValueError("no items to add")
    expected = _next_item_sequence(connection, meal_id)
    for offset, item in enumerate(items):
        if item.meal_id != meal_id:
            raise ValueError(f"item {item.sequence} belongs to meal {item.meal_id!r}, not {meal_id!r}")
        # Sequences are allocated before the snapshot fact IDs are built from them; anything else
        # means the meal changed in between, or a removed item's number would be reused.
        if item.sequence != expected + offset:
            raise ValueError(
                f"meal {meal_id!r} changed while the item was being prepared (expected item {expected + offset})"
            )
        _insert_item(connection, item)


def _insert_item(connection: sqlite3.Connection, item: MealItem) -> None:
    if item.is_general:
        # In the caller's transaction, before the item row that references it (a failed write drops both).
        _ensure_general_meal_profile(connection)
    connection.execute(
        """
        INSERT INTO nutrition_meal_items (
            meal_id, item_sequence, food_name, food_profile_id,
            quantity, quantity_unit, serving_description
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item.meal_id,
            item.sequence,
            item.food_name,
            item.food_profile_id,
            decimal_to_text(item.quantity) if item.quantity is not None else None,
            item.quantity_unit.value if item.quantity_unit is not None else None,
            item.serving_description,
        ),
    )
    _insert_facts_in_dependency_order(
        connection, item.nutrition_facts, meal_id=item.meal_id, item_sequence=item.sequence, profile_id=None
    )


def _ensure_general_meal_profile(connection: sqlite3.Connection) -> None:
    """Create the general meal's system profile if missing, then check it is exactly that profile.

    Inserted once (``INSERT OR IGNORE``), never updated. A pre-existing row with that ID that has
    another name, nutrition facts or aliases is a user food, not the general meal: refused.
    """
    connection.execute(
        "INSERT OR IGNORE INTO nutrition_food_profiles (profile_id, name) VALUES (?, ?)",
        (GENERAL_MEAL_FOOD_ID, GENERAL_MEAL_NAME),
    )
    name = connection.execute(
        "SELECT name FROM nutrition_food_profiles WHERE profile_id = ?", (GENERAL_MEAL_FOOD_ID,)
    ).fetchone()["name"]
    has_facts = connection.execute(
        "SELECT 1 FROM nutrition_facts WHERE profile_id = ? LIMIT 1", (GENERAL_MEAL_FOOD_ID,)
    ).fetchone() is not None
    has_aliases = connection.execute(
        "SELECT 1 FROM nutrition_food_profile_aliases WHERE profile_id = ? LIMIT 1", (GENERAL_MEAL_FOOD_ID,)
    ).fetchone() is not None
    if name != GENERAL_MEAL_NAME or has_facts or has_aliases:
        raise ValueError(
            f"food {GENERAL_MEAL_FOOD_ID!r} in the catalog is not the general meal (it has nutrition facts, "
            "aliases or another name); general meals cannot be recorded. Nothing was changed."
        )


def _insert_removal(
    connection: sqlite3.Connection, meal_id: str, item_sequence: int, removed_at: datetime, *, replaced_by: int | None
) -> None:
    connection.execute(
        """
        INSERT INTO nutrition_meal_item_removals (meal_id, item_sequence, removed_at, replaced_by_item_sequence)
        VALUES (?, ?, ?, ?)
        """,
        (meal_id, item_sequence, removed_at.isoformat(), replaced_by),
    )


def _insert_void(
    connection: sqlite3.Connection, meal_id: str, voided_at: datetime, reason: str | None, *, merged_into: str | None
) -> None:
    connection.execute(
        "INSERT INTO nutrition_meal_voids (meal_id, voided_at, reason, merged_into_meal_id) VALUES (?, ?, ?, ?)",
        (meal_id, voided_at.isoformat(), reason, merged_into),
    )


def _load_history(connection: sqlite3.Connection, meal_id: str) -> MealHistory | None:
    meal_row = connection.execute(
        "SELECT eaten_at, meal_type FROM nutrition_meals WHERE meal_id = ?", (meal_id,)
    ).fetchone()
    if meal_row is None:
        return None
    revisions: tuple[MealRevision, ...] = ()
    if _has_table(connection, "nutrition_meal_revisions"):
        revisions = tuple(
            MealRevision(
                revision=row["revision"],
                revised_at=datetime.fromisoformat(row["revised_at"]),
                meal_type=MealType(row["meal_type"]),
                eaten_at=datetime.fromisoformat(row["eaten_at"]),
            )
            for row in connection.execute(
                "SELECT * FROM nutrition_meal_revisions WHERE meal_id = ? ORDER BY revision", (meal_id,)
            ).fetchall()
        )
    void: MealVoid | None = None
    merges: list[MealMerge] = []
    if _has_table(connection, "nutrition_meal_voids"):
        void_row = connection.execute("SELECT * FROM nutrition_meal_voids WHERE meal_id = ?", (meal_id,)).fetchone()
        if void_row is not None:
            void = MealVoid(
                voided_at=datetime.fromisoformat(void_row["voided_at"]),
                reason=void_row["reason"],
                merged_into=void_row["merged_into_meal_id"],
            )
        if _has_table(connection, "nutrition_meal_merged_items"):
            # A merge is recorded as the source's void row (when) plus one mapping row per copied item.
            items_by_source: dict[str, list[MergedItem]] = {}
            merged_at: dict[str, datetime] = {}
            for row in connection.execute(
                """
                SELECT mi.source_meal_id, mi.item_sequence, mi.source_item_sequence, v.voided_at
                FROM nutrition_meal_merged_items mi
                JOIN nutrition_meal_voids v ON v.meal_id = mi.source_meal_id
                WHERE mi.meal_id = ?
                ORDER BY mi.item_sequence
                """,
                (meal_id,),
            ).fetchall():
                source = row["source_meal_id"]
                items_by_source.setdefault(source, []).append(
                    MergedItem(row["item_sequence"], row["source_item_sequence"])
                )
                merged_at[source] = datetime.fromisoformat(row["voided_at"])
            merges = sorted(
                (MealMerge(source, merged_at[source], tuple(items)) for source, items in items_by_source.items()),
                key=lambda merge: (merge.merged_at, merge.source_meal_id),
            )
    return MealHistory(
        logged_meal_type=MealType(meal_row["meal_type"]),
        logged_eaten_at=datetime.fromisoformat(meal_row["eaten_at"]),
        revisions=revisions,
        void=void,
        merged_from=tuple(merges),
    )


def _reload_meal(connection: sqlite3.Connection, meal_id: str) -> Meal:
    meal = _load_meal(connection, meal_id)
    if meal is None:
        raise RuntimeError(f"meal {meal_id!r} disappeared while editing its items")
    return meal

def _load_profile(connection: sqlite3.Connection, profile_id: str) -> FoodNutritionProfile | None:
    profile_row = connection.execute(
        "SELECT * FROM nutrition_food_profiles WHERE profile_id = ?", (profile_id,)
    ).fetchone()
    if profile_row is None:
        return None
    alias_rows = connection.execute(
        "SELECT alias FROM nutrition_food_profile_aliases WHERE profile_id = ? ORDER BY alias",
        (profile_id,),
    ).fetchall()
    fact_rows = connection.execute(
        "SELECT * FROM nutrition_facts WHERE profile_id = ?",
        (profile_id,),
    ).fetchall()
    # See the matching comment in _load_meal: created_at is offset-bearing ISO text, so it
    # must be sorted as reconstructed aware datetimes, not as raw SQL text.
    facts = sorted(
        (_fact_from_row(row) for row in fact_rows),
        key=lambda fact: (fact.provenance.created_at, fact.fact_id),
    )
    return FoodNutritionProfile(
        profile_id=profile_row["profile_id"],
        name=profile_row["name"],
        facts=tuple(facts),
        aliases=tuple(row["alias"] for row in alias_rows),
    )


def _item_from_row(row: sqlite3.Row, facts: tuple[NutritionFact, ...]) -> MealItem:
    return MealItem(
        meal_id=row["meal_id"],
        sequence=row["item_sequence"],
        food_name=row["food_name"],
        quantity=_optional_decimal(row["quantity"]),
        quantity_unit=QuantityUnit(row["quantity_unit"]) if row["quantity_unit"] is not None else None,
        food_profile_id=row["food_profile_id"],
        serving_description=row["serving_description"],
        nutrition_facts=facts,
    )


def _fact_insert_row(
    fact: NutritionFact,
    *,
    meal_id: str | None,
    item_sequence: int | None,
    profile_id: str | None,
) -> tuple[object, ...]:
    minimums: dict[str, Decimal] = {}
    maximums: dict[str, Decimal] = {}
    if fact.value_range is not None:
        for nutrient in NutrientField:
            bounds = fact.value_range.bounds(nutrient)
            if bounds is not None:
                minimums[nutrient.value], maximums[nutrient.value] = bounds

    def text(value: Decimal | None) -> str | None:
        return decimal_to_text(value) if value is not None else None

    return (
        fact.fact_id,
        meal_id,
        item_sequence,
        profile_id,
        text(fact.values.calories_kcal),
        text(fact.values.protein_g),
        text(fact.values.carbohydrate_g),
        text(fact.values.fat_g),
        text(minimums.get(NutrientField.CALORIES_KCAL.value)),
        text(maximums.get(NutrientField.CALORIES_KCAL.value)),
        text(minimums.get(NutrientField.PROTEIN_G.value)),
        text(maximums.get(NutrientField.PROTEIN_G.value)),
        text(minimums.get(NutrientField.CARBOHYDRATE_G.value)),
        text(maximums.get(NutrientField.CARBOHYDRATE_G.value)),
        text(minimums.get(NutrientField.FAT_G.value)),
        text(maximums.get(NutrientField.FAT_G.value)),
        decimal_to_text(fact.basis_quantity),
        fact.basis_unit.value,
        fact.provenance.source_type.value,
        fact.provenance.source_reference,
        text(fact.provenance.confidence),
        fact.provenance.accuracy.value,
        fact.provenance.parser_version,
        fact.provenance.model_version,
        fact.provenance.created_at.isoformat(),
        fact.supersedes_fact_id,
    )


def _fact_from_row(row: sqlite3.Row) -> NutritionFact:
    values = NutritionValue(
        calories_kcal=_optional_decimal(row["calories_kcal"]),
        protein_g=_optional_decimal(row["protein_g"]),
        carbohydrate_g=_optional_decimal(row["carbohydrate_g"]),
        fat_g=_optional_decimal(row["fat_g"]),
    )
    has_range = any(row[f"min_{nutrient.value}"] is not None for nutrient in NutrientField)
    value_range = (
        NutritionRange(
            minimum=NutritionValue(
                **{nutrient.value: _optional_decimal(row[f"min_{nutrient.value}"]) for nutrient in NutrientField}
            ),
            maximum=NutritionValue(
                **{nutrient.value: _optional_decimal(row[f"max_{nutrient.value}"]) for nutrient in NutrientField}
            ),
        )
        if has_range
        else None
    )
    return NutritionFact(
        fact_id=row["fact_id"],
        values=values,
        basis_quantity=decimal_from_text(row["basis_quantity"]),
        basis_unit=QuantityUnit(row["basis_unit"]),
        provenance=NutritionProvenance(
            source_type=NutritionSourceType(row["source_type"]),
            accuracy=Accuracy(row["accuracy"]),
            source_reference=row["source_reference"],
            created_at=datetime.fromisoformat(row["created_at"]),
            confidence=_optional_decimal(row["confidence"]),
            parser_version=row["parser_version"],
            model_version=row["model_version"],
        ),
        value_range=value_range,
        supersedes_fact_id=row["supersedes_fact_id"],
    )


def _insert_facts_in_dependency_order(
    connection: sqlite3.Connection,
    facts: tuple[NutritionFact, ...],
    *,
    meal_id: str | None,
    item_sequence: int | None,
    profile_id: str | None,
) -> None:
    """Insert facts so a superseding fact is never inserted before what it supersedes.

    The append-only trigger requires the superseded row to already exist, but
    callers (including tests) may attach facts to a Meal/Profile in any order.
    """
    remaining = list(facts)
    inserted: set[str] = set()
    while remaining:
        ready = [fact for fact in remaining if fact.supersedes_fact_id is None or fact.supersedes_fact_id in inserted]
        if not ready:
            raise ValueError("nutrition fact history has an unresolvable supersession reference")
        for fact in ready:
            connection.execute(
                _FACT_INSERT_SQL,
                _fact_insert_row(fact, meal_id=meal_id, item_sequence=item_sequence, profile_id=profile_id),
            )
            inserted.add(fact.fact_id)
        remaining = [fact for fact in remaining if fact.fact_id not in inserted]


def _optional_decimal(text: str | None) -> Decimal | None:
    return None if text is None else decimal_from_text(text)


def _utc_sort_key(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@contextmanager
def _connect(database_path: Path) -> Iterator[sqlite3.Connection]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    _enable_wal(connection)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _enable_wal(connection: sqlite3.Connection) -> None:
    # Concurrent first starts can race while SQLite creates the database/WAL files.
    # Some Windows SQLite builds return SQLITE_BUSY here without honoring busy_timeout.
    for attempt in range(5):
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))
