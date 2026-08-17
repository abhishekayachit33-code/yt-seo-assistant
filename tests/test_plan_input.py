from plan_input import is_plan_input_sufficient


def test_script_alone_is_enough():
    assert is_plan_input_sufficient("Today we talk about the APS process for Germany")


def test_no_script_is_refused():
    assert not is_plan_input_sufficient("")


def test_whitespace_only_script_is_refused():
    assert not is_plan_input_sufficient("   ")
