from plan_input import is_plan_input_sufficient


def test_specific_title_alone_is_enough():
    assert is_plan_input_sufficient("MBA in Germany for Indian students", "", "", [])


def test_vague_title_alone_is_refused():
    # The exact failure this gate exists for: enough to submit, nowhere near
    # enough to research demand or judge an audience from.
    assert not is_plan_input_sufficient("my new video", "", "", [])
    assert not is_plan_input_sufficient("a video about this", "", "", [])


def test_filler_words_do_not_count_toward_the_title_bar():
    # Five words, but every one of them is filler.
    assert not is_plan_input_sufficient("the new video about my", "", "", [])


def test_a_description_rescues_a_vague_title():
    assert is_plan_input_sufficient("my new video", "A guide to the APS certificate", "", [])


def test_a_script_rescues_a_vague_title():
    assert is_plan_input_sufficient("my new video", "", "Today we talk about the APS process", [])


def test_tags_rescue_a_vague_title():
    assert is_plan_input_sufficient("my new video", "", "", ["aps certificate"])


def test_completely_empty_input_is_refused():
    assert not is_plan_input_sufficient("", "", "", [])


def test_whitespace_only_input_is_refused():
    assert not is_plan_input_sufficient("   ", "   ", "   ", [])
