import argparse
import sys
from database import SessionLocal
from models.user import User
from utils.audit import record_audit_event

def main():
    parser = argparse.ArgumentParser(description="Grant or revoke admin privileges for a user.")
    parser.add_argument("--email", required=True, help="User email address")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--remove", action="store_true", help="Revoke admin privilege (restore to normal user)")

    args = parser.parse_args()
    email_clean = args.email.strip().lower()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email_clean).first()
        if not user:
            print(f"Error: User with email '{email_clean}' not found.", file=sys.stderr)
            sys.exit(1)

        target_admin_status = not args.remove
        action_name = "Grant Admin" if target_admin_status else "Revoke Admin"

        if user.is_admin == target_admin_status:
            print(f"User '{user.username}' ({user.email}) is already {'an Admin' if target_admin_status else 'a Normal User'}.")
            return

        print(f"Target User:")
        print(f"  ID: {user.id}")
        print(f"  Username: {user.username}")
        print(f"  Email: {user.email}")
        print(f"  Current Status: {'Admin' if user.is_admin else 'Normal User'}")
        print(f"  New Status: {'Admin' if target_admin_status else 'Normal User'}")

        if not args.yes:
            confirm = input(f"Are you sure you want to {action_name} for this user? [y/N]: ").strip().lower()
            if confirm not in ("y", "yes"):
                print("Operation cancelled.")
                return

        user.is_admin = target_admin_status
        db.commit()

        event_name = "admin_role_granted" if target_admin_status else "admin_role_removed"
        record_audit_event(
            event_type=event_name,
            user_id=user.id,
            details={"email": user.email, "is_admin": user.is_admin}
        )

        print(f"Successfully updated user '{user.username}' ({user.email}). New role: {'Admin' if target_admin_status else 'Normal User'}.")

    finally:
        db.close()

if __name__ == "__main__":
    main()
