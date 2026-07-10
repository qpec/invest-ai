"""Inline-keyboard JSON for job-minted asks (tg-spec §3.1 grammar). Alert keyboards are
built by render/alert.py (P5); these are the Q/F/V/N keyboards that ride job outputs."""
import json


def _kb(rows):
    return json.dumps({"inline_keyboard": rows})


def q_keyboard(ask_id: str) -> str:
    """§3.2: [Yes][No][Can't verify]."""
    return _kb([[{"text": "Yes", "callback_data": f"trig:yes:{ask_id}"},
                 {"text": "No", "callback_data": f"trig:no:{ask_id}"},
                 {"text": "Can't verify", "callback_data": f"trig:cant:{ask_id}"}]])


def reaff_keyboard(ask_id: str, *, field: str = "conviction") -> str:
    """§3.5 step 1: [Still …][Change…] — the daemon advances the 3-step sequence."""
    return _kb([[{"text": "Unchanged", "callback_data": f"reaff:set:{ask_id}:{field}:same"},
                 {"text": "Change…", "callback_data": f"reaff:set:{ask_id}:{field}:change"}]])


def v_keyboard(ask_id: str) -> str:
    """§3.10a: verdict follow-up."""
    return _kb([[{"text": "Journal: advice rejected", "callback_data": f"vfu:reject:{ask_id}"}],
                [{"text": "Move to WATCH", "callback_data": f"vfu:watch:{ask_id}"}]])


def circle_note_keyboard(ask_id: str) -> str:
    """§3.9: the one zero-consequence free-text invitation."""
    return _kb([[{"text": "Add a circle note", "callback_data": f"sys:note:{ask_id}"}]])
