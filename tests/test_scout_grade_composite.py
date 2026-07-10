"""Stage-1 composite + grade (design §1 composite table): 0.25V+0.25Q+0.20G+0.15D+0.15M,
then A/B/C/D/F bands; penalty applied to composite; vetoed -> suppressed."""
from agentcy import scout_grade as sg


def test_composite_weights():
    # Stage-1.5 weights: 0.25 V + 0.25 Q + 0.20 G + 0.15 D + 0.15 M
    c = sg.composite(v=80.0, q=80.0, g=80.0, d=80.0, m=80.0, penalty=0)
    assert c == 80.0
    # all-weight sanity: V+Q only (100 each), rest 0 -> 0.25*100 + 0.25*100 = 50
    c2 = sg.composite(v=100.0, q=100.0, g=0.0, d=0.0, m=0.0, penalty=0)
    assert c2 == 50.0
    # G alone at 100, rest 0 -> 0.20*100 = 20
    c3 = sg.composite(v=0.0, q=0.0, g=100.0, d=0.0, m=0.0, penalty=0)
    assert c3 == 20.0


def test_penalty_subtracts_and_floors_at_zero():
    assert sg.composite(v=50.0, q=50.0, g=50.0, d=50.0, m=50.0, penalty=-15) == 35.0
    assert sg.composite(v=5.0, q=5.0, g=5.0, d=5.0, m=5.0, penalty=-15) == 0.0  # floored


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
