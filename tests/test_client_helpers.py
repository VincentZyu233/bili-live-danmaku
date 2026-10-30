from bili_live_danmaku.bili.client import BiliApi, account_mid, has_login_cookie


def test_account_mid_and_cookie_presence() -> None:
    cookie = "buvid3=abc; SESSDATA=secret; DedeUserID=123456"
    assert account_mid(cookie) == 123456
    assert has_login_cookie(cookie)
    assert account_mid("buvid3=abc") == 0
    assert not has_login_cookie("buvid3=abc")


async def test_anonymous_buvid_header_has_no_trailing_space() -> None:
    api = BiliApi("")
    try:
        api._buvid3 = "device-id"
        cookie = api._headers()["Cookie"]
        assert cookie == cookie.strip()
        assert cookie.startswith("buvid3=device-id; b_nut=")
    finally:
        await api.close()
