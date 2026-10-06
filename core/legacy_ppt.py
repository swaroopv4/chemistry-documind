"""Read live slide text from unencrypted PowerPoint 97-2003 OLE files.

Uses the current-user edit chain and persist directory from Microsoft's MS-PPT
specification so deleted slides and old saved text do not enter the index.
"""
from __future__ import annotations

import struct
from pathlib import Path

import olefile

from core.formats import Section


def _record(data, offset, limit=None):
    limit = len(data) if limit is None else limit
    if offset < 0 or offset + 8 > limit:
        raise ValueError("Truncated PPT record header")
    flags, kind, length = struct.unpack_from("<HHI", data, offset)
    start, end = offset + 8, offset + 8 + length
    if end > limit:
        raise ValueError("Truncated PPT record payload")
    return flags, kind, start, end


def _children(data, start, end):
    while start < end:
        flags, kind, body, next_offset = _record(data, start, end)
        yield flags, kind, body, next_offset
        start = next_offset


def _descendants(data, start, end, depth=0):
    if depth > 64:
        raise ValueError("PPT record nesting exceeds supported depth")
    for flags, kind, body, next_offset in _children(data, start, end):
        yield flags, kind, body, next_offset
        # OfficeArtClientTextbox contains PPT atoms despite recVer=0.
        if flags & 15 == 15 or kind == 0xF00D:
            yield from _descendants(data, body, next_offset, depth + 1)


def _text(data, start, end):
    result = []
    for _, kind, body, stop in _descendants(data, start, end):
        if kind == 4000:
            if (stop - body) % 2:
                raise ValueError("Invalid UTF-16 PPT text record")
            result.append(data[body:stop].decode("utf-16-le"))
        elif kind == 4008:
            # MS-PPT TextBytesAtom stores low bytes of UTF-16 characters.
            result.append(data[body:stop].decode("latin-1"))
    return [text.replace("\r", "\n").strip() for text in result if text.strip()]


def extract_ppt(path: Path) -> list[Section]:
    if not olefile.isOleFile(str(path)):
        raise ValueError("Not a binary .ppt file; export the presentation as .pptx")
    with olefile.OleFileIO(str(path)) as ole:
        if not ole.exists("PowerPoint Document") or not ole.exists("Current User"):
            raise ValueError("Unsupported or encrypted PPT; save an unencrypted .pptx copy")
        data = ole.openstream("PowerPoint Document").read()
        user = ole.openstream("Current User").read()
    _, kind, body, end = _record(user, 0)
    if kind != 4086 or end - body < 12:
        raise ValueError("Invalid PPT Current User stream")
    token, edit = struct.unpack_from("<II", user, body + 4)
    if token != 0xE391C05F:
        raise ValueError("Encrypted PPT is unsupported; save an unencrypted copy")

    directory, visited, doc_id = {}, set(), None
    while True:
        if edit in visited:
            raise ValueError("Cyclic PPT edit history")
        visited.add(edit)
        _, kind, start, end = _record(data, edit)
        if kind != 4085 or end - start < 28:
            raise ValueError("Invalid PPT UserEditAtom")
        previous, persist_offset, current_doc_id = struct.unpack_from("<III", data, start + 8)
        if doc_id is None:
            doc_id = current_doc_id
        _, kind, pos, stop = _record(data, persist_offset)
        if kind not in (6001, 6002):
            raise ValueError("Invalid PPT persist directory")
        while pos < stop:
            if pos + 4 > stop:
                raise ValueError("Truncated PPT persist directory")
            descriptor = struct.unpack_from("<I", data, pos)[0]
            first_id, count = descriptor & 0xFFFFF, descriptor >> 20
            pos += 4
            if not count or pos + 4 * count > stop:
                raise ValueError("Invalid PPT persist entry")
            for i in range(count):
                offset = struct.unpack_from("<I", data, pos + 4 * i)[0]
                directory.setdefault(first_id + i, offset)  # newest edit wins
            pos += 4 * count
        if not previous:
            break
        edit = previous
    if doc_id not in directory:
        raise ValueError("PPT document missing from persist directory")
    _, kind, start, end = _record(data, directory[doc_id])
    if kind != 1000:
        raise ValueError("Invalid PPT DocumentContainer")

    slides = []
    for flags, kind, body, stop in _descendants(data, start, end):
        if kind != 4080 or flags >> 4 != 0:
            continue  # ordinary slides only; exclude notes and masters
        active = None
        for _, child_kind, child_start, child_end in _children(data, body, stop):
            if child_kind == 1011:
                if child_end - child_start < 20:
                    raise ValueError("Invalid PPT SlidePersistAtom")
                active = {"id": struct.unpack_from("<I", data, child_start)[0], "text": []}
                slides.append(active)
            elif active is not None and child_kind in (4000, 4008):
                raw = data[child_start:child_end]
                active["text"].append(raw.decode("utf-16-le" if child_kind == 4000 else "latin-1"))

    result = []
    for number, slide in enumerate(slides, 1):
        slide_id = slide["id"]
        if slide_id not in directory:
            raise ValueError("PPT slide missing from persist directory")
        _, kind, body, stop = _record(data, directory[slide_id])
        if kind != 1006:
            raise ValueError("Invalid PPT SlideContainer")
        texts = slide["text"] + _text(data, body, stop)
        # Placeholder text may be duplicated in the slide outline and shape data.
        text = "\n".join(dict.fromkeys(t.replace("\r", "\n").strip() for t in texts if t.strip()))
        if text:
            result.append(Section(text, f"slide {number}", number))
    return result
