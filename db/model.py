from sqlalchemy import Boolean, Column, Integer, String, DateTime
from sqlalchemy.sql import func
from .database import Base


class MediaGroupMesssage(Base):
    __tablename__ = "media_group_message"
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer)
    message_id = Column(Integer)
    media_group_id = Column(Integer)
    is_header = Column(Boolean)
    caption_html = Column(String(1024 * 64))


class FormnStatus(Base):
    __tablename__ = "formn_status"
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer)
    message_thread_id = Column(Integer)
    status = Column(String(64))


class MessageMap(Base):
    __tablename__ = "message_map"
    id = Column(Integer, primary_key=True, index=True)
    user_chat_message_id = Column(Integer)
    group_chat_message_id = Column(Integer)
    user_id = Column(Integer)


class User(Base):
    __tablename__ = "user"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, index=True)
    first_name = Column(String(64))
    last_name = Column(String(64))
    username = Column(String(64))
    is_premium = Column(Boolean)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    message_thread_id = Column(Integer, default=0)
