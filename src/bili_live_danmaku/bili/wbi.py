from __future__ import annotations

import hashlib
from collections.abc import Mapping
from urllib.parse import quote, urlparse

MIXIN_KEY_ENC_TAB = (
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
)


def key_from_url(url: str) -> str:
    name = urlparse(url).path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0]


def mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    if len(raw) < 64:
        raise ValueError("WBI keys are shorter than 64 characters")
    return "".join(raw[index] for index in MIXIN_KEY_ENC_TAB)[:32]


def percent_encode(value: str) -> str:
    return quote(value, safe="-_.~")


def make_query(params: Mapping[str, str | int], mixin: str) -> str:
    cleaned: list[tuple[str, str]] = []
    for key, value in sorted(params.items()):
        text = str(value)
        text = "".join(char for char in text if char not in "!'()*")
        cleaned.append((percent_encode(key), percent_encode(text)))
    query = "&".join(f"{key}={value}" for key, value in cleaned)
    digest = hashlib.md5((query + mixin).encode("utf-8")).hexdigest()  # noqa: S324
    return f"{query}&w_rid={digest}"
