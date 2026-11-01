import pytest

from bili_live_danmaku.bili.client import BiliApi, CookieInvalidError, account_mid, has_login_cookie


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


async def test_auth_uid_rejects_expired_cookie() -> None:
    api = BiliApi("SESSDATA=expired; DedeUserID=123456")
    try:
        api._nav_payload = {"isLogin": False}
        with pytest.raises(CookieInvalidError, match="Cookie 已失效"):
            await api.auth_uid()
    finally:
        await api.close()


async def test_auth_uid_allows_anonymous_without_cookie() -> None:
    api = BiliApi("")
    try:
        api._nav_payload = {"isLogin": False}
        assert await api.auth_uid() == 0
    finally:
        await api.close()


async def test_auth_uid_uses_valid_login_mid() -> None:
    api = BiliApi("SESSDATA=valid; DedeUserID=123456")
    try:
        api._nav_payload = {"isLogin": True, "mid": 654321}
        assert await api.auth_uid() == 654321
        api._nav_payload = {"isLogin": True}
        assert await api.auth_uid() == 123456
    finally:
        await api.close()
