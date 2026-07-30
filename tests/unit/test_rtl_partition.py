# tests/unit/test_rtl_partition.py
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/rtl-design/scripts"))
from rtl.partition import coverage_verdict, post_verdict  # noqa: E402

_PURE_MANIFEST = {
    "module": "top",
    "children": [
        {"name": "leaf", "rtl_modules": ["leaf_m"]},
        {"name": "topc", "rtl_modules": ["top"]},
    ],
}


def _coverage(tmp_path, top):
    """The pre-dispatch gate is no longer a verb; coverage_verdict is what specification's own
    check-coverage mirrors, and test_partition_purity_agreement.py locks the two together."""
    return coverage_verdict(tmp_path / "manifest.json", top)


def test_pre_phase_fails_bundled_top_manifest_only(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "module": "top",
                "children": [
                    {"name": "leaf", "rtl_modules": ["leaf_m"]},
                    {"name": "topc", "rtl_modules": ["top", "wb_front"]},
                ],
            }
        )
    )
    status, reason = _coverage(tmp_path, "top")
    assert status == "fail" and "not pure" in reason


def test_pre_phase_fails_zero_coverage(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {"module": "top", "children": [{"name": "leaf", "rtl_modules": ["leaf_m"]}]}
        )
    )
    status, reason = _coverage(tmp_path, "top")
    assert status == "fail" and "covered by 0 children" in reason


def test_post_verdict_fails_clean_on_missing_ledger(tmp_path):
    # The post-exit gate must fail loud-but-clean (status=fail, rc=1) when
    # reaped-children.json / the sidecars are absent, per its own fail_reason — not let
    # a raw traceback escape from reading a missing file.
    (tmp_path / "manifest.json").write_text(json.dumps(_PURE_MANIFEST))
    verdict, rc = post_verdict(
        tmp_path / "manifest.json",
        "top",
        tmp_path / "reaped-children.json",  # absent
        tmp_path,  # workdir: neither sidecar present
    )
    assert rc == 1
    assert "reaped-children.json" in verdict["fail_reason"]


def test_post_verdict_never_under_reports_a_readable_ledger(tmp_path):
    # A fail envelope promotes exactly like a passing one, and promote treats artifacts[] as the
    # new canonical view: every entry it omits is deleted from canonical. So a verdict must never
    # report an empty artifacts[] while the sidecars on disk are readable — here the sidecars
    # carried forward but reaped-children.json did not, which is a fail with a live baseline.
    (tmp_path / "manifest.json").write_text(json.dumps(_PURE_MANIFEST))
    (tmp_path / "rtl-files.json").write_text(
        json.dumps({"leaf": {"files": ["leaf.v"]}, "topc": {"files": ["top.v"]}})
    )
    ann = {
        "sgdc": {
            "sync_cell": [],
            "reset_synchronizer": [],
            "set_case_analysis": [],
            "quasi_static": [],
        },
        "sdc": {
            "create_generated_clock": [],
            "set_multicycle_path": [],
            "set_false_path": [],
        },
    }
    (tmp_path / "constraint-annotations.json").write_text(
        json.dumps({"leaf": ann, "topc": ann})
    )
    verdict, rc = post_verdict(
        tmp_path / "manifest.json",
        "top",
        tmp_path / "reaped-children.json",  # absent
        tmp_path,  # workdir: both sidecars present and valid
    )
    assert rc == 1
    assert "reaped-children.json" in verdict["fail_reason"]
    assert {a["path"] for a in verdict["artifacts"]} == {
        "leaf.v",
        "top.v",
        "rtl-files.json",
        "constraint-annotations.json",
    }


def test_pre_phase_passes_pure_top_manifest_only(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "module": "top",
                "children": [
                    {"name": "leaf", "rtl_modules": ["leaf_m"]},
                    {"name": "topc", "rtl_modules": ["top"]},
                ],
            }
        )
    )
    assert _coverage(tmp_path, "top") == ("pass", None)
