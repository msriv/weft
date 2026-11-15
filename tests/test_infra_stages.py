"""The Terraform nightly stage list must match pipeline/run.py STAGES (#155)."""

import re
from pathlib import Path

from pipeline.run import STAGES

# Not part of the nightly workflow: autoclean has its own scheduler job.
NOT_NIGHTLY = {"autoclean"}


def test_terraform_nightly_stages_match_runner() -> None:
    tf = (Path(__file__).resolve().parent.parent / "infra" / "main.tf").read_text()
    block = re.search(r'module "nightly" \{.*?\n\s*stages\s*=\s*\[(.*?)\]', tf, re.DOTALL)
    assert block, "module.nightly.stages not found in infra/main.tf"
    listed = re.findall(r'"([a-z_]+)"', block.group(1))
    assert listed == [s for s in STAGES if s not in NOT_NIGHTLY]
