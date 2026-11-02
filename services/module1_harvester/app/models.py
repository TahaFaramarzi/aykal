"""
مدل‌های دیتابیس ماژول ۱، منطبق با اسکیمای مشترک پروژه (db/schema.sql).
هویت هر کاربر اینستاگرام = ig_users.user_id (BIGINT)؛ مشترک با همه‌ی ماژول‌ها.
"""
from datetime import datetime
from sqlalchemy import (
    Column, BigInteger, Integer, String, DateTime, Text, ForeignKey, Boolean, Index, cast,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from app.database import Base


class IgUser(Base):
    """هویت مشترک کاربر اینستاگرام (همه‌ی ماژول‌ها به این جدول وصل‌اند)"""
    __tablename__ = "ig_users"

    user_id = Column(BigInteger, primary_key=True, autoincrement=False)
    username = Column(String(100), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    last_seen_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    do_not_contact = Column(Boolean, nullable=False, default=False)


class Lead(Base):
    """سرنخ — یک کاربر اینستاگرام که با پیج ما تعامل داشته"""
    __tablename__ = "leads"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("ig_users.user_id"), unique=True, nullable=False)
    full_name = Column(String(255), nullable=True)

    intent = Column(String(50), default="unknown")
    lead_score = Column(Integer, default=0)

    # active | engaged | warm | hot | cold | converted | lost
    status = Column(String(20), default="active")

    total_interactions = Column(Integer, default=0)
    last_interaction_at = Column(DateTime(timezone=True), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    ig_user = relationship("IgUser", lazy="joined")
    interactions = relationship("Interaction", back_populates="lead", cascade="all, delete-orphan")

    # سازگاری با کد قبلی: instagram_id همان user_id به‌صورت رشته است
    @hybrid_property
    def instagram_id(self):
        return str(self.user_id)

    @instagram_id.expression
    def instagram_id(cls):
        return cast(cls.user_id, String)

    @property
    def username(self):
        return self.ig_user.username if self.ig_user else None

    def __repr__(self):
        return f"<Lead {self.user_id} score={self.lead_score} intent={self.intent}>"


class Interaction(Base):
    """یک تعامل (کامنت / دایرکت / لایک / منشن / پاسخ استوری)"""
    __tablename__ = "interactions"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("ig_users.user_id"), nullable=False)
    lead_id = Column(BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=True)

    interaction_type = Column(String(32), nullable=False)
    # comment | direct | like | mention | story_reply

    content = Column(Text, nullable=True)
    media_id = Column(String(64), nullable=True)
    comment_id = Column(String(64), nullable=True)

    detected_intent = Column(String(64), nullable=True)
    intent_score = Column(Integer, default=0)

    # پاسخ پیشنهادی LLM (فقط ذخیره می‌شود؛ ارسال خودکار نیست)
    generated_reply = Column(Text, nullable=True)
    reply_sent_at = Column(DateTime(timezone=True), nullable=True)
    reply_status = Column(String(32), nullable=True)   # pending | sent | failed | skipped

    external_id = Column(String(100), unique=True, nullable=True)   # جلوگیری از رکورد تکراری
    created_at = Column("received_at", DateTime(timezone=True), default=datetime.utcnow)

    lead = relationship("Lead", back_populates="interactions")

    @property
    def instagram_id(self):
        return str(self.user_id)

    def __repr__(self):
        return f"<Interaction {self.interaction_type} user={self.user_id}>"
