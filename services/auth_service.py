import bcrypt
from datetime import datetime, timezone
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from models.user import User

def hash_password(password: str) -> str:
    """Hashes a password using bcrypt."""
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against a hashed password."""
    if not plain_password or not hashed_password:
        return False
    try:
        pwd_bytes = plain_password.encode("utf-8")[:72]
        return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
    except Exception:
        return False

def generate_temporary_password() -> str:
    """Generates a secure temporary password of length 18 containing uppercase, lowercase, digits, and safe symbols without ambiguous characters."""
    import secrets
    upper_pool = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    lower_pool = "abcdefghijkmnopqrstuvwxyz"
    digits_pool = "23456789"
    symbols_pool = "@#$%&*+?="
    
    password = [
        secrets.choice(upper_pool),
        secrets.choice(lower_pool),
        secrets.choice(digits_pool),
        secrets.choice(symbols_pool)
    ]
    
    all_pool = upper_pool + lower_pool + digits_pool + symbols_pool
    for _ in range(14):
        password.append(secrets.choice(all_pool))
        
    secrets.SystemRandom().shuffle(password)
    return "".join(password)

def get_user_by_email(db: Session, email: str) -> User | None:
    """Retrieves a user by email (case-insensitive)."""
    if not email or not email.strip():
        return None
    normalized_email = email.strip().lower()
    return db.query(User).filter(func.lower(User.email) == normalized_email).first()

def get_user_by_username(db: Session, username: str) -> User | None:
    """Retrieves a user by username (case-insensitive)."""
    if not username or not username.strip():
        return None
    normalized_username = username.strip().lower()
    return db.query(User).filter(func.lower(User.username) == normalized_username).first()

def get_user_by_identifier(db: Session, identifier: str) -> User | None:
    """Retrieves a user by username OR email (case-insensitive).
    If ambiguity occurs (e.g. username of User A equals email of User B),
    rejects safely to prevent wrong account access."""
    if not identifier or not identifier.strip():
        return None
    clean_identifier = identifier.strip().lower()

    matches = db.query(User).filter(
        or_(
            func.lower(User.username) == clean_identifier,
            func.lower(User.email) == clean_identifier
        )
    ).all()

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        exact_email = [u for u in matches if u.email and u.email.strip().lower() == clean_identifier]
        exact_uname = [u for u in matches if u.username and u.username.strip().lower() == clean_identifier]
        if len(exact_email) == 1 and len(exact_uname) == 0:
            return exact_email[0]
        elif len(exact_uname) == 1 and len(exact_email) == 0:
            return exact_uname[0]
        return None
    return None

def get_user_by_id(db: Session, user_id: int) -> User | None:
    """Retrieves a user by primary key ID."""
    if not user_id:
        return None
    return db.get(User, user_id)

def create_user(db: Session, username: str, email: str, password: str, role: str = "user") -> User:
    """Creates a new user record with hashed password. Safely rolls back on IntegrityError."""
    clean_username = username.strip()
    normalized_email = email.strip().lower()

    with db.no_autoflush:
        if db.query(User.id).filter(func.lower(User.username) == clean_username).first() is not None:
            raise ValueError("Username is already taken")
        if db.query(User.id).filter(func.lower(User.email) == normalized_email).first() is not None:
            raise ValueError("Email is already registered")

    pwd_hash = hash_password(password)
    user = User(
        username=clean_username,
        email=normalized_email,
        password_hash=pwd_hash,
        role=role,
        status="active",
        is_active=True,
        is_admin=(role in ("admin", "owner"))
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError as e:
        db.rollback()
        raise ValueError("Username or Email is already registered") from e

def authenticate_user(db: Session, identifier: str, password: str) -> User | None:
    """Authenticates a user by username or email and password. Returns None if inactive or not active status."""
    with db.no_autoflush:
        user = get_user_by_identifier(db, identifier)
    if not user:
        return None
    if getattr(user, "status", "active") != "active" or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user

def update_last_login(db: Session, user: User) -> None:
    """Updates the last_login_at timestamp for a user."""
    db_user = db.get(User, user.id)
    if db_user:
        db_user.last_login_at = datetime.now(timezone.utc)
        try:
            db.commit()
        except Exception:
            db.rollback()
