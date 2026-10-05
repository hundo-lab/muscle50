"""Resolve what the user typed after `--item` to one catalog food ID, without guessing.

The token is a food ID (exact, case-sensitive) or a food's exact name or alias (surrounding
whitespace trimmed, ASCII case ignored through `FoodNutritionRepository.search`). There is no
fuzzy, partial or suggested match. A token that could mean two different foods is refused, and
nothing is picked automatically. A token that matches nothing is reported as "no match" so the
caller can hand it on unchanged and the existing unknown-food refusal keeps its text and order.
"""

from __future__ import annotations

from muscle50.application.nutrition import FoodNutritionRepository
from muscle50.application.nutrition_logging import NutritionLoggingError


class ResolveFoodReference:
    """Map what the user typed after --item to one catalog food ID, without guessing."""

    def __init__(self, foods: FoodNutritionRepository) -> None:
        self._foods = foods

    def execute(self, reference: str, *, label: str) -> str | None:
        """The ID of the one food `reference` names; None when no food has it as ID, name or alias.

        Raises NutritionLoggingError when the reference names more than one food.
        """
        by_id = self._foods.get(reference)
        text = reference.strip()
        if not text:
            return by_id.profile_id if by_id is not None else None
        named = [
            profile.profile_id
            for profile in self._foods.search(text)
            if by_id is None or profile.profile_id != by_id.profile_id
        ]
        if by_id is not None:
            if named:
                food_or_foods = "food" if len(named) == 1 else "foods"
                raise NutritionLoggingError(
                    f"{label} {reference!r} is ambiguous: it is the ID of food {by_id.profile_id} and a name/alias "
                    f"of {food_or_foods} {', '.join(named)}. No food is chosen automatically. Nothing was changed."
                )
            return by_id.profile_id
        if not named:
            return None
        if len(named) == 1:
            return named[0]
        raise NutritionLoggingError(
            f"{label} {reference!r} is ambiguous: it is a name/alias of foods {', '.join(named)}. "
            "No food is chosen automatically; use one of these food IDs. Nothing was changed."
        )
