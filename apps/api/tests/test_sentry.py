from src.main import _scrub_pii


def test_scrub_pii_removes_display_name() -> None:
    event: dict = {"user": {"id": "abc123", "display_name": "Craig Robinson", "username": "craig"}}
    result = _scrub_pii(event, {})
    assert "display_name" not in result["user"]
    assert "username" not in result["user"]
    assert result["user"]["id"] == "abc123"


def test_scrub_pii_no_user() -> None:
    event: dict = {"message": "test error", "exception": {}}
    result = _scrub_pii(event, {})
    assert result == {"message": "test error", "exception": {}}


def test_scrub_pii_user_without_display_name() -> None:
    event: dict = {"user": {"id": "xyz"}}
    result = _scrub_pii(event, {})
    assert result["user"] == {"id": "xyz"}
