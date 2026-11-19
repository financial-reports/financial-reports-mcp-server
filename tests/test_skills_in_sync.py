"""The plugin skill tree and the standalone `skills/` copy must not drift.

Why this exists: the same skill files ship twice. `plugins/financialfilings/skills/`
is what the Claude plugin directory serves, and `skills/` is the standalone copy for
someone who wants the skill without installing the plugin. Issue #208 asked for one
of them to become the source rather than for the two to be "kept in sync", because
two hand-maintained copies of one file is drift and this repo has already paid for
that class several times.

The plugin tree is the source. `scripts/sync_standalone_skills.sh` copies one way,
and this test is the gate: a missed sync is a red run rather than a standalone copy
that is quietly a release behind. That matters more than it looks, because the
standalone copy is the one a reader finds by browsing the repo, so a stale one is
read by exactly the person who has no other reference.

`skills/README.md` and `skills/GETTING-STARTED.md` are standalone-only and are not
compared: they describe installing without the plugin, which the plugin tree has no
reason to carry.
"""
from __future__ import annotations

import hashlib
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN_SKILLS = ROOT / "plugins" / "financialfilings" / "skills"
STANDALONE_SKILLS = ROOT / "skills"
STANDALONE_ONLY = {"README.md", "GETTING-STARTED.md"}


def _tree(root: pathlib.Path) -> dict[str, str]:
    """Every file under `root`, as {relative posix path: sha256}."""
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def test_the_plugin_tree_is_not_empty() -> None:
    """Positive control, first: every assertion below compares two trees, and two
    EMPTY trees are equal. Without this, deleting the skills would pass."""
    plugin = _tree(PLUGIN_SKILLS)
    assert plugin, "no files under the plugin skill tree"
    skill_files = [p for p in plugin if p.endswith("SKILL.md")]
    assert len(skill_files) >= 5, (
        f"expected the base skill plus the four job-shaped skills, found {skill_files}"
    )


def test_every_plugin_skill_has_an_identical_standalone_copy() -> None:
    plugin = _tree(PLUGIN_SKILLS)
    standalone = {
        rel: digest
        for rel, digest in _tree(STANDALONE_SKILLS).items()
        if rel.split("/")[0] not in STANDALONE_ONLY
    }

    missing = sorted(set(plugin) - set(standalone))
    assert not missing, (
        "these files exist in the plugin tree and not in skills/: "
        f"{missing}. Run scripts/sync_standalone_skills.sh"
    )

    extra = sorted(set(standalone) - set(plugin))
    assert not extra, (
        "these files exist in skills/ and not in the plugin tree: "
        f"{extra}. The plugin tree is the source, so either add them there or "
        "delete them here; a standalone-only skill is a skill the directory "
        "never ships"
    )

    differing = sorted(rel for rel in plugin if plugin[rel] != standalone[rel])
    assert not differing, (
        f"these files differ between the two trees: {differing}. "
        "Run scripts/sync_standalone_skills.sh"
    )


def test_the_comparison_can_actually_fail() -> None:
    """Mutation control for the test above. A byte-identity assertion over two
    trees built by the same function is the kind of check that passes because
    both sides are computed the same way, so prove a single changed byte is
    caught before trusting a green run."""
    plugin = _tree(PLUGIN_SKILLS)
    mutated = dict(plugin)
    victim = next(rel for rel in sorted(mutated) if rel.endswith("SKILL.md"))
    mutated[victim] = "0" * 64
    differing = [rel for rel in plugin if plugin[rel] != mutated[rel]]
    assert differing == [victim], (
        "the digest comparison does not detect a changed file, so the test above "
        "is not measuring what it claims"
    )
