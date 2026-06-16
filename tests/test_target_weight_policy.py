from app.target_weight_policy import TargetWeightPolicy, build_equal_weight_targets, normalize_target_weights


def test_build_equal_weight_targets_deduplicates_and_caps_symbols():
    targets = build_equal_weight_targets(
        ["000001.SZ", "000001.SZ", "600000.SH", "300001.SZ"],
        TargetWeightPolicy(max_symbols=2, gross_exposure=0.6),
    )

    assert targets == {"000001.SZ": 0.3, "600000.SH": 0.3}


def test_build_equal_weight_targets_returns_empty_when_weight_too_small():
    targets = build_equal_weight_targets(
        ["000001.SZ", "600000.SH", "300001.SZ"],
        TargetWeightPolicy(max_symbols=3, gross_exposure=0.02, min_weight=0.01),
    )

    assert targets == {}


def test_normalize_target_weights_caps_total_and_drops_invalid_values():
    targets = normalize_target_weights(
        {"600000.SH": 0.8, "000001.SZ": 0.4, "bad": -1.0, "": 0.2},
        max_total=0.9,
    )

    assert targets == {"000001.SZ": 0.3, "600000.SH": 0.6}
