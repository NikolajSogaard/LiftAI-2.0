import os
from agent_system import knowledge


def _write(d, slug, frontmatter, body):
    os.makedirs(os.path.join(d, "subjects"), exist_ok=True)
    with open(os.path.join(d, "subjects", f"{slug}.md"), "w", encoding="utf-8") as f:
        f.write(f"---\n{frontmatter}\n---\n\n{body}\n")


def test_returns_body_without_frontmatter(tmp_path):
    d = str(tmp_path)
    _write(d, "effort", "subject: effort\nmerged: [x]", "# Effort\n\nTrain hard.")
    out = knowledge.get_subject_context(["effort"], brain_dir=d)
    assert "Train hard." in out
    assert "subject: effort" not in out      # frontmatter hidden from agents
    assert "merged:" not in out


def test_concatenates_multiple_and_skips_missing(tmp_path):
    d = str(tmp_path)
    _write(d, "effort", "subject: effort", "Effort body.")
    _write(d, "volume", "subject: volume", "Volume body.")
    out = knowledge.get_subject_context(["effort", "nope", "volume"], brain_dir=d)
    assert "Effort body." in out and "Volume body." in out


def test_returns_empty_when_none_resolve(tmp_path):
    out = knowledge.get_subject_context(["ghost"], brain_dir=str(tmp_path))
    assert out == ""


def _write_program(d, slug, goal, split, days, level, body):
    os.makedirs(os.path.join(d, "programs"), exist_ok=True)
    fm = (f"type: example-program\ngoal: {goal}\nsplit: {split}\n"
          f"days_per_week: {days}\nlevel: {level}")
    with open(os.path.join(d, "programs", f"{slug}.md"), "w", encoding="utf-8") as f:
        f.write(f"---\n{fm}\n---\n\n{body}\n")


def test_example_program_matches_by_request(tmp_path):
    d = str(tmp_path)
    _write_program(d, "ul4", "hypertrophy", "upper-lower", 4, "all", "UL FOUR BODY")
    _write_program(d, "ppl6", "powerbuilding", "ppl", 6, "all", "PPL SIX BODY")
    out = knowledge.get_example_programs("I want a 6 day PPL powerbuilding split", brain_dir=d)
    assert "PPL SIX BODY" in out and "UL FOUR BODY" not in out
    assert "type: example-program" not in out      # frontmatter stripped


def test_example_returns_a_default_with_no_signal(tmp_path):
    d = str(tmp_path)
    _write_program(d, "ul4", "hypertrophy", "upper-lower", 4, "all", "UL FOUR BODY")
    out = knowledge.get_example_programs("", brain_dir=d)
    assert "UL FOUR BODY" in out      # a template still surfaces


def test_example_returns_empty_when_no_programs(tmp_path):
    assert knowledge.get_example_programs("anything", brain_dir=str(tmp_path)) == ""
