from pydantic import BaseModel, Field


class SkillMeta(BaseModel):
    name: str
    description: str
    path: str = ""


class SkillBody(BaseModel):
    name: str
    description: str
    body: str


class SkillbookState(BaseModel):
    catalog: list[SkillMeta] = Field(default_factory=list)
    active: SkillBody | None = None
