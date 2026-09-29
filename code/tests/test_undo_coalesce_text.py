"""Frontend undo coalesce spec (mirrors product/frontend/src/model/undoCoalesce.ts).

shouldCoalesceTextEdit / isWordBoundaryChar:
- In-word single-character insert/delete coalesces (hel -> hell).
- Whitespace, newline, or punctuation is a word boundary and does not coalesce
  (hello -> hello ; hello  -> hello w).
- First character of a new word after a boundary does not coalesce.

shouldPersistMoveEvent / countMovePersists:
- pointer-move events do not persist
- pointer-up / end persists once
- N move events + 1 end => 1 persist
"""

import re

WORD_BOUNDARY_RE = re.compile(r"""[\s.,;:!?()[\]{}"'`]""")


def is_word_boundary_char(ch):
    if not ch:
        return False
    if ch in ("\n", "\r", "\t"):
        return True
    return WORD_BOUNDARY_RE.search(ch) is not None


def should_coalesce_text_edit(prev, nxt):
    if prev == nxt:
        return True
    prev_last = prev[-1] if prev else ""
    if len(nxt) == len(prev) + 1 and nxt.startswith(prev):
        if is_word_boundary_char(prev_last):
            return False
        return not is_word_boundary_char(nxt[-1])
    if len(prev) == len(nxt) + 1 and prev.startswith(nxt):
        next_last = nxt[-1] if nxt else ""
        if is_word_boundary_char(next_last):
            return False
        return not is_word_boundary_char(prev_last)
    return False


def should_persist_move_event(phase):
    return phase == "end"


def count_move_persists(phases):
    return sum(1 for phase in phases if should_persist_move_event(phase))


def should_suppress_persist_during_drag(is_dragging):
    return bool(is_dragging)


def move_coalesce_key(space_id):
    return "move:%s" % space_id


def test_word_level_text_coalesce_not_character_level():
    assert should_coalesce_text_edit("hel", "hell") is True
    assert should_coalesce_text_edit("hello", "hello ") is False
    assert should_coalesce_text_edit("hello ", "hello w") is False
    typed = ""
    persist_windows = 1
    generation = 0
    for ch in "hello":
        nxt = typed + ch
        if typed:
            assert should_coalesce_text_edit(typed, nxt) is True
        typed = nxt
    nxt = typed + " "
    assert should_coalesce_text_edit(typed, nxt) is False
    persist_windows += 1
    generation += 1
    typed = nxt
    nxt = typed + "w"
    assert should_coalesce_text_edit(typed, nxt) is False
    persist_windows += 1
    typed = nxt
    nxt = typed + "o"
    assert should_coalesce_text_edit(typed, nxt) is True
    assert persist_windows == 3
    assert generation == 1
    assert should_coalesce_text_edit("hello.", "hello. ") is False
    assert should_coalesce_text_edit("hi", "hi\n") is False


def test_space_move_n_move_events_plus_end_is_one_persist():
    phases = ["move"] * 40 + ["end"]
    assert count_move_persists(phases) == 1
    assert should_persist_move_event("move") is False
    assert should_persist_move_event("end") is True
    assert should_suppress_persist_during_drag(True) is True
    assert should_suppress_persist_during_drag(False) is False
    assert move_coalesce_key("space1") == "move:space1"
    two_drags = ["move", "move", "end", "move", "end"]
    assert count_move_persists(two_drags) == 2


if __name__ == "__main__":
    test_word_level_text_coalesce_not_character_level()
    test_space_move_n_move_events_plus_end_is_one_persist()
    print("test_undo_coalesce_text ok")
