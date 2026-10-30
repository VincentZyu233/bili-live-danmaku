# 🍪 B站 Cookie 助手

`get_bili_cookie.py` 会打开 Edge/Chrome 的临时 profile，等待你扫码登录 B站，然后通过 Chrome DevTools Protocol 读取 Cookie。

```powershell
uv run tools/get_bili_cookie.py
```

默认写入：

```text
%LOCALAPPDATA%\bili-live-danmaku\cookie.txt
```

脚本不会处理密码，也不会修改日常浏览器 profile。完整 Cookie 默认不打印到终端；需要临时查看时可加 `--print-cookie`。

也可以指定浏览器或输出位置：

```powershell
uv run tools/get_bili_cookie.py --browser-path "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
uv run tools/get_bili_cookie.py --output "D:\temp\cookie.txt"
```

Cookie 是会话凭据。不要提交到 Git、粘贴到 issue 或公开聊天中。
