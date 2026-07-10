"""Stage-1 composite + grade (design §1 composite table): 0.30V+0.30Q+0.20D+0.20M,
then A/B/C/D/F bands; penalty applied to composite; vetoed -> suppressed."""
from agentcy import scout_grade as sg


def test_composite_weights():
    c = sg.composite(v=80.0, q=80.0, d=80.0, m=80.0, penalty=0)
    assert c == 80.0
    c2 = sg.composite(v=100.0, q=100.0, d=0.0, m=0.0, penalty=0)
    assert c2 == 60.0   # 0.30*100 + 0.30*100 + 0 + 0


def test_penalty_subtracts_and_floors_at_zero():
    assert sg.composite(v=50.0, q=50.0, d=50.0, m=50.0, penalty=-15) == 35.0
    assert sg.composite(v=5.0, q=5.0, d=5.0, m=5.0, penalty=-15) == 0.0  # floored


def test_grade_bands():
    assert sg.grade_letter(80.0) == "A"
    assert sg.grade_letter(79.9) == "B"
    assert sg.grade_letter(65.0) == "B"
    assert sg.grade_letter(64.9) == "C"
    assert sg.grade_letter(50.0) == "C"
    assert sg.grade_letter(49.9) == "D"
    assert sg.grade_letter(35.0) == "D"
    assert sg.grade_letter(34.9) == "F"


def test_pillar_score_drops_missing_legs_not_zero():
    # a pillar with one missing leg averages only the present legs
    assert sg.pillar_score([60.0, None, 80.0]) == 70.0
    assert sg.pillar_score([None, None]) is None
