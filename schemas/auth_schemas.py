from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict

class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str

    @field_validator("username", mode="before")
    @classmethod
    def trim_username(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        if len(v) < 8 or len(v) > 128:
            raise ValueError("Password must be between 8 and 128 characters long.")
        if not any(c.isalpha() for c in v):
            raise ValueError("Password must contain at least one letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        return v

class UserLoginRequest(BaseModel):
    email: str  # Field named email for API compatibility, accepts username or email
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_identifier(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_admin: bool = False
    role: str = "user"
    status: str = "active"

    model_config = ConfigDict(from_attributes=True)

class AuthSuccessResponse(BaseModel):
    success: bool
    user: UserResponse | None = None
    redirect_url: str | None = None

class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password_complexity(cls, v: str) -> str:
        if len(v) < 8 or len(v) > 128:
            raise ValueError("Password must be between 8 and 128 characters long.")
        if not any(c.isalpha() for c in v):
            raise ValueError("Password must contain at least one letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        return v
