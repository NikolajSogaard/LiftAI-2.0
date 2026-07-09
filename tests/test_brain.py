import os
from agent_system import knowledge


def _write(d, slug, body, frontmatter="subject: x\nrelated: []"):
    os.makedirs(os.path.join(d, "subjects"), exist_ok=True)
    with open(os.path.join(d, "subjects", f"{slug}.md"), "w", encoding="utf-8") as f:
        f.write(f"---\n{frontmatter}\n---\n\n{body}\n")


def test_clean_note_has_no_issues(tmp_path):
    d = str(tmp_path)
    _write(d, "effort", "# Effort\n\nTrain at 0-3 RIR.\n\n## Related\n- [[volume]]",
           frontmatter="subject: effort\nrelated: [[volume]]")
    _write(d, "volume", "# Volume\n\nMore sets, more growth (to a point).")
    assert knowledge.lint_brain(brain_dir=d) == []


def test_flags_author_name(tmp_path):
    d = str(tmp_path)
    _write(d, "effort", "# Effort\n\nNippard recommends 0-3 RIR.")
    issues = knowledge.lint_brain(brain_dir=d)
    assert any("Nippard" in i and "effort" in i for i in issues)


def test_flags_broken_wikilink(tmp_path):
    d = str(tmp_path)
    _write(d, "effort", "# Effort\n\nSee [[ghost-subject]].")
    issues = knowledge.lint_brain(brain_dir=d)
    assert any("ghost-subject" in i for i in issues)


def test_flags_missing_subject_frontmatter(tmp_path):
    d = str(tmp_path)
    _write(d, "effort", "# Effort\n\nbody", frontmatter="title: x")
    issues = knowledge.lint_brain(brain_dir=d)
    assert any("subject" in i and "effort" in i for i in issues)


def test_real_brain_passes_lint():
    """Integration guard over the committed Data/brain. Vacuous until Task 5."""
    assert knowledge.lint_brain() == []
