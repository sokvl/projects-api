import uuid
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BaseModel
from app.models.document import Document


class ProjectRole(StrEnum):
    OWNER = "owner"
    PARTICIPANT = "participant"


ROLE_VALUES = ", ".join(f"'{role}'" for role in ProjectRole)


class Project(BaseModel):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    documents: Mapped[list["Document"]] = relationship(
        "Document", cascade="all, delete-orphan", passive_deletes=True
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (CheckConstraint(f"role IN ({ROLE_VALUES})", name="ck_project_members_role"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(Text)
