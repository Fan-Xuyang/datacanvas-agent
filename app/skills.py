"""Small, auditable skill packs loaded from the local skills directory."""

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    keywords: tuple[str, ...]
    instructions: str


class SkillRegistry:
    def __init__(self, root: Path):
        self.root = Path(root)

    def list(self):
        skills = []
        for path in sorted(self.root.glob("*/SKILL.md")):
            skill = self._load(path)
            skills.append({"name": skill.name, "description": skill.description})
        return skills

    def select(self, query: str):
        normalized = query.casefold()
        matches = []
        for path in sorted(self.root.glob("*/SKILL.md")):
            skill = self._load(path)
            score = sum(
                1 for keyword in skill.keywords if keyword.casefold() in normalized
            )
            if score:
                matches.append((score, skill))
        matches.sort(key=lambda item: (-item[0], item[1].name))
        return [skill for _, skill in matches[:3]]

    @staticmethod
    def _load(path: Path):
        text = path.read_text(encoding="utf-8")
        header, _, body = text.partition("\n---\n")
        fields = {}
        for line in header.splitlines():
            match = re.match(r"^(name|description|keywords):\s*(.*)$", line)
            if match:
                fields[match.group(1)] = match.group(2).strip().strip("\"'")
        if not fields.get("name") or not fields.get("description") or not body.strip():
            raise ValueError(f"Skill 元数据不完整：{path.name}")
        keywords = tuple(
            x.strip() for x in fields.get("keywords", "").split(",") if x.strip()
        )
        return Skill(fields["name"], fields["description"], keywords, body.strip())
