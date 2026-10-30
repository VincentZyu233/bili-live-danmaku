from __future__ import annotations

from bili_live_danmaku.bili.wbi import make_query, mixin_key, percent_encode


def test_percent_encode_matches_wbi_rules() -> None:
    assert percent_encode("a b!'()*中") == "a%20b%21%27%28%29%2A%E4%B8%AD"


def test_make_query_is_sorted_and_signed() -> None:
    mixin = "0123456789abcdef0123456789abcdef"
    query = make_query(
        {"id": "1", "type": "0", "context_type": "0", "wts": "1700000000"}, mixin
    )
    assert query == (
        "context_type=0&id=1&type=0&wts=1700000000"
        "&w_rid=bfae9a671c0b0c8a656d3e5dc47c9d26"
    )


def test_mixin_key_uses_fixed_permutation() -> None:
    raw = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"
    result = mixin_key(raw[:32], raw[32:])
    assert result == "KLi2R8nwfOavW3JzrH5Nx9GjtseDcCFd"
