from pydantic import BaseModel, Field, model_validator

TITLE_MAX = 200
BODY_MAX = 100_000


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    body: str = Field(default="", max_length=BODY_MAX)


class NoteUpdate(BaseModel):
    version: int = Field(ge=1, description="The version you last read")
    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    body: str | None = Field(default=None, max_length=BODY_MAX)

    @model_validator(mode="after")
    def require_a_change(self) -> "NoteUpdate":
        if self.title is None and self.body is None:
            raise ValueError("Provide at least one of title or body")
        return self


class NoteOut(BaseModel):
    id: int
    team_id: int
    title: str
    body: str
    version: int
    created_by: int
    updated_by: int
    created_at: str
    updated_at: str


class ConflictOut(BaseModel):
    detail: str
    current: NoteOut
