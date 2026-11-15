"""Build inputs stay pinned: no `latest` or untagged images, no floating action tags."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _files(*globs: str) -> list[Path]:
    return [p for g in globs for p in ROOT.glob(g) if "node_modules" not in p.parts]


def test_images_have_explicit_tags() -> None:
    bad = []
    for p in _files("**/Dockerfile"):
        for line in p.read_text().splitlines():
            m = re.match(
                r"\s*(?:FROM|COPY\s+--from=)\s*(?:--platform=\S+\s+)?(\S+)", line, re.IGNORECASE
            )
            if m:
                img = m.group(1)
                if img in {"scratch"} or re.fullmatch(r"[a-z_]+", img):  # build-stage alias
                    continue
                if ":" not in img.split("/")[-1] or img.endswith(":latest"):
                    bad.append(f"{p.relative_to(ROOT)}: {img}")
    for p in _files("docker-compose*.yml"):
        for line in p.read_text().splitlines():
            m = re.match(r"\s*image:\s*(\S+)", line)
            if m and (":" not in m.group(1).split("/")[-1] or m.group(1).endswith(":latest")):
                bad.append(f"{p.relative_to(ROOT)}: {m.group(1)}")
    assert not bad, bad


def test_actions_pinned_by_sha() -> None:
    bad = []
    for p in _files(".github/workflows/*.yml"):
        for line in p.read_text().splitlines():
            m = re.search(r"uses:\s*(\S+)", line)
            if (
                m
                and not m.group(1).startswith("./")
                and not re.search(r"@[0-9a-f]{40}$", m.group(1))
            ):
                bad.append(f"{p.name}: {m.group(1)}")
    assert not bad, bad
