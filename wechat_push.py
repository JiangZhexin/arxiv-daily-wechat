# -*- coding: utf-8 -*-
"""
wechat_push.py
通过「微信公众号测试号」模板消息把内容推送到微信。

申请测试号（免费、个人即可）:
    https://mp.weixin.qq.com/debug/cgi-bin/sandbox
用微信扫码登录后即可看到 appID / appsecret，
在「模板消息」里添加一个模板并记录 template_id，
让微信扫码「测试者」二维码，你的 openid 会出现在测试者列表中。

模板消息 data 的字段名由你选择的模板决定（常见为 first / keyword1.. / remark），
通过 template_fields 映射后本模块会按你模板的实际字段名发送。
"""
import time

import requests

TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
SEND_URL = "https://api.weixin.qq.com/cgi-bin/message/template/send"


class WeChatPusher:
    def __init__(self, app_id, app_secret, template_id, user_openid):
        self.app_id = app_id
        self.app_secret = app_secret
        self.template_id = template_id
        self.user_openid = user_openid
        self._token = None

    def get_access_token(self):
        """获取（并缓存）全局 access_token，有效期 7200 秒。"""
        if self._token:
            return self._token
        resp = requests.get(
            TOKEN_URL,
            params={
                "grant_type": "client_credential",
                "appid": self.app_id,
                "secret": self.app_secret,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if "access_token" not in data:
            raise RuntimeError(f"获取 access_token 失败: {data}")
        self._token = data["access_token"]
        return self._token

    def send_template(self, data, url=None, max_retries=2):
        """
        发送一条模板消息。

        参数:
            data: dict，形如 {"first": {"value": "..."}, "keyword1": {"value": "..."}, "remark": {"value": "..."}}
                 注意：key 是模板的真实字段名，请先按 template_fields 映射好。
            url: 可选，微信消息里点击可跳转的链接（如论文 arxiv 地址）
        """
        token = self.get_access_token()
        send_url = f"{SEND_URL}?access_token={token}"
        body = {
            "touser": self.user_openid,
            "template_id": self.template_id,
            "data": data,
        }
        if url:
            body["url"] = url

        for attempt in range(max_retries):
            resp = requests.post(send_url, json=body, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            if result.get("errcode") == 0:
                return True
            if result.get("errcode") in (40001, 42001):
                # access_token 过期或无效，清掉重取
                self._token = None
                token = self.get_access_token()
                send_url = f"{SEND_URL}?access_token={token}"
                continue
            raise RuntimeError(f"模板消息发送失败: {result}")

        return False

    def send_batch(self, messages, pause_seconds=2):
        """
        发送多条模板消息（论文多时拆分推送）。

        参数:
            messages: list[dict]，每个 dict 形如 {"data": {...}, "url": "可选跳转链接"}
            pause_seconds: 每条之间的间隔秒数
        """
        sent = 0
        for i, msg in enumerate(messages):
            self.send_template(msg["data"], url=msg.get("url"))
            sent += 1
            if i < len(messages) - 1:
                time.sleep(pause_seconds)
        return sent


if __name__ == "__main__":
    # 自测示例（需要真实凭据）：
    # python wechat_push.py
    import os
    import sys
    import time

    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")

    pusher = WeChatPusher(
        app_id=os.environ.get("WECHAT_APP_ID", ""),
        app_secret=os.environ.get("WECHAT_APP_SECRET", ""),
        template_id=os.environ.get("WECHAT_TEMPLATE_ID", ""),
        user_openid=os.environ.get("WECHAT_OPENID", ""),
    )
    if not pusher.app_id:
        print("请先设置环境变量 WECHAT_APP_ID / WECHAT_APP_SECRET / WECHAT_TEMPLATE_ID / WECHAT_OPENID")
        sys.exit(1)

    ok = pusher.send_template(
        {
            "first": {"value": "测试消息"},
            "keyword1": {"value": "arXiv 每日速览"},
            "keyword2": {"value": "配置成功"},
            "remark": {"value": "如果你在微信收到了这条消息，说明推送通道已打通。"},
        }
    )
    print("发送成功" if ok else "发送失败")
