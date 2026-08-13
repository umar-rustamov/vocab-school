# -*- coding: utf-8 -*-
"""
Разбор списка слов в формате:

    1) Word - перевод
    синоним, синоним, синоним
    Collocations:
    словосочетание 1
    словосочетание 2

    2) Next word - перевод
    ...

Функция parse_vocab_text() возвращает список словарей:
    {"word": str, "translation": str, "synonyms": [str, ...], "collocations": [str, ...]}
"""

import re
from typing import Optional

WORD_LINE_RE = re.compile(r"^\d+[.)]\s*(.+)$")
# дефис/тире с пробелами по бокам — надёжный разделитель «слово - перевод»
DASH_SPLIT_STRICT_RE = re.compile(r"\s-{1,2}\s")
# дефис/тире без пробелов или только с одной стороны
# («Word-перевод», «Word– перевод») — менее надёжно, поэтому используется
# только если справа явно кириллица (перевод), иначе легко спутать с
# коллокацией вида "WMD-weapons of mass destruction"
DASH_SPLIT_LOOSE_RE = re.compile(r"\s*[-–—]{1,2}\s*")
COLLOCATIONS_RE = re.compile(r"^collocations:?$", re.IGNORECASE)
CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")


def _split_word_translation(content: str):
    """Пробует разбить строку на (слово, перевод). Сначала строгий разделитель
    (дефис с пробелами с обеих сторон), затем — более широкий (любое тире,
    в том числе без пробелов), но только если справа есть кириллица."""
    parts = DASH_SPLIT_STRICT_RE.split(content, maxsplit=1)
    if len(parts) >= 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(), parts[1].strip()

    parts = DASH_SPLIT_LOOSE_RE.split(content, maxsplit=1)
    if (
        len(parts) >= 2
        and parts[0].strip()
        and parts[1].strip()
        and CYRILLIC_RE.search(parts[1])
    ):
        return parts[0].strip(), parts[1].strip()

    return None


def parse_vocab_text(text: str):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    entries = []
    current = None
    stage = None

    for raw in lines:
        # строка "Collocations:" не может сама быть новым словом
        if not COLLOCATIONS_RE.match(raw):
            m = WORD_LINE_RE.match(raw)
            # если есть номер («1) Word - перевод») — берём текст после номера,
            # иначе пробуем всю строку как есть («Word - перевод» без номера)
            content = m.group(1).strip() if m else raw
            content = content.replace("**", "").strip()
            split = _split_word_translation(content)
            if split:
                if current:
                    entries.append(current)
                current = {
                    "word": split[0],
                    "translation": split[1],
                    "synonyms": [],
                    "collocations": [],
                }
                stage = "synonyms"
                continue

        if current is None:
            continue
        if COLLOCATIONS_RE.match(raw):
            stage = "collocations"
            continue
        if stage == "synonyms":
            for s in raw.split(","):
                s = s.strip()
                if s:
                    current["synonyms"].append(s)
        elif stage == "collocations":
            current["collocations"].append(raw)

    if current:
        entries.append(current)

    return [e for e in entries if e["word"] and e["translation"]]


def extract_docx_text(file_stream) -> str:
    """Достаёт весь текст из .docx (используется при загрузке файла учителем)."""
    import docx  # python-docx

    document = docx.Document(file_stream)
    return "\n".join(p.text for p in document.paragraphs)


UNIT_NUMBER_RE = re.compile(r"(?:unit|юнит)\D{0,3}(\d+)", re.IGNORECASE)


def guess_unit_number(*sources) -> Optional[int]:
    """Пытается определить номер юнита (ищет «Unit N» / «юнит N») по очереди
    в переданных строках — например, сначала по имени файла, потом по тексту."""
    for src in sources:
        if not src:
            continue
        m = UNIT_NUMBER_RE.search(src)
        if m:
            return int(m.group(1))
    return None


def guess_unit_title(filename: str) -> str:
    """Название юнита по умолчанию — имя файла без расширения."""
    import os

    stem = os.path.splitext(filename)[0]
    return re.sub(r"\s+", " ", stem).strip()


def normalize(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"^to\s+", "", s)
    s = re.sub(r"[.,!?;:'\"]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s
