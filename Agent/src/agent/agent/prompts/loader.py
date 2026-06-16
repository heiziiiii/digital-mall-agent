"""提示词 Skill 加载器。

每个提示词位于 ``skills/<name>/SKILL.md``，由 YAML 风格 frontmatter
和正文组成。本模块负责解析、缓存并渲染最终 system prompt。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_BASE_IDENTITY = "你是「智能数码商城」的在线客服助手，专业、简洁、友好，只围绕数码商城业务回答。"
_SKILLS_DIR = Path(__file__).parent / "skills"


@dataclass(frozen=True)
class Skill:
    """一个提示词 Skill。"""

    name: str
    description: str
    prepend_base: bool
    body: str

    def render(self, variables: dict[str, str] | None = None) -> str:
        """渲染为最终 system 文本。"""
        body = self.body
        for key, value in (variables or {}).items():
            body = body.replace(f"{{{{ {key} }}}}", value)
        if self.prepend_base:
            return f"{_BASE_IDENTITY}\n{body}"
        return body


@lru_cache(maxsize=None)
def load_skill(name: str) -> Skill:
    """按名称加载并缓存 Skill。"""
    path = _SKILLS_DIR / name / "SKILL.md"
    if not path.exists():
        raise FileNotFoundError(f"未找到提示词 Skill：{name}（路径：{path}）")

    text = path.read_text(encoding="utf-8")
    if not text.lstrip().startswith("---"):
        raise ValueError("SKILL.md 缺少 frontmatter（需以 --- 开头）")

    _, raw_meta, body = text.split("---", 2)
    meta: dict[str, str] = {}
    for line in raw_meta.strip().splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()

    return Skill(
        name=meta.get("name", name),
        description=meta.get("description", ""),
        prepend_base=meta.get("prepend_base", "false").lower() == "true",
        body=body.strip(),
    )


def render_skill(name: str, variables: dict[str, str] | None = None) -> str:
    """加载并渲染指定 Skill 的最终 system 文本。"""
    return load_skill(name).render(variables=variables)


def list_skills() -> list[Skill]:
    """列出全部可用 Skill，便于调试与文档生成。"""
    return [
        load_skill(path.parent.name)
        for path in sorted(_SKILLS_DIR.glob("*/SKILL.md"))
    ]
