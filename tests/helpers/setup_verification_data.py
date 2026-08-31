import os
import sys

# Default to e2e database if not set
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "sqlite:///./data/yamasee_e2e.db"

# Safeguard check
db_url = os.environ["DATABASE_URL"]
if "yamasee.db" in db_url and not db_url.endswith("yamasee_e2e.db") and os.getenv("FORCE_VERIFICATION_DB") != "1":
    print("ERROR: Refusing to run setup script against the real development database.")
    print("To bypass this safeguard, set environment variable FORCE_VERIFICATION_DB=1")
    sys.exit(1)

from database import SessionLocal, Base, engine
from models.user import User
from services.auth_service import create_user
from sqlalchemy import text

def setup():
    # Ensure all tables exist in the target database
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # Clean up database
        db.query(User).delete()
        db.execute(text("DELETE FROM audit_logs"))
        db.commit()

        # Create verification accounts
        create_user(db, "OwnerTest", "owner@example.com", "OwnerPass123!", role="owner")
        create_user(db, "AdminTest", "admin@example.com", "AdminPass123!", role="admin")
        create_user(db, "NormalTest", "normal@example.com", "NormalPass123!", role="user")
        create_user(db, "DuplicateTest", "duplicate@example.com", "DuplicatePass123!", role="user")
        create_user(db, "DisposableTest", "disposable@example.com", "DisposablePass123!", role="user")
        
        db.commit()
        print("Verification data populated successfully!")
    finally:
        db.close()

if __name__ == "__main__":
    setup()
