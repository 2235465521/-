"""解析 MySQL dump 中 INSERT INTO ... VALUES (...) 行内的元组。"""
from __future__ import annotations

import re


def _split_tuples(values_blob: str) -> list[str]:
    tuples: list[str] = []
    depth = 0
    in_string = False
    escape = False
    start = 0
    for i, ch in enumerate(values_blob):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'":
                in_string = False
            continue
        if ch == "'":
            in_string = True
            continue
        if ch == "(":
            if depth == 0:
                start = i + 1
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                tuples.append(values_blob[start:i])
    return tuples


def _split_fields(tuple_body: str) -> list[str | None]:
  fields: list[str | None] = []
  buf: list[str] = []
  in_string = False
  escape = False
  i = 0
  n = len(tuple_body)
  while i < n:
    ch = tuple_body[i]
    if in_string:
      if escape:
        buf.append(ch)
        escape = False
      elif ch == "\\":
        escape = True
      elif ch == "'":
        if i + 1 < n and tuple_body[i + 1] == "'":
          buf.append("'")
          i += 1
        else:
          in_string = False
      else:
        buf.append(ch)
      i += 1
      continue
    if ch == "'":
      in_string = True
      i += 1
      continue
    if ch == ",":
      token = "".join(buf).strip()
      fields.append(None if token.upper() == "NULL" else token)
      buf = []
      i += 1
      continue
    buf.append(ch)
    i += 1
  token = "".join(buf).strip()
  fields.append(None if token.upper() == "NULL" else token)
  return fields


def iter_insert_rows(line: str, table: str):
    marker = f"INSERT INTO `{table}` VALUES "
    if marker in line:
        blob = line.split(marker, 1)[1].strip()
        if blob.endswith(";"):
            blob = blob[:-1]
        for body in _split_tuples(blob):
            yield _split_fields(body)
        return

    named = re.search(
        rf"INSERT INTO `{re.escape(table)}`\s*\([^)]+\)\sVALUES\s(.+?);?\s*$",
        line,
        flags=re.IGNORECASE,
    )
    if not named:
        return
    blob = named.group(1).strip().rstrip(";")
    for body in _split_tuples(blob):
        yield _split_fields(body)
