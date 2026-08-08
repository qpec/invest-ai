from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_local_wrapper_has_durable_lock_and_no_box_paths():
    text = read("deploy/local/scout-production.sh")
    assert "flock" in text
    assert "SCOUT_DB_DIR" in text
    assert "SCOUT_ARTIFACT_ROOT" in text
    assert "/opt/stock-agentcy" not in text
    assert "/var/lib/stock-agentcy" not in text


def test_timers_use_one_templated_service():
    daily = read("deploy/systemd/scout-production-daily.timer")
    weekly = read("deploy/systemd/scout-production-weekly.timer")
    service = read("deploy/systemd/scout-production@.service")
    assert "Unit=scout-production@daily.service" in daily
    assert "Unit=scout-production@weekly.service" in weekly
    assert "%i" in service
    assert "NoNewPrivileges=true" in service


def test_publisher_limits_git_payload_and_never_embeds_a_token():
    text = read("deploy/local/scout-production.sh")
    assert "add -A docs production-manifest.json" in text
    assert "x-access-token" not in text
    assert "GIT_ASKPASS" in text


def test_wrapper_verifies_staged_artifact_before_copying_it():
    text = read("deploy/local/scout-production.sh")
    verify = text.index("verify-artifact")
    copy = text.index("rsync -a --delete")
    assert verify < copy


def test_thesis_runner_pins_owner_approved_max_effort_isolated_session():
    text = read("deploy/local/scout-thesis-runner.sh")
    assert "openai/gpt-5.6-sol" in text
    assert "maximum available effort" in text
    assert "--thinking max" not in text
    assert "--session-key" in text
    assert "--timeout 3600" in text
    assert "--deliver" not in text


def test_production_wrapper_requires_and_passes_thesis_runner():
    wrapper = read("deploy/local/scout-production.sh")
    environment = read("deploy/local/scout-production.env.example")
    assert ': "${SCOUT_THESIS_RUNNER:?set SCOUT_THESIS_RUNNER}"' in wrapper
    assert '--thesis-runner "$SCOUT_THESIS_RUNNER"' in wrapper
    assert '--thesis-model "${SCOUT_THESIS_MODEL:-gpt-5.6-sol}"' in wrapper
    assert "SCOUT_THESIS_RUNNER=" in environment
    assert "SCOUT_THESIS_MODEL=gpt-5.6-sol" in environment
