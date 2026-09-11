from __future__ import annotations


def test_settings_shows_provider_controls(monkeypatch, tmp_path):
    monkeypatch.setenv("RAB_NAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RAB_NAC_DB_PATH", str(tmp_path / "data" / "app.db"))
    monkeypatch.setenv("RAB_NAC_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("RAB_NAC_UPLOAD_DIR", str(tmp_path / "uploads"))

    from streamlit.testing.v1 import AppTest

    script = """
from modules import db
from modules import ui_system as ui
from streamlit_app import init_session, settings_page
ui.apply_page_config()
db.init_db()
init_session()
ui.inject_css()
settings_page()
"""
    app = AppTest.from_string(script, default_timeout=20).run()

    assert not app.exception
    markdown = "\n".join(str(item.value) for item in app.markdown)
    assert "AI Review Providers" in markdown
    assert any(button.label == "Test OpenAI API" for button in app.button)
    assert any(button.label == "Test Gemini Flash API" for button in app.button)
