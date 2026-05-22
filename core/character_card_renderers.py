from __future__ import annotations

import html
import json
from typing import Any

from core.models import CharacterCard


def render_card_markdown(card: CharacterCard) -> str:
    name = _card_name(card)
    aliases = ", ".join(card.identity.aliases)
    tags = ", ".join(card.user_metadata.tags)
    lines = [
        f"# {name}",
        "",
        f"- Status: {card.compile_status.value}",
        f"- Source: {card.compile_source.value}",
    ]
    if aliases:
        lines.append(f"- Aliases: {aliases}")
    if tags:
        lines.append(f"- Tags: {tags}")
    if card.user_metadata.notes.strip():
        lines.extend(["", "## Notes", card.user_metadata.notes.strip()])
    if card.assets.cover_path:
        lines.extend(["", "## Cover", card.assets.cover_path])
    if card.profile.summary.strip():
        lines.extend(["", "## Summary", card.profile.summary.strip()])
    if card.profile.long_description.strip():
        lines.extend(["", "## Description", card.profile.long_description.strip()])
    if card.profile.personality.strip() or card.profile.personality_traits:
        lines.append("")
        lines.append("## Personality")
        if card.profile.personality.strip():
            lines.append(card.profile.personality.strip())
        lines.extend([f"- {item}" for item in card.profile.personality_traits if item.strip()])
    if card.profile.speech_style:
        lines.extend(["", "## Speech Style"])
        lines.extend([f"- {item}" for item in card.profile.speech_style if item.strip()])
    if card.relationships:
        lines.extend(["", "## Relationships"])
        for item in card.relationships:
            lines.append(f"- {_dict_text(item)}")
    if card.timeline:
        lines.extend(["", "## Timeline"])
        for item in card.timeline:
            label = " / ".join(str(item.get(key, "")) for key in ("season_id", "episode_id") if item.get(key))
            state = item.get("state", {})
            lines.append(f"- {label}: {_dict_text(state) if isinstance(state, dict) else state}")
    warnings = [*card.quality.warnings, *card.evidence.warnings]
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend([f"- {item}" for item in warnings if item.strip()])
    lines.extend(
        [
            "",
            "## Evidence",
            f"- Evidence count: {card.evidence.evidence_count}",
        ]
    )
    lines.extend([f"- {item}" for item in card.evidence.refs if item.strip()])
    return "\n".join(lines).rstrip() + "\n"


def render_card_html(card: CharacterCard) -> str:
    name = html.escape(_card_name(card))
    status = html.escape(card.compile_status.value)
    source = html.escape(card.compile_source.value)
    cover = _cover_html(card)
    sections = [
        _section("Summary", card.profile.summary),
        _section("Description", card.profile.long_description),
        _list_section("Personality", [card.profile.personality, *card.profile.personality_traits]),
        _list_section("Speech Style", card.profile.speech_style),
        _list_section("Behavior", card.profile.behavior_patterns),
        _list_section("Warnings", [*card.quality.warnings, *card.evidence.warnings]),
        _timeline_section(card),
        _list_section("Evidence", card.evidence.refs),
    ]
    notes = html.escape(card.user_metadata.notes)
    aliases = html.escape(", ".join(card.identity.aliases))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{name}</title>
  <style>
    body {{ margin: 0; font-family: "Segoe UI", sans-serif; color: #202124; background: #f7f6f2; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 28px; }}
    header {{ display: grid; grid-template-columns: minmax(180px, 260px) 1fr; gap: 24px; align-items: start; }}
    img.cover {{ width: 100%; aspect-ratio: 9 / 16; object-fit: cover; border-radius: 8px; background: #ddd; }}
    h1 {{ margin: 0 0 8px; font-size: 32px; line-height: 1.18; }}
    .meta {{ color: #5f6368; line-height: 1.65; }}
    section {{ margin-top: 24px; padding-top: 18px; border-top: 1px solid #dadce0; }}
    h2 {{ font-size: 18px; margin: 0 0 10px; }}
    p, li {{ line-height: 1.7; }}
    ul {{ padding-left: 20px; }}
    @media (max-width: 720px) {{ header {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>{cover}</div>
      <div>
        <h1>{name}</h1>
        <div class="meta">Status: {status}<br>Source: {source}<br>Aliases: {aliases}</div>
        <p>{notes}</p>
      </div>
    </header>
    {''.join(sections)}
  </main>
</body>
</html>
"""


def build_human_json_sections(card: CharacterCard) -> list[dict[str, Any]]:
    payload = card.model_dump(mode="json")
    groups = [
        ("Identity", ["card_id", "card_kind", "compile_status", "compile_source", "identity", "user_metadata"]),
        ("Profile", ["profile", "prompt_surfaces", "dialogue", "character_book"]),
        ("Evidence", ["source_context", "timeline", "evidence", "quality"]),
        ("Assets And Exports", ["assets", "export_profiles", "extensions"]),
    ]
    return [
        {
            "title": title,
            "items": {key: payload.get(key) for key in keys if key in payload},
        }
        for title, keys in groups
    ]


def _card_name(card: CharacterCard) -> str:
    return card.identity.display_name or card.identity.character_name or card.card_id or "Untitled Character"


def _cover_html(card: CharacterCard) -> str:
    if not card.assets.cover_path:
        return ""
    return f'<img class="cover" src="{html.escape(card.assets.cover_path, quote=True)}" alt="{html.escape(_card_name(card), quote=True)} cover">'


def _section(title: str, content: str) -> str:
    if not content.strip():
        return ""
    return f"<section><h2>{html.escape(title)}</h2><p>{html.escape(content.strip())}</p></section>"


def _list_section(title: str, items: list[str]) -> str:
    clean = [item.strip() for item in items if isinstance(item, str) and item.strip()]
    if not clean:
        return ""
    body = "".join(f"<li>{html.escape(item)}</li>" for item in clean)
    return f"<section><h2>{html.escape(title)}</h2><ul>{body}</ul></section>"


def _timeline_section(card: CharacterCard) -> str:
    if not card.timeline:
        return ""
    items = []
    for item in card.timeline:
        label = " / ".join(str(item.get(key, "")) for key in ("season_id", "episode_id") if item.get(key))
        state = item.get("state", {})
        text = _dict_text(state) if isinstance(state, dict) else str(state)
        items.append(f"<li><strong>{html.escape(label)}</strong>: {html.escape(text)}</li>")
    return f"<section><h2>Timeline</h2><ul>{''.join(items)}</ul></section>"


def _dict_text(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)
