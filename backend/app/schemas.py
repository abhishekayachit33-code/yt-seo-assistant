from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str


class AnalyzeRequest(BaseModel):
    url: str
    include_competitors: bool = False
    run_keyword_pipeline: bool = True


class HistoryItem(BaseModel):
    id: int
    video_id: str
    title: str
    channel: str
    analyzed_at: str


class PlanRequest(BaseModel):
    script: str
    title: str = ""
    description: str = ""
    tags: str = ""  # comma-separated, same as the old form field
    title_variant: str = ""  # one alternative title to compare, optional
    include_competitors: bool = False
    run_keyword_pipeline: bool = True


class ThumbnailCritiqueRequest(BaseModel):
    # Exactly one of these -- a real video's public thumbnail (fetched by
    # URL) or an uploaded/generated one (sent as base64, since this is a
    # JSON endpoint, not multipart).
    thumbnail_url: str | None = None
    image_base64: str | None = None
    mime_type: str = "image/jpeg"


class ThumbnailGenerateRequest(BaseModel):
    title: str
    context: str = ""
    count: int = 3


TokenResponse.model_rebuild()
