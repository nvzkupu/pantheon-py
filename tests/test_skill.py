"""Tests for the SKILL.md parser."""

import pytest

from pantheon.skill import split_frontmatter, parse_text


class TestSplitFrontmatter:
    def test_standard(self):
        fm, body = split_frontmatter("---\nname: test\n---\n\n# Body")
        assert fm == "name: test"
        assert body == "# Body"

    def test_no_frontmatter(self):
        fm, body = split_frontmatter("# Just markdown\n\nContent")
        assert fm == ""
        assert body == "# Just markdown\n\nContent"

    def test_empty_body(self):
        fm, body = split_frontmatter("---\nname: test\n---\n")
        assert fm == "name: test"
        assert body == ""

    def test_whitespace_handling(self):
        fm, body = split_frontmatter("---\nname: test\n---\n\n  # Body  \n")
        assert fm == "name: test"
        assert body == "# Body"


class TestParseText:
    def test_full_skill(self):
        text = """---
name: athena
description: A strategist skill
license: MIT
metadata:
  persona: Your Devoted Strategist
  model: opus-4
  temperature: 0.5
  max_tokens: 8192
  tools:
    - read_file
    - list_dir
  delegates:
    - kali
---

# Athena

Body content."""

        s = parse_text(text, "/skills/athena/SKILL.md")
        assert s.name == "athena"
        assert s.description == "A strategist skill"
        assert s.license == "MIT"
        assert s.persona == "Your Devoted Strategist"
        assert s.model == "opus-4"
        assert s.temperature == 0.5
        assert s.max_tokens == 8192
        assert s.tool_names == ["read_file", "list_dir"]
        assert s.delegate_names == ["kali"]
        assert "# Athena" in s.body

    def test_missing_description_raises(self):
        with pytest.raises(ValueError, match="missing required field"):
            parse_text("---\nname: test\n---\n\nBody", "/test/SKILL.md")

    def test_name_inferred_from_path(self):
        s = parse_text("---\ndescription: inferred\n---\n\nBody", "/skills/myskill/SKILL.md")
        assert s.name == "myskill"

    def test_no_frontmatter_raises(self):
        with pytest.raises(ValueError, match="no YAML frontmatter"):
            parse_text("# Just markdown", "/test.md")

    def test_defaults(self):
        s = parse_text("---\nname: x\ndescription: x\n---\n\nBody", "/x/SKILL.md")
        assert s.model == "gpt-4o"
        assert s.temperature == 0.7
        assert s.max_tokens == 4096
        assert s.max_iterations == 10
        assert s.tool_names == []
        assert s.delegate_names == []

    def test_metadata_without_tools(self):
        text = """---
name: eris
description: A challenger
metadata:
  model: nano
  temperature: 0.9
---

# Eris"""
        s = parse_text(text, "/skills/eris/SKILL.md")
        assert s.model == "nano"
        assert s.temperature == 0.9
        assert s.tool_names == []
