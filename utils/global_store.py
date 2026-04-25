from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from pathlib import Path
from typing import Any

from utils.paths import APP_ROOT


CONFIG_PATH = APP_ROOT / "config.yaml"
GLOBAL_CONFIG_VERSION = 1


class GlobalStore(ABC):
    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        raise NotImplementedError

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    def all(self) -> dict[str, Any]:
        raise NotImplementedError


class YamlFileGlobalStore(GlobalStore):
    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path

    def get(self, key: str, default: Any = None) -> Any:
        data = self.all()
        current: Any = data
        for segment in key.split("/"):
            if not isinstance(current, dict) or segment not in current:
                return default
            current = current[segment]
        return deepcopy(current)

    def set(self, key: str, value: Any) -> None:
        data = self.all()
        current = data
        segments = key.split("/")
        for segment in segments[:-1]:
            next_value = current.get(segment)
            if not isinstance(next_value, dict):
                next_value = {}
                current[segment] = next_value
            current = next_value
        current[segments[-1]] = deepcopy(value)
        data.setdefault("version", GLOBAL_CONFIG_VERSION)
        self._write(data)

    def all(self) -> dict[str, Any]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return {"version": GLOBAL_CONFIG_VERSION}
        try:
            data = _parse_yaml(self.path.read_text(encoding="utf-8"))
        except OSError:
            return {"version": GLOBAL_CONFIG_VERSION}
        return data if isinstance(data, dict) else {"version": GLOBAL_CONFIG_VERSION}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.write_text(_dump_yaml(data), encoding="utf-8")


_store: GlobalStore = YamlFileGlobalStore()


def global_store() -> GlobalStore:
    return _store


def set_global_store(store: GlobalStore) -> None:
    global _store
    _store = store


def get_global_value(key: str, default: Any = None) -> Any:
    return global_store().get(key, default)


def set_global_value(key: str, value: Any) -> None:
    global_store().set(key, value)


def _parse_yaml(text: str) -> Any:
    lines = [
        (len(raw_line) - len(raw_line.lstrip(" ")), raw_line.strip())
        for raw_line in text.splitlines()
        if raw_line.strip() and not raw_line.lstrip().startswith("#")
    ]
    if not lines:
        return {}
    value, _index = _parse_block(lines, 0, lines[0][0])
    return value


def _parse_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    if lines[index][1].startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_dict(lines, index, indent)


def _parse_dict(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    data: dict[str, Any] = {}
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent:
            break
        if line_indent > indent:
            index += 1
            continue
        if content.startswith("- ") or ":" not in content:
            break

        key, raw_value = content.split(":", maxsplit=1)
        key = key.strip()
        raw_value = raw_value.strip()
        index += 1
        if raw_value:
            data[key] = _parse_scalar(raw_value)
        elif index < len(lines) and lines[index][0] > line_indent:
            data[key], index = _parse_block(lines, index, lines[index][0])
        else:
            data[key] = {}
    return data, index


def _parse_list(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent != indent or not content.startswith("- "):
            break

        item_content = content[2:].strip()
        index += 1
        if not item_content:
            if index < len(lines) and lines[index][0] > line_indent:
                item, index = _parse_block(lines, index, lines[index][0])
            else:
                item = None
        elif ":" in item_content and not item_content.startswith(("'", '"')):
            key, raw_value = item_content.split(":", maxsplit=1)
            item = {key.strip(): _parse_scalar(raw_value.strip()) if raw_value.strip() else {}}
            if index < len(lines) and lines[index][0] > line_indent:
                nested, index = _parse_dict(lines, index, lines[index][0])
                item.update(nested)
        else:
            item = _parse_scalar(item_content)
        items.append(item)
    return items, index


def _parse_scalar(value: str) -> Any:
    if value == "null":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if value.startswith('"') and value.endswith('"'):
        import json

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


def _dump_yaml(data: Any, indent: int = 0) -> str:
    lines = _dump_yaml_lines(data, indent)
    return "\n".join(lines) + "\n"


def _dump_yaml_lines(data: Any, indent: int) -> list[str]:
    prefix = " " * indent
    if isinstance(data, dict):
        lines: list[str] = []
        for key, value in data.items():
            if isinstance(value, dict):
                lines.append(f"{prefix}{key}:")
                lines.extend(_dump_yaml_lines(value, indent + 2))
            elif isinstance(value, list):
                if value:
                    lines.append(f"{prefix}{key}:")
                    lines.extend(_dump_yaml_lines(value, indent + 2))
                else:
                    lines.append(f"{prefix}{key}: []")
            else:
                lines.append(f"{prefix}{key}: {_format_scalar(value)}")
        return lines
    if isinstance(data, list):
        lines = []
        for item in data:
            if isinstance(item, dict):
                item_lines = _dump_yaml_lines(item, indent + 2)
                if item_lines:
                    lines.append(f"{prefix}- {item_lines[0].strip()}")
                    lines.extend(item_lines[1:])
                else:
                    lines.append(f"{prefix}- {{}}")
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                lines.extend(_dump_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_format_scalar(item)}")
        return lines
    return [f"{prefix}{_format_scalar(data)}"]


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    import json

    return json.dumps(str(value), ensure_ascii=False)
