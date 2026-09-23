"""Part M: robust statistics of the historical OTA shares (pure, no outlier removal, Decimal)."""

from decimal import Decimal

from app.modules.intelligence.distribution.statistics import median, percentile, summarize


def test_median_of_an_odd_sample_is_the_middle_value() -> None:
    assert median([Decimal(10), Decimal(30), Decimal(20)]) == Decimal(20)


def test_median_of_an_even_sample_is_the_mean_of_the_two_middle_values() -> None:
    assert median([Decimal(10), Decimal(20), Decimal(30), Decimal(40)]) == Decimal(25)


def test_p25_by_linear_interpolation() -> None:
    values = [Decimal(v) for v in (10, 20, 30, 40, 50)]
    # position = (5-1)*0.25 = 1 -> exactly index 1 -> 20
    assert percentile(values, Decimal("0.25")) == Decimal(20)


def test_p75_by_linear_interpolation() -> None:
    values = [Decimal(v) for v in (10, 20, 30, 40)]
    # position = (4-1)*0.75 = 2.25 -> between index 2 (30) and 3 (40)
    assert percentile(values, Decimal("0.75")) == Decimal("32.5")


def test_iqr_is_p75_minus_p25() -> None:
    values = [Decimal(v) for v in (10, 20, 30, 40, 50)]
    stats = summarize(values)
    assert stats.iqr == stats.p75 - stats.p25


def test_upper_fence_is_p75_plus_1_5_times_iqr() -> None:
    values = [Decimal(v) for v in (10, 20, 30, 40, 50)]
    stats = summarize(values)
    assert stats.upper_fence == stats.p75 + Decimal("1.5") * stats.iqr


def test_no_outlier_is_ever_removed() -> None:
    values = [Decimal(v) for v in (40, 42, 41, 43, 500)]  # one wild outlier
    stats = summarize(values)
    # The outlier still participates in the median/percentile computation (position-based),
    # never dropped from the sample before the statistics are computed.
    assert stats.median == Decimal(42)  # middle of the sorted 5-value sample, outlier included


def test_statistics_stay_at_full_decimal_precision() -> None:
    values = [Decimal(v) for v in (10, 20, 30)]
    stats = summarize(values)
    assert isinstance(stats.median, Decimal)
    assert isinstance(stats.p25, Decimal)
    assert isinstance(stats.upper_fence, Decimal)
