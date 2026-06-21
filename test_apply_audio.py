from scripts.apply_audio import build_source_volume_expression


def test_source_volume_stops_at_outro():
    expr, eval_frame = build_source_volume_expression(15.0, 2.0, True, 5.0, 1.0)
    assert eval_frame
    assert "lt(t,10.0)" in expr
    assert "lt(t,11.0)" in expr
    assert expr.endswith(",1.0))")


def test_source_volume_without_outro_is_flat():
    expr, eval_frame = build_source_volume_expression(15.0, 0.6, False, 5.0, 1.0)
    assert expr == "0.6"
    assert not eval_frame


if __name__ == "__main__":
    test_source_volume_stops_at_outro()
    test_source_volume_without_outro_is_flat()
