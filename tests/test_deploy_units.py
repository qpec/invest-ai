"""The unit files are the deployment contract; these assertions pin the §1.2 load-bearing
lines the review flagged as convictions (not style). If a line here changes, the review
finding it encodes must be re-litigated first."""
from pathlib import Path

D = Path(__file__).resolve().parents[1] / "deploy" / "systemd"
UNITS = [
    "agentcy-bot.service", "agentcy-daily.service", "agentcy-daily.timer",
    "agentcy-weekly.service", "agentcy-weekly.timer", "agentcy-quarterly.service",
    "agentcy-quarterly.timer", "agentcy-backup.service", "agentcy-backup.timer",
    "agentcy-event.service", "agentcy-event.path", "agentcy-fail@.service",
]


def _read(name):
    return (D / name).read_text(encoding="utf-8")


def test_all_units_exist():
    for u in UNITS:
        assert (D / u).exists(), u


def test_daemon_watchdog_startlimit_and_sandbox():
    s = _read("agentcy-bot.service")
    assert "Type=notify" in s and "WatchdogSec=90" in s
    assert "Restart=always" in s and "RestartSec=10" in s
    assert "StartLimitIntervalSec=600" in s and "StartLimitBurst=5" in s   # §1.2 conviction
    assert "OnFailure=agentcy-fail@%n.service" in s
    assert "ProtectSystem=strict" in s and "ReadWritePaths=/var/lib/stock-agentcy" in s
    assert "ExecStart=/opt/stock-agentcy/.venv/bin/agentcy bot" in s


def test_oneshot_jobs_have_30min_timeout_and_network_online():
    for u in ("agentcy-daily.service", "agentcy-weekly.service",
              "agentcy-quarterly.service", "agentcy-event.service", "agentcy-backup.service"):
        s = _read(u)
        assert "Type=oneshot" in s, u
        assert "TimeoutStartSec=30min" in s, u                              # §1.2 conviction
        assert "OnFailure=agentcy-fail@%n.service" in s, u


def test_daily_service_execstart_and_mpl_backend():
    s = _read("agentcy-daily.service")
    assert "ExecStart=/opt/stock-agentcy/.venv/bin/agentcy run daily" in s
    assert "Environment=MPLBACKEND=Agg" in s
    assert "Wants=network-online.target" in s and "After=network-online.target" in s


def test_timers_calendars_and_persistent():
    assert "OnCalendar=*-*-* 07:00:00 Europe/Amsterdam" in _read("agentcy-daily.timer")
    assert "Persistent=true" in _read("agentcy-daily.timer")
    assert "OnCalendar=Sat 08:00 Europe/Amsterdam" in _read("agentcy-weekly.timer")
    assert "OnCalendar=*-01,04,07,10-01 08:30 Europe/Amsterdam" in _read("agentcy-quarterly.timer")
    assert "OnCalendar=*-*-* 03:30:00 Europe/Amsterdam" in _read("agentcy-backup.timer")
    for t in ("agentcy-daily.timer", "agentcy-weekly.timer",
              "agentcy-quarterly.timer", "agentcy-backup.timer"):
        assert "Persistent=true" in _read(t)


def test_backup_service_has_second_disk_rwpath():                          # §1.2 deviation 1
    assert "ReadWritePaths=/mnt/agentcy-backup" in _read("agentcy-backup.service")
    assert "ExecStart=/opt/stock-agentcy/.venv/bin/python -m agentcy.jobs.backup" in _read("agentcy-backup.service")


def test_event_service_has_its_own_startlimit():                           # §1.2 deviation 2
    s = _read("agentcy-event.service")
    assert "StartLimitIntervalSec=600" in s and "StartLimitBurst=5" in s
    assert "ExecStart=/opt/stock-agentcy/.venv/bin/agentcy run event" in s


def test_event_path_watches_the_spool():
    s = _read("agentcy-event.path")
    assert "DirectoryNotEmpty=/var/lib/stock-agentcy/spool/events" in s
    assert "Unit=agentcy-event.service" in s


def test_fail_notifier_is_templated_and_calls_the_script():
    s = _read("agentcy-fail@.service")
    assert "ExecStart=/opt/stock-agentcy/.venv/bin/python /opt/stock-agentcy/tools/fail_notify.py %i" in s
    assert "EnvironmentFile=/etc/stock-agentcy/agentcy.env" in s
