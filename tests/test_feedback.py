"""Feedback read from PocketBase: what each message becomes, and the page's numbers."""
import urllib.error

from server import feedback

DAY = 86400.0
NOW = 1_800_000_000.0


def created(t):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S.000Z")


def record(id_, message, t, **extra):
    return {"id": id_, "message": message, "created": created(t), "place": "game", "version": "1.3.0",
            "priority": "medium", "resolved": False, "screenshot": [], "audio": "", **extra}


class FakePocketBase(feedback.FeedbackSource):
    def __init__(self, records, fail=None):
        super().__init__("https://pb.example", "reader@example.com", "secret")
        self.records, self.fail, self.calls = records, fail, []

    def _call(self, method, path, body=None, auth=True):
        self.calls.append(path)
        if "auth-with-password" in path:
            return {"token": "T"}
        if auth:
            self._auth()
        if self.fail:
            raise self.fail
        return {"items": self.records}


def test_a_message_and_its_crash_log_are_split():
    item = feedback.normalise(record("a", "game stopped\r\n\r\n=== DEBUG LOGS ===\r\nline 1", NOW))
    assert item["message"] == "game stopped" and item["has_logs"]
    assert item["logs"] == "=== DEBUG LOGS ===\nline 1" and abs(item["t"] - NOW) < 1


def test_made_up_words_look_like_tests():
    assert feedback.looks_like_test("vijomc") and feedback.looks_like_test(" ddwztc ")
    assert not feedback.looks_like_test("Sort cards on hand") and not feedback.looks_like_test("crash")


def test_page_counts_and_tabs():
    source = FakePocketBase([
        record("new", "Add a quick game", NOW - DAY, screenshot=["s.jpg"]),
        record("high", "crash\n=== DEBUG LOGS ===\nx", NOW - 2 * DAY, priority="high"),
        record("done", "Sort cards", NOW - 10 * DAY, resolved=True),
        record("test", "vijomc", NOW - 3 * DAY),
    ])
    page = feedback.page(source, "open", "", NOW)
    k = page["kpis"]
    assert (k["open"], k["open_high"], k["week"], k["week_prev"], k["crashes"], k["shots"]) == (2, 1, 2, 1, 1, 1)
    assert (k["resolved"], k["total"], k["tests"]) == (1, 3, 1)
    assert [r["id"] for r in page["rows"]] == ["new", "high"]
    assert [r["id"] for r in feedback.page(source, "all", "", NOW)["rows"]] == ["new", "high", "done", "test"]
    assert [r["id"] for r in feedback.page(source, "all", "SORT", NOW)["rows"]] == ["done"]
    assert feedback.open_count(source) == 2
    d = feedback.detail(source, "new")
    assert d["screenshots"][0]["thumb"] == "https://pb.example/api/files/feedbacks/new/s.jpg?thumb=600x0"
    assert feedback.detail(source, "nope") is None


def test_pocketbase_is_asked_once_a_minute_and_an_old_copy_survives_an_outage():
    source = FakePocketBase([record("a", "hello there", NOW)])
    assert len(source.items()) == 1 and len(source.items()) == 1
    assert sum("records" in c for c in source.calls) == 1
    source._items_at = 0  # a minute later, PocketBase is down
    source.fail = urllib.error.URLError("down")
    assert len(source.items()) == 1 and source.error == "unreachable"


def test_not_set_up():
    source = feedback.FeedbackSource(None, None, None)
    assert source.items() == [] and source.error == "not_set_up"
    assert feedback.page(source, "open", "", NOW)["setup"] is False
