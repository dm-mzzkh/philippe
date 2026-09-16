"""Adapter helpers that need the bot extra (aiogram). Skipped if absent."""

from hashlib import sha256

import pytest

pytest.importorskip("aiogram")


class FakeHydrus:
    """In-memory HydrusClient double."""
    def __init__(self):
        self._store: dict[str, bytes] = {}
        self._tags: dict[str, list[str]] = {}

    def upload(self, blob: bytes) -> str:
        h = sha256(blob).hexdigest()
        self._store[h] = blob
        return h

    def download(self, file_hash: str) -> bytes:
        return self._store[file_hash]

    def thumbnail(self, file_hash: str) -> bytes:
        return self._store[file_hash]

    def tag(self, file_hash: str, tags: list[str]) -> None:
        self._tags[file_hash] = list(tags)


def test_persist_images_uploads_to_hydrus_and_swaps_file_ids():
    import asyncio

    from philippe._telegram import Runner
    from philippe.core import FieldSpec, FormSpec, Session

    blobs = {"fileA": b"\x89PNGaaa", "fileB": b"\xff\xd8bbb"}

    class FakeBot:
        async def download(self, fid):
            class Buf:
                def read(self):
                    return blobs[fid]
            return Buf()

    class FakeMessage:
        bot = FakeBot()

    class CapSink:
        def save(self, *a):
            pass

    hydrus = FakeHydrus()
    runner = Runner(forms={}, sink=CapSink(), hydrus_client=hydrus)
    form = FormSpec(name="p", title="P", table="t",
                    fields=[FieldSpec(key="pics", type="photos", label="Pics")])
    session = Session(form=form)
    record = {"pics": ["fileA", "fileB"]}

    asyncio.run(runner._persist_images(FakeMessage(), session, record))

    expected_hashes = [sha256(blobs["fileA"]).hexdigest(),
                       sha256(blobs["fileB"]).hexdigest()]
    assert record["pics"] == expected_hashes
    assert hydrus._store[expected_hashes[0]] == blobs["fileA"]
    assert hydrus._store[expected_hashes[1]] == blobs["fileB"]


def test_persist_images_applies_tags_from_field_spec():
    import asyncio

    from philippe._telegram import Runner
    from philippe.core import FieldSpec, FormSpec, Session

    class FakeBot:
        async def download(self, fid):
            class Buf:
                def read(self):
                    return b"data"
            return Buf()

    class FakeMessage:
        bot = FakeBot()

    class CapSink:
        def save(self, *a):
            pass

    hydrus = FakeHydrus()
    runner = Runner(forms={}, sink=CapSink(), hydrus_client=hydrus)
    form = FormSpec(name="p", title="P", table="t", fields=[
        FieldSpec(key="pics", type="photos", label="Pics",
                  tags=["food", "place", "name"]),
        FieldSpec(key="name", type="text", label="Name"),
    ])
    session = Session(form=form)
    session.answers = {"name": "McDuck"}
    record = {"pics": ["fileA", "fileB"]}

    asyncio.run(runner._persist_images(FakeMessage(), session, record))

    # Both images get tags: literal "food", "place", and resolved "name" → "McDuck"
    for h in record["pics"]:
        assert hydrus._tags[h] == ["food", "place", "McDuck"]


def test_persist_images_literal_tag_when_no_matching_field():
    import asyncio

    from philippe._telegram import Runner
    from philippe.core import FieldSpec, FormSpec, Session

    class FakeBot:
        async def download(self, fid):
            class Buf:
                def read(self):
                    return b"data"
            return Buf()

    class FakeMessage:
        bot = FakeBot()

    class CapSink:
        def save(self, *a):
            pass

    hydrus = FakeHydrus()
    runner = Runner(forms={}, sink=CapSink(), hydrus_client=hydrus)
    form = FormSpec(name="p", title="P", table="t", fields=[
        FieldSpec(key="pics", type="photos", label="Pics", tags=["static_tag"]),
    ])
    session = Session(form=form)
    record = {"pics": ["fileA"]}

    asyncio.run(runner._persist_images(FakeMessage(), session, record))

    assert hydrus._tags[record["pics"][0]] == ["static_tag"]


def test_persist_images_skips_when_no_hydrus():
    import asyncio

    from philippe._telegram import Runner
    from philippe.core import FieldSpec, FormSpec, Session

    class CapSink:
        def save(self, *a):
            pass

    runner = Runner(forms={}, sink=CapSink(), hydrus_client=None)
    form = FormSpec(name="p", title="P", table="t",
                    fields=[FieldSpec(key="pics", type="photos", label="Pics")])
    session = Session(form=form)
    record = {"pics": ["fileA"]}

    # Should not raise — just return silently.
    asyncio.run(runner._persist_images(None, session, record))
    assert record["pics"] == ["fileA"]  # unchanged (no download happened)


def test_show_row_images_downloads_from_hydrus():
    import asyncio

    from philippe._telegram import Runner
    from philippe.core import QueryAction

    hydrus = FakeHydrus()
    hydrus._store["h1"] = b"IMG1"
    hydrus._store["h2"] = b"IMG2"

    sent = {}

    class FakeBot:
        async def send_media_group(self, chat_id, media):
            sent["media"] = media

    class FakeMessage:
        bot = FakeBot()
        chat = type("C", (), {"id": 1})()

        async def answer(self, *a, **k):
            sent["answer"] = a

    runner = Runner(forms={}, sink=None, hydrus_client=hydrus)
    action = QueryAction(show_images="photos")
    runner._actions[1] = (action, [{"photos": ["h1", "h2"]}])

    asyncio.run(runner.show_row_images(FakeMessage(), 0))
    assert len(sent["media"]) == 2 and "answer" not in sent


def test_show_row_images_no_hashes_answers_empty():
    import asyncio

    from philippe._telegram import Runner
    from philippe.core import QueryAction

    hydrus = FakeHydrus()

    class FakeMessage:
        chat = type("C", (), {"id": 1})()

        async def answer(self, text):
            self.said = text

    runner = Runner(forms={}, sink=None, hydrus_client=hydrus)
    runner._actions[1] = (QueryAction(show_images="photos"), [{"photos": []}])
    msg = FakeMessage()
    asyncio.run(runner.show_row_images(msg, 0))
    assert "📭" in msg.said


def test_show_row_images_no_hydrus_warns():
    import asyncio

    from philippe._telegram import Runner
    from philippe.core import QueryAction

    class FakeMessage:
        chat = type("C", (), {"id": 1})()

        async def answer(self, text):
            self.said = text

    runner = Runner(forms={}, sink=None, hydrus_client=None)
    runner._actions[1] = (QueryAction(show_images="photos"), [{"photos": ["h1"]}])
    msg = FakeMessage()
    asyncio.run(runner.show_row_images(msg, 0))
    assert "Hydrus" in msg.said


# --- hourly check-in: save_hour_reply ----------------------------------------

import datetime as dt

PERIOD = dt.datetime(2026, 9, 16, 1, tzinfo=dt.timezone.utc)


class _HourSink:
    """Captures save()/insert()/exec(); models the overwrite flow."""
    def __init__(self):
        self.saved = []
        self.inserted = []
        self.execed = []
        self.periods = set()   # periods that already have an hour_log row

    def save(self, form, record):
        self.saved.append(dict(record, table=form.table))
        self.periods.add(record["period"])

    def insert(self, table, record):
        self.inserted.append(dict(record, table=table))

    def exec(self, sql, params=None):
        self.execed.append((sql, params))
        period = params[-1]
        if sql.startswith("UPDATE"):
            if period in self.periods:
                self.periods.add(period)
                return [(period, "id")]
            return None
        self.periods.discard(period)   # DELETE hour_photos
        return None


def _hour_form():
    from philippe.core import ContextColumn, FieldSpec, FormSpec
    return FormSpec(name="hour", title="Что делал этот час?", table="hour_log",
                    context=[ContextColumn(column="chat_id", source="chat_id")],
                    fields=[FieldSpec(key="period", type="text", label="Period"),
                            FieldSpec(key="note", type="text", label="note")])


class _HourMessage:
    def __init__(self, text=None, caption=None, photo=None, chat=42):
        self.text = text
        self.caption = caption
        self.photo = photo or []
        self.chat = type("C", (), {"id": chat})()
        self.from_user = None
        self.replied = []

    async def answer(self, text):
        self.replied.append(text)


class _FakePhoto:
    def __init__(self, file_id):
        self.file_id = file_id


def test_save_hour_reply_text_only():
    import asyncio
    from philippe._telegram import Runner

    sink = _HourSink()
    runner = Runner(forms={"hour": _hour_form()}, sink=sink, hydrus_client=None)
    msg = _HourMessage(text="кодил 60 минут")
    asyncio.run(runner.save_hour_reply(msg, PERIOD))

    assert sink.saved == [{"period": PERIOD, "note": "кодил 60 минут", "chat_id": 42,
                           "table": "hour_log"}]
    assert sink.inserted == []
    assert "Записал" in msg.replied[0] and "кодил 60 минут" in msg.replied[0]


def test_save_hour_reply_photo_only_no_hour_row():
    import asyncio
    from philippe._telegram import Runner

    sink = _HourSink()
    runner = Runner(forms={"hour": _hour_form()}, sink=sink, hydrus_client=None)
    msg = _HourMessage(photo=[_FakePhoto("fileXYZ")])
    asyncio.run(runner.save_hour_reply(msg, PERIOD))

    assert sink.saved == []
    assert sink.inserted == [{"period": PERIOD, "hash": "fileXYZ", "chat_id": 42,
                              "table": "hour_photos"}]
    assert "📷 1" in msg.replied[0]


def test_save_hour_reply_text_plus_photo_uses_hydrus_hash():
    import asyncio
    from philippe._telegram import Runner

    blob = b"\x89PNGphoto"

    class FakeBot:
        async def download(self, fid):
            class Buf:
                def read(self):
                    return blob
            return Buf()

    class Msg(_HourMessage):
        bot = FakeBot()

    sink = _HourSink()
    runner = Runner(forms={"hour": _hour_form()}, sink=sink,
                    hydrus_client=FakeHydrus())
    msg = Msg(text="думал о проекте", caption=None,
              photo=[_FakePhoto("fileU")])
    asyncio.run(runner.save_hour_reply(msg, PERIOD))

    assert len(sink.saved) == 1 and sink.saved[0]["table"] == "hour_log"
    assert sink.inserted and sink.inserted[0]["table"] == "hour_photos"
    assert sink.inserted[0]["hash"] == sha256(blob).hexdigest()  # not fileU


def test_save_hour_reply_no_caption_photo_falls_back_to_file_id():
    import asyncio
    from philippe._telegram import Runner

    sink = _HourSink()
    runner = Runner(forms={"hour": _hour_form()}, sink=sink, hydrus_client=None)
    msg = _HourMessage(caption="только подпись", photo=[_FakePhoto("fid9")])
    asyncio.run(runner.save_hour_reply(msg, PERIOD))
    assert sink.saved[0]["note"] == "только подпись"
    assert sink.inserted[0]["hash"] == "fid9"


def test_save_hour_reply_empty_reply_asks_again():
    import asyncio
    from philippe._telegram import Runner

    sink = _HourSink()
    runner = Runner(forms={"hour": _hour_form()}, sink=sink, hydrus_client=None)
    msg = _HourMessage(text="   ")
    asyncio.run(runner.save_hour_reply(msg, PERIOD))
    assert sink.saved == [] and sink.inserted == []
    assert "нужен текст или фото" in msg.replied[0]


def test_save_hour_reply_overwrites_existing_period():
    # second reply to same question: UPDATE note, reset photos, no new row
    import asyncio
    from philippe._telegram import Runner

    sink = _HourSink()
    sink.periods.add(PERIOD)   # row exists from the first reply
    runner = Runner(forms={"hour": _hour_form()}, sink=sink, hydrus_client=None)
    msg = _HourMessage(text="передумал: смотрел кино",
                       photo=[_FakePhoto("newFid")])
    asyncio.run(runner.save_hour_reply(msg, PERIOD))

    sqls = " ".join(sql for sql, _ in sink.execed)
    assert "UPDATE hour_log" in sqls and "DELETE FROM hour_photos" in sqls
    assert sink.saved == []                       # no second INSERT
    assert [r["hash"] for r in sink.inserted] == ["newFid"]


def test_save_hour_reply_photo_only_keeps_old_note_but_resets_photos():
    import asyncio
    from philippe._telegram import Runner

    sink = _HourSink()
    sink.periods.add(PERIOD)
    runner = Runner(forms={"hour": _hour_form()}, sink=sink, hydrus_client=None)
    msg = _HourMessage(photo=[_FakePhoto("pic")])   # no text
    asyncio.run(runner.save_hour_reply(msg, PERIOD))

    sqls = " ".join(sql for sql, _ in sink.execed)
    assert "UPDATE hour_log" not in sqls           # note untouched
    assert "DELETE FROM hour_photos" in sqls
    assert not sink.saved


def test_start_shows_host():
    from philippe._telegram import Runner
    assert Runner(forms={}, sink=None).host  # always truthy via env/hostname


# --- hourly check-in: stateless question parse --------------------------------

def _question(text, from_bot=True):
    class _U: is_bot = from_bot
    m = _HourMessage.__new__(_HourMessage)
    m.text = text; m.from_user = _U if from_bot else None
    return m


def test_period_from_question_parses_date_and_hours():
    import datetime as dt
    from philippe._telegram import _period_from_question, _local_now

    now = _local_now()
    y, mo, d = now.year, now.month, now.day
    per = _period_from_question(
        _question(f"❓ Что делал за {d:02d}.{mo:02d} 14:00–15:00?"))
    assert (per.day, per.month, per.hour) == (d, mo, 14)

    # year rollover: a 31.12 23:00–00:00 question answered on Jan 1st
    old = dt.date(y - 1, 12, 31)
    per = _period_from_question(
        _question(f"❓ Что делал за {old.day:02d}.{old.month:02d} 23:00–00:00?"))
    assert (per.month, per.day, per.hour, per.year) == (12, 31, 23, y - 1)


def test_period_from_question_rejects_non_question():
    from philippe._telegram import _period_from_question
    assert _period_from_question(_question("обычное сообщение")) is None
    # echo by a human (not the bot) can't fake a period
    assert _period_from_question(
        _question("❓ Что делал за 16.09 02:00–03:00?", from_bot=False)) is None
