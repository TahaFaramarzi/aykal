"""
Simulated Instagram inbox for the company demo.
No Meta / Facebook Developer login: events are signed locally and
posted to the same webhook the live Graph API would call.
"""
import hashlib
import hmac
import json
import os
import time

import httpx
import streamlit as st

M1 = os.getenv("MODULE1_URL", "http://127.0.0.1:8001").rstrip("/")
M4 = os.getenv("MODULE4_URL", "http://127.0.0.1:8004").rstrip("/")
SECRET = os.getenv("META_APP_SECRET", "local-dev-secret")
API_KEY = os.getenv("API_KEY", "")


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _meta_payload(kind: str, user_id: str, username: str, text: str) -> dict:
    stamp = int(time.time() * 1000)
    mid = f"local.{stamp}"
    if kind == "comment":
        return {
            "object": "instagram",
            "entry": [{
                "id": "1",
                "changes": [{
                    "field": "comments",
                    "value": {
                        "id": mid,
                        "text": text,
                        "from": {"id": user_id, "username": username},
                        "media": {"id": "demo_post"},
                    },
                }],
            }],
        }
    return {
        "object": "instagram",
        "entry": [{
            "id": "1",
            "messaging": [{
                "sender": {"id": user_id},
                "recipient": {"id": "1"},
                "timestamp": stamp,
                "message": {"mid": mid, "text": text},
            }],
        }],
    }


def post_webhook(kind: str, user_id: str, username: str, text: str) -> dict:
    payload = _meta_payload(kind, user_id, username, text)
    body = json.dumps(payload).encode()
    r = httpx.post(
        f"{M1}/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign(body),
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def chat_with_agent(user_id: str, text: str) -> dict:
    r = httpx.post(
        f"{M4}/chat",
        json={"user_id": user_id, "message": text},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()


def fetch_leads():
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    try:
        r = httpx.get(f"{M1}/leads", headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("items") or data.get("leads") or []
    except Exception:
        return []


st.set_page_config(page_title="Aykal — Simulated Instagram", layout="wide")
st.markdown(
    """
    <style>
    html, body, [data-testid="stAppViewContainer"] { direction: rtl; }
    .stChatMessage { direction: rtl; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("صندوق پیام شبیه‌سازی‌شده")
st.caption(
    "این همان مسیر واقعی محصول است، بدون ورود به Meta for Developers. "
    "پاسخ‌ها از مدل محلی (Ollama) و پایگاه دانش داخل خود پروژه می‌آیند."
)

if "messages" not in st.session_state:
    st.session_state.messages = []

col_chat, col_side = st.columns([1.4, 1])

with col_side:
    st.subheader("هویت مشتری آزمایشی")
    user_id = st.text_input("شناسه عددی", value="1000000001")
    username = st.text_input("نام کاربری", value="demo_customer")
    st.markdown("**نوع رویداد**")
    kind = st.radio(
        "kind",
        ["direct", "comment"],
        format_func=lambda v: "دایرکت (مدل پاسخ می‌دهد)" if v == "direct" else "کامنت روی پست (سرنخ)",
        label_visibility="collapsed",
    )
    if st.button("بارگذاری سرنخ‌های ماژول ۱"):
        st.session_state["leads"] = fetch_leads()
    for lead in st.session_state.get("leads") or []:
        if isinstance(lead, dict):
            st.write(
                f"@{lead.get('username') or lead.get('user_id')} — "
                f"{lead.get('intent') or lead.get('detected_intent')} "
                f"(امتیاز {lead.get('lead_score', '—')})"
            )

with col_chat:
    for item in st.session_state.messages:
        with st.chat_message(item["role"]):
            st.write(item["text"])
            if item.get("meta"):
                st.caption(item["meta"])

    prompt = st.chat_input("مثل مشتری اینستاگرام بنویسید…")
    if prompt:
        st.session_state.messages.append({"role": "user", "text": prompt})
        try:
            if kind == "direct":
                # Direct /chat only — Celery also forwards DMs, so posting
                # the webhook here would duplicate the user message.
                reply = chat_with_agent(user_id, prompt)
                bot_text = reply.get("response") or "(ربات ساکت ماند — احتمالاً ارجاع به اپراتور)"
                meta = (
                    f"handoff={reply.get('handoff')}  "
                    f"confidence={reply.get('confidence')}"
                )
                st.session_state.messages.append(
                    {"role": "assistant", "text": bot_text, "meta": meta}
                )
            else:
                hook = post_webhook(kind, user_id, username, prompt)
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "text": "کامنت ثبت شد. نیت و امتیاز سرنخ در ستون سمت چپ بعد از پردازش Celery دیده می‌شود.",
                        "meta": f"webhook queued={hook.get('events_queued')}",
                    }
                )
        except Exception as exc:
            st.session_state.messages.append(
                {"role": "assistant", "text": f"خطا: {exc}"}
            )
        st.rerun()
