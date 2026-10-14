from sawy.insights.format import money, pct
from sawy.report.charts import _nice_ticks, axis_money


def test_money_is_readable_for_a_non_technical_reader():
    assert money(120_500_593) == "$120,5 M"
    assert money(-1_073_112) == "−$1,1 M"
    assert money(808_638) == "$808.638"


def test_pct():
    assert pct(0.35) == "35%"
    assert pct(0.033) == "3,3%"
    assert pct(-0.069) == "−6,9%"


def test_ticks_include_zero_and_cover_range():
    t = _nice_ticks(-311_000, 82_000)
    assert 0 in t and t[0] <= -311_000 and t[-1] >= 82_000
    assert axis_money(-200_000) == "−$200 mil"
