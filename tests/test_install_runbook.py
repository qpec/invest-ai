"""install.sh is not executed in CI (it needs root/systemd/a second disk); we assert it
CONTAINS the review-mandated provisioning steps, in a way that will trip if a step is
dropped. The one-time semantic checks (dirs, license gate, bootstrap journal) are proven
by the smoke test and the deploy-unit test; here we pin the script's own contract."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SH = (ROOT / "install.sh").read_text(encoding="utf-8")


def _has(*needles):
    for n in needles:
        assert n in SH, f"install.sh missing: {n}"


def test_creates_agentcy_user_and_state_tree():
    _has("useradd", "agentcy",
         "/var/lib/stock-agentcy/locks",
         "/var/lib/stock-agentcy/spool/tmp",
         "/var/lib/stock-agentcy/spool/events",
         "/var/lib/stock-agentcy/spool/done",
         "/var/lib/stock-agentcy/spool/failed",
         "/var/lib/stock-agentcy/archive")


def test_environmentfile_is_0600_with_the_two_secrets():
    _has("/etc/stock-agentcy/agentcy.env", "chmod 600",
         "AGENTCY_BOT_TOKEN", "AGENTCY_OWNER_CHAT_ID")


def test_inits_the_archive_repo_with_backup_remote():
    _has("git init", "/var/lib/stock-agentcy/archive",
         "git remote add backup", "/mnt/agentcy-backup")


def test_runs_the_license_gate_and_migrates():
    _has("tools/license_gate.py", "uv sync --locked", "agentcy run", )  # gate then a migrating command
    assert "license_gate.py" in SH


def test_bootstrap_journal_and_deadman_config_via_cli():
    # S0-S3 land as migration-000 seeds; the ONE install-time act is choosing the ping service:
    _has("agentcy config set deadman_ping_url", "--reason")


def test_archives_the_recovery_toolchain():
    _has("wheelhouse", "uv", "python-build-standalone")  # tarball + uv binary + wheelhouse (§12.3)


def test_verifies_units_and_enables_timers():
    _has("systemd-analyze verify", "deploy/systemd/",
         "systemctl enable", "agentcy-bot", "agentcy-daily.timer",
         "agentcy-event.path")


RB = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")


def test_runbook_has_the_deadman_rule_verbatim():
    assert "No message by 08:00" in RB and "the box is down" in RB
    assert "systemctl status 'agentcy-*'" in RB


def test_runbook_lists_quarterly_ritual_steps_0_through_6():
    for step in ("(0)", "(1)", "(2)", "(3)", "(4)", "(5)", "(6)"):
        assert step in RB, f"quarterly ritual {step} missing"
    assert "license_gate.py" in RB and "systemd-analyze verify" in RB


def test_runbook_has_yfinance_emergency_lane_and_spool_recovery_and_restore_drill():
    assert "emergency" in RB.lower() and "yfinance" in RB
    assert "reset-failed agentcy-event" in RB          # event-spool recovery line (§1.5)
    assert "spool/failed" in RB
    assert "restore drill" in RB.lower() and "integrity_check" in RB
