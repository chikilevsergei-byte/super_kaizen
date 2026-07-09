from sqlalchemy import BigInteger, String, Text, DateTime, ForeignKey, func, Enum, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime
import enum

class UserRole(str, enum.Enum):
    EMPLOYEE = "employee"
    SUPERVISOR = "supervisor"
    DIRECTOR = "director"

class ProblemStatus(str, enum.Enum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    POSTPONED = "POSTPONED"

class Base(DeclarativeBase):
    pass

class Store(Base):
    __tablename__ = 'stores'
    id: Mapped[int] = mapped_column(primary_key=True)
    cluster: Mapped[str] = mapped_column(String(50), nullable=True)
    region: Mapped[str] = mapped_column(String(50), nullable=True)


class User(Base):
    __tablename__ = 'users'
    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.EMPLOYEE)
    store_id: Mapped[int] = mapped_column(ForeignKey('stores.id'), nullable=True)
    cluster: Mapped[str] = mapped_column(String(50), nullable=True)
    region: Mapped[str] = mapped_column(String(50), nullable=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)

class Problem(Base):
    __tablename__ = 'problems'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.tg_id'))
    store_id: Mapped[int] = mapped_column(ForeignKey('stores.id'))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[ProblemStatus] = mapped_column(Enum(ProblemStatus), default=ProblemStatus.NEW)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    resolution_comment: Mapped[str] = mapped_column(Text, nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    original_problem_id: Mapped[int] = mapped_column(ForeignKey('problems.id'), nullable=True)

class FeedbackStatus(str, enum.Enum):
    NEW = "NEW"
    RESOLVED = "RESOLVED"

class Feedback(Base):
    __tablename__ = 'feedback'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.tg_id'))
    text: Mapped[str] = mapped_column(Text)
    phone: Mapped[str] = mapped_column(String, nullable=True)
    status: Mapped[FeedbackStatus] = mapped_column(Enum(FeedbackStatus), default=FeedbackStatus.NEW)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
