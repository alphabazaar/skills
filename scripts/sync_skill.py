#!/usr/bin/env python3
"""Copy the live skill from alphabazaar.ai into skills/alpha-bazaar/SKILL.md.

The site's skill.md (https://www.alphabazaar.ai/skill.md) is the source of truth: it is served next to the API it
describes. This copy keeps its name, description and body, and writes frontmatter that follows the Agent Skills
spec (name, description, license, compatibility, metadata with string values), so it also loads where unknown
top-level keys are errors, such as claude.ai uploads and the Skills API. The plugin manifests get the skill's
version, so installed plugins see updates.

  python3 scripts/sync_skill.py                 fetch the live skill
  python3 scripts/sync_skill.py --from FILE     use a local copy (for tests)
"""
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

SOURCE = "https://www.alphabazaar.ai/skill.md"
ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "alpha-bazaar" / "SKILL.md"
PLUGIN = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
NAME = "alpha-bazaar"
COMPATIBILITY = ("Needs network access to api.alphabazaar.ai. The REST examples use curl and jq; MCP clients can use "
                 "https://api.alphabazaar.ai/mcp instead.")


def fail(message: str) -> None:
    print(f"sync_skill: {message}", file=sys.stderr)
    sys.exit(1)


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "alphabazaar-skills-sync"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def split(text: str):
    """(frontmatter lines, body) of a SKILL.md, or fail."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        fail("the source doesn't start with YAML frontmatter")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        fail("the source's frontmatter never closes")
    return lines[1:end], "\n".join(lines[end + 1:])


def top_level(front, key: str) -> str:
    """A top-level scalar from the frontmatter (the site writes them unquoted on one line)."""
    for line in front:
        m = re.match(rf"^{re.escape(key)}:\s*(.*)$", line)
        if m:
            value = m.group(1).strip()
            if value[:1] in "\"'":
                if len(value) < 2 or value[-1] != value[0] or value[0] in value[1:-1] or "\\" in value:
                    fail(f"{key}: only plain or simply quoted one-line values are supported")
                return value[1:-1]
            if value[:1] in ">|&*!%@`[{" or " #" in value or ": " in value:
                fail(f"{key}: {value[:30]!r} isn't a plain one-line YAML scalar")
            return value
    return ""


def build(source: str):
    front, body = split(source)
    name, description, version = top_level(front, "name"), top_level(front, "description"), top_level(front, "version")
    if name != NAME:
        fail(f"expected name {NAME!r}, got {name!r}")
    if not description or len(description) > 1024:
        fail("the description is missing or longer than 1024 characters")
    if "<" in description or ">" in description:
        fail("the description has < or >, which claude.ai uploads reject")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        fail(f"the version {version!r} isn't MAJOR.MINOR.PATCH")
    if len(body.strip()) < 2000:
        fail("the body is too short to be the skill: refusing to overwrite")
    if SKILL.exists() and "--force" not in sys.argv:
        old = split(SKILL.read_text(encoding="utf-8"))[1]
        if len(body) < 0.7 * len(old):
            fail(f"the body shrank from {len(old)} to {len(body)} characters: refusing (rerun with --force if intended)")
    q = json.dumps  # a JSON string is a valid YAML double-quoted scalar
    header = "\n".join([
        "---",
        f"name: {NAME}",
        f"description: {q(description, ensure_ascii=False)}",
        "license: MIT",
        f"compatibility: {q(COMPATIBILITY)}",
        "metadata:",
        f"  version: {q(version)}",
        f"  homepage: {q('https://www.alphabazaar.ai')}",
        f"  api-key-env: {q('ALPHA_BAZAAR_API_KEY')}",
        f"  source: {q(SOURCE)}",
        "---",
    ])
    skill = header + "\n" + body
    return skill, f"{version}+{hashlib.sha256(skill.encode()).hexdigest()[:8]}"  # any change is a new plugin version


def set_version(path: Path, version: str, plugin_entry: bool) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if plugin_entry:
        for plugin in data["plugins"]:
            if plugin["name"] == NAME:
                plugin["version"] = version
    else:
        data["version"] = version
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv) -> int:
    source = Path(argv[argv.index("--from") + 1]).read_text(encoding="utf-8") if "--from" in argv else fetch(SOURCE)
    skill, version = build(source)
    SKILL.parent.mkdir(parents=True, exist_ok=True)
    SKILL.write_text(skill, encoding="utf-8")
    set_version(PLUGIN, version, plugin_entry=False)
    set_version(MARKETPLACE, version, plugin_entry=True)
    print(f"skill v{version}: {SKILL.relative_to(ROOT)}, plugin.json and marketplace.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
