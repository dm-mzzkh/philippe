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
