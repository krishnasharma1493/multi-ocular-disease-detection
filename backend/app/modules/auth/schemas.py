from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.modules.users.schemas import UserRead


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class LoginOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserRead


class RegisterIn(BaseModel):
    name: str
    email: str
    password: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        s = v.strip()
        if not (1 <= len(s) <= 80):
            raise ValueError("Name must be between 1 and 80 characters")
        return s

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        s = v.strip().lower()
        if len(s) > 254:
            raise ValueError("Email must be at most 254 characters")
        if s.count("@") != 1:
            raise ValueError("Email must contain exactly one @")
        local, domain = s.split("@")
        if not local:
            raise ValueError("Email must have a mailbox name before @")
        if "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("Email domain must contain a dot")
        return s

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not (8 <= len(v) <= 200):
            raise ValueError("Password must be between 8 and 200 characters")
        return v

