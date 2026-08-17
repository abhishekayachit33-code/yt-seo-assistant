"""Whether a planning-mode draft has enough typed input to work from.

Lives in its own module rather than app.py so it can be unit-tested --
importing app.py executes the whole Streamlit script.
"""


def is_plan_input_sufficient(script: str) -> bool:
    """Deliberately a hard gate, not a degradation path.

    Everything downstream in planning mode -- autocomplete seeds, target
    audience, keyword demand, the titles Gemini proposes -- is derived from
    the script. A title/description/tags typed without a script is not
    enough to research real search demand or judge an audience from; a
    script alone is (Gemini proposes the title itself from it).
    """
    return bool(script.strip())
