from __future__ import annotations

from dataclasses import dataclass

import anthropic

_SYSTEM_PROMPT = """\
You parse media download requests from family members into structured data.

Rules:
- Classify as TV show or movie.
- "latest", "newest", "most recent" → scope = latest_episode
- Specific episode references ("S02E05", "season 2 episode 5") → scope = specific_episode
- "the whole season" or "season 3" alone → scope = full_season
- A film → scope = movie
- Extract year when mentioned (e.g. "The Batman 2022" → year = 2022).
- Extract any size constraint ("not too big", "under 2GB") → max_size_gb
- Extract any quality preference ("HD", "4K", "1080p") → min_quality
- If the title is ambiguous (could be show or film, or unclear) → confidence < 0.7, set clarification_needed
- Always call parse_request. Never respond with text.
"""

_INTENT_TOOL: anthropic.types.ToolParam = {
    "name": "parse_request",
    "description": "Structured representation of a media download request",
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["tv", "movie", "unknown"],
            },
            "title": {"type": "string"},
            "year": {
                "type": "integer",
                "description": "Release year if mentioned in the request",
            },
            "scope": {
                "type": "string",
                "enum": ["latest_episode", "specific_episode", "full_season", "movie"],
            },
            "season": {"type": "integer"},
            "episode": {"type": "integer"},
            "max_size_gb": {"type": "number"},
            "min_quality": {
                "type": "string",
                "enum": ["720p", "1080p", "4k"],
            },
            "confidence": {
                "type": "number",
                "description": "0.0–1.0 confidence the request was correctly understood",
            },
            "clarification_needed": {
                "type": "string",
                "description": "Question to ask the user when confidence < 0.7",
            },
        },
        "required": ["kind", "title", "scope", "confidence"],
    },
}


@dataclass
class ParsedIntent:
    kind: str
    title: str
    scope: str
    year: int | None
    season: int | None
    episode: int | None
    max_size_gb: float | None
    min_quality: str | None
    confidence: float
    clarification_needed: str | None

    def is_confident(self) -> bool:
        return self.confidence >= 0.7

    def lookup_term(self) -> str:
        """Build a search term that includes year when available."""
        if self.year:
            return f"{self.title} {self.year}"
        return self.title

    def human_description(self) -> str:
        year_str = f" ({self.year})" if self.year else ""
        if self.kind == "tv":
            if self.scope == "latest_episode":
                return f"the latest episode of {self.title}{year_str}"
            if self.scope == "specific_episode" and self.season and self.episode:
                return f"{self.title}{year_str} S{self.season:02d}E{self.episode:02d}"
            if self.scope == "full_season" and self.season:
                return f"{self.title}{year_str} Season {self.season}"
        if self.kind == "movie":
            return f"the movie {self.title}{year_str}"
        return f"{self.title}{year_str}"


async def parse_intent(client: anthropic.AsyncAnthropic, text: str) -> ParsedIntent:
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[_INTENT_TOOL],
        tool_choice={"type": "tool", "name": "parse_request"},
        messages=[{"role": "user", "content": text}],
    )

    tool_block = next(b for b in response.content if b.type == "tool_use")
    inp = tool_block.input

    return ParsedIntent(
        kind=inp["kind"],
        title=inp["title"],
        scope=inp["scope"],
        year=inp.get("year"),
        season=inp.get("season"),
        episode=inp.get("episode"),
        max_size_gb=inp.get("max_size_gb"),
        min_quality=inp.get("min_quality"),
        confidence=float(inp["confidence"]),
        clarification_needed=inp.get("clarification_needed"),
    )
