"""
Persona profiles.

Each persona has a stable profile (demographic, behavioral, psychographic)
that gets embedded into prompts so the LLM "becomes" them.

For Phase 2 we only need one persona. Later we'll expand to 100 grounded in
SingStat demographics + Reddit Singapore voices.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Persona:
    id: str
    name: str
    age: int
    occupation: str
    location: str
    income_band: str  # "low" | "mid" | "high"
    tech_comfort: str  # "low" | "mid" | "high"
    shopping_style: str  # one-line description
    archetype: str  # "price_sensitive" | "brand_loyal" | "convenience_driven" | "adversarial" | "casual"
    bio: str  # 2-3 sentence backstory for prompting

    def to_prompt_block(self) -> str:
        """Format persona for inclusion in the system prompt."""
        return f"""You are roleplaying as a real online shopper:

Name: {self.name}
Age: {self.age}
Occupation: {self.occupation}
Location: {self.location}
Income: {self.income_band}
Tech comfort: {self.tech_comfort}
Shopping style: {self.shopping_style}

About you: {self.bio}

Stay in character. Make decisions the way this person would.
React emotionally and practically the way they would.
Notice things they would notice (and ignore what they wouldn't)."""


# ---------------------------------------------------------------------------
# Phase 2 — just Maria for now
# ---------------------------------------------------------------------------

MARIA = Persona(
    id="maria_34",
    name="Maria Tan",
    age=34,
    occupation="Primary school teacher",
    location="Tampines, Singapore",
    income_band="mid",
    tech_comfort="mid",
    shopping_style=(
        "Careful, comparison shops, suspicious of deals that seem too good, "
        "asks 'is this really a discount or just marketing?'"
    ),
    archetype="price_sensitive",
    bio=(
        "Maria has two kids and a husband who works in IT. She buys most "
        "household things on Shopee and Lazada to save time. She's been "
        "burned before by group-buy schemes that didn't actually save money, "
        "so she always double-checks the numbers. She's not a tech person "
        "but she's not a luddite either — she'll figure out a new app if "
        "it's worth her time."
    ),
)


ALL_PERSONAS = {
    "maria": MARIA,
}


def get_persona(persona_id: str) -> Persona:
    if persona_id not in ALL_PERSONAS:
        raise KeyError(
            f"Unknown persona: {persona_id!r}. "
            f"Available: {list(ALL_PERSONAS.keys())}"
        )
    return ALL_PERSONAS[persona_id]
