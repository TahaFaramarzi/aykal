"""مدل‌های داده: نوع فعالیت و خود فعالیت کاربر."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class ActivityType(str, Enum):
    LOGIN = "login"
    LOGOUT = "logout"
    VIEW = "view"
    LIKE = "like"
    COMMENT = "comment"
    FOLLOW = "follow"
    UPLOAD = "upload"
    MESSAGE = "message"    # پیام مستقیم (دایرکت) ورودی از کاربر
    MENTION = "mention"    # منشن پیج در محتوای کاربر
    REACTION = "reaction"  # واکنش به پیام
    OTHER = "other"

    @classmethod
    def from_content(cls, content: str) -> "ActivityType":
        """نوع فعالیت را از روی متن (مثلاً 'Comment: Nice!') تشخیص می‌دهد."""
        text = content.strip().lower()
        for member in cls:
            if member is not cls.OTHER and text.startswith(member.value):
                return member
        return cls.OTHER


@dataclass
class UserActivity:
    user_id: str
    content: str
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, str) or not self.user_id.strip():
            raise ValueError("user_id نباید خالی باشد")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("content نباید خالی باشد")
        if isinstance(self.created_at, str):
            try:
                self.created_at = datetime.strptime(self.created_at, DATE_FORMAT)
            except ValueError as exc:
                raise ValueError(
                    f"فرمت تاریخ نامعتبر است (باید {DATE_FORMAT} باشد): {self.created_at!r}"
                ) from exc

    @property
    def detail(self) -> str:
        """متن بعد از «:» در content؛ مثلاً 'Message: سلام' ← 'سلام'."""
        return self.content.split(":", 1)[1].strip() if ":" in self.content else ""

    @property
    def type(self) -> ActivityType:
        return ActivityType.from_content(self.content)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "content": self.content,
            "created_at": self.created_at.strftime(DATE_FORMAT),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserActivity":
        return cls(
            user_id=data["user_id"],
            content=data["content"],
            created_at=data["created_at"],
        )
