from plancheck.core.geometry import flip_point, flip_y, pt_to_ft


def test_flip_y_origin():
    height = 1684.0
    # PyMuPDF (0, 0) is top-left. Sheet space origin is bottom-left.
    assert flip_y(0.0, height) == height
    assert flip_y(height, height) == 0.0
    assert flip_y(height / 2, height) == height / 2


def test_flip_point_uses_flip_y():
    assert flip_point(10.0, 20.0, 100.0) == (10.0, 80.0)


def test_pt_to_ft():
    assert abs(pt_to_ft(412.0 + 18.0 * 15.08, 412.0, 18.0) - 15.08) < 1e-9
