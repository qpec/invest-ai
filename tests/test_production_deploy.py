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


def test_publication_is_verified_against_the_live_page():
    """2026-08-08 incident. The publisher targeted bot/site while GitHub Pages served
    main/docs, so every run "succeeded" while the public page went months stale —
    nothing in the pipeline ever looked at the site, so nothing could notice.

    A push proves bytes left the machine; only reading the page back proves
    publication. The run must fetch SCOUT_SITE_URL, look for the snapshot id it just
    built, and refuse to record the publication if it cannot see it — which catches the
    branch mismatch and every other fail-open mode (Pages off, stuck deploy, stale CDN).
    """
    text = read("deploy/local/scout-production.sh")
    assert "SCOUT_SITE_URL" in text
    assert "snapshot_id" in text                       # what it looks for
    assert "curl" in text and "grep -qF" in text       # how it looks
    assert "PUBLISH VERIFICATION FAILED" in text

    # The check must GATE mark-published: recording a publication the world cannot see
    # is exactly the failure this exists to prevent.
    assert text.index("PUBLISH VERIFICATION FAILED") < text.index("mark-published")
    # ...and it must be able to fail the run, not merely warn.
    verify = text[text.index("PUBLISH VERIFICATION FAILED"):text.index("mark-published")]
    assert "exit 1" in verify


def test_the_site_url_is_required_configuration():
    """An unset URL must stop the run at the top, not silently skip verification."""
    text = read("deploy/local/scout-production.sh")
    assert ': "${SCOUT_SITE_URL:?' in text
    environment = read("deploy/local/scout-production.env.example")
    assert "SCOUT_SITE_URL=" in environment
    assert "SCOUT_SITE_BRANCH=" in environment


def test_the_publish_branch_matches_what_pages_serves():
    """The example config and the workflow comment must agree on the served branch.
    They disagreed for months, which is what caused the incident."""
    environment = read("deploy/local/scout-production.env.example")
    assert "SCOUT_SITE_BRANCH=main" in environment
    workflow = read(".github/workflows/pages.yml")
    assert "main /docs" in workflow and "not bot/site" in workflow
