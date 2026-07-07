import uuid

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.user import Role


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: Role
    company_id: uuid.UUID