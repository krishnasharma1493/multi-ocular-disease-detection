from sqlmodel import SQLModel


class UserRead(SQLModel):
    id: int
    email: str
    name: str
    is_admin: bool
