"""SQLAlchemy models for the studio database."""

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

STATUS_STABLE = "stable"
STATUS_WIP = "wip"
STATUS_CANCELED = "canceled"
STATUSES = (STATUS_STABLE, STATUS_WIP, STATUS_CANCELED)


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Asset(Base):
    """One version of an asset.

    Multiple records may share the same ``name`` (one per version),
    but only one of them may have status ``stable`` at a time.
    """

    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint(f"status IN {STATUSES}", name="ck_asset_status"),
        UniqueConstraint("name", "version", name="uq_asset_name_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    author: Mapped[str] = mapped_column(String(128), nullable=False, default="unknown")
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="v001")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_WIP)
    # file name inside the preview_img folder, e.g. "asset_1_ab12cd.png"
    preview_img: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    steps: Mapped[list["Step"]] = relationship(
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="Step.key",
    )

    def __repr__(self):
        return f"<Asset {self.id} {self.name} {self.version} [{self.status}]>"


class Step(Base):
    """One entry of the asset's steps dict: key (str) -> value (int).

    Each entry also carries its own status, last modification date and
    the name of the user who modified it.
    """

    __tablename__ = "steps"
    __table_args__ = (
        CheckConstraint(f"status IN {STATUSES}", name="ck_step_status"),
        UniqueConstraint("asset_id", "key", name="uq_step_asset_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_WIP)
    modified_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
    modified_by: Mapped[str] = mapped_column(String(128), nullable=False, default="unknown")

    asset: Mapped[Asset] = relationship(back_populates="steps")

    def __repr__(self):
        return f"<Step {self.asset_id}:{self.key}={self.value} [{self.status}]>"
