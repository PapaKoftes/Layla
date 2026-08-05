"""RED-TEAM regression: the Character Lab modal became UNCLOSABLE. renderCharacterLab() overwrites
#character-lab-container.innerHTML, which destroyed the only close button (#charlab-close-btn, static
in index.html), and openCharacterLab() wired no Escape/backdrop — so once opened it could only be
dismissed by reloading the page. Source-level guard (no JS unit-test harness in this suite)."""
from pathlib import Path

CC = Path(__file__).resolve().parent.parent / "ui" / "components" / "character-creator.js"


def test_render_reincludes_the_close_button():
    src = CC.read_text(encoding="utf-8")
    # renderCharacterLab must emit a close control into the innerHTML it writes (it destroys the static one)
    assert 'id="charlab-close-btn"' in src and 'data-action="closeCharacterLab"' in src, \
        "renderCharacterLab must re-include the close button it overwrites"


def test_open_wires_escape_and_backdrop_close():
    src = CC.read_text(encoding="utf-8")
    assert "_onCharLabKeydown" in src and "addEventListener('keydown', _onCharLabKeydown, true)" in src, \
        "openCharacterLab must add a document-level Escape handler"
    assert "_onCharLabBackdrop" in src and "closeCharacterLab()" in src, \
        "backdrop click must close the lab"


def test_close_removes_its_listeners_no_leak():
    src = CC.read_text(encoding="utf-8")
    assert "removeEventListener('keydown', _onCharLabKeydown, true)" in src, \
        "closeCharacterLab must remove the Escape handler (no listener leak across opens)"
