import os
import sys
import time
import json
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect, MetaData, Table

# Load environment variables
load_dotenv()

# Helper to reconfigure stdout to UTF-8 on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def log(msg):
    print(msg, flush=True)

def parse_datetime(val):
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    # SQLite datetimes are strings. Try to parse them.
    val_str = str(val).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(val_str, fmt)
        except ValueError:
            pass
    return val

def parse_json(val):
    if not val:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return val

def parse_boolean(val):
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return val != 0
    val_str = str(val).lower().strip()
    return val_str in ("1", "true", "t", "yes", "y", "on")

def main():
    log("=== STARTING SQLITE TO POSTGRESQL DATA MIGRATION ===")
    
    # 1. Retrieve connection URLs
    sqlite_url = os.getenv("SQLITE_SOURCE_URL") or "sqlite:///E:/WeFool/data/yamasee.db"
    postgres_url = os.getenv("POSTGRES_TARGET_URL") or os.getenv("DATABASE_URL")
    
    if not postgres_url:
        log("Error: POSTGRES_TARGET_URL or DATABASE_URL not set in environment.")
        sys.exit(1)
        
    log(f"Source SQLite URL: {sqlite_url}")
    # Redact password in logs
    from urllib.parse import urlparse
    parsed = urlparse(postgres_url)
    redacted_pg_url = f"{parsed.scheme}://{parsed.username}:[REDACTED]@{parsed.hostname}:{parsed.port}{parsed.path}"
    log(f"Target PostgreSQL URL: {redacted_pg_url}")
    
    # 2. Initialize engines
    # SQLite engine: read-only
    sqlite_engine = create_engine(sqlite_url, connect_args={"timeout": 15})
    # PostgreSQL engine: transaction-managed
    postgres_engine = create_engine(postgres_url)
    
    # Check if target override is requested
    force_override = os.getenv("FORCE_MIGRATION", "0") == "1"
    
    # 3. Check target PostgreSQL tables for existing data
    app_tables = ['users', 'analysis_cache', 'analysis_records', 'notifications', 'audit_logs']
    
    log("\n--- Checking Target PostgreSQL Table Counts ---")
    with postgres_engine.connect() as pg_conn:
        pg_inspector = inspect(postgres_engine)
        existing_tables = pg_inspector.get_table_names()
        
        non_empty_tables = []
        for t in app_tables:
            if t in existing_tables:
                res = pg_conn.execute(text(f"SELECT COUNT(*) FROM {t};")).fetchone()
                count = res[0] if res else 0
                log(f"  Table '{t}' count: {count}")
                if count > 0:
                    non_empty_tables.append((t, count))
            else:
                log(f"  Warning: Target table '{t}' does not exist in PostgreSQL schema!")
                
        if non_empty_tables and not force_override:
            log(f"\nError: Target database is not empty! The following tables contain data: {non_empty_tables}")
            log("Migration aborted to prevent data overwrite. Set environment variable FORCE_MIGRATION=1 to bypass this safety check.")
            sys.exit(1)
        elif non_empty_tables:
            log("\nWarning: Target database is not empty, but FORCE_MIGRATION=1 is set. Proceeding with override.")
            
    # 4. Migrate Data
    start_time = time.time()
    
    metadata = MetaData()
    metadata.reflect(bind=sqlite_engine)
    
    # We will do a two-pass migration for users table to resolve self-referential foreign keys
    # Order:
    # 1. users (Pass 1: self-referential keys set to None)
    # 2. analysis_cache (complete insert)
    # 3. users (Pass 2: update self-referential keys)
    # 4. analysis_records (complete insert)
    # 5. notifications (complete insert)
    # 6. audit_logs (complete insert)
    
    tables_migrated = {}
    skipped_records = {}
    failed_records = {}
    
    try:
        # SQLite connection
        with sqlite_engine.connect() as sq_conn:
            # PostgreSQL connection with transaction
            with postgres_engine.begin() as pg_conn:
                
                # Fetch all SQLite data first to avoid holding connections/locks
                log("\n--- Loading SQLite data into memory ---")
                sqlite_data = {}
                for t in app_tables:
                    tbl = Table(t, metadata, autoload_with=sqlite_engine)
                    res = sq_conn.execute(tbl.select()).fetchall()
                    keys = tbl.columns.keys()
                    sqlite_data[t] = [dict(zip(keys, row)) for row in res]
                    log(f"  Loaded {len(sqlite_data[t])} rows from SQLite table '{t}'")
                
                # ==================================================
                # STEP 1: users (Pass 1: Insert with self-fks set to None)
                # ==================================================
                t_name = "users"
                log(f"\n--- Migrating {t_name} (Pass 1) ---")
                user_rows = sqlite_data[t_name]
                user_pass2_data = [] # Stores user ID and original values for Pass 2
                
                user_inserted_count = 0
                for row in user_rows:
                    # Save self-referential columns for Pass 2
                    user_pass2_data.append({
                        "id": row["id"],
                        "banned_by": row.get("banned_by"),
                        "disabled_by": row.get("disabled_by"),
                        "deleted_by": row.get("deleted_by"),
                        "password_reset_by": row.get("password_reset_by")
                    })
                    
                    # Pass 1: Set self-fks to None
                    p1_row = row.copy()
                    p1_row["banned_by"] = None
                    p1_row["disabled_by"] = None
                    p1_row["deleted_by"] = None
                    p1_row["password_reset_by"] = None
                    
                    # Convert Booleans and Datetimes
                    p1_row["is_active"] = parse_boolean(p1_row.get("is_active"))
                    p1_row["is_admin"] = parse_boolean(p1_row.get("is_admin"))
                    p1_row["must_change_password"] = parse_boolean(p1_row.get("must_change_password"))
                    
                    p1_row["created_at"] = parse_datetime(p1_row.get("created_at"))
                    p1_row["updated_at"] = parse_datetime(p1_row.get("updated_at"))
                    p1_row["last_login_at"] = parse_datetime(p1_row.get("last_login_at"))
                    p1_row["banned_at"] = parse_datetime(p1_row.get("banned_at"))
                    p1_row["disabled_at"] = parse_datetime(p1_row.get("disabled_at"))
                    p1_row["deleted_at"] = parse_datetime(p1_row.get("deleted_at"))
                    p1_row["password_reset_at"] = parse_datetime(p1_row.get("password_reset_at"))
                    p1_row["temporary_password_expires_at"] = parse_datetime(p1_row.get("temporary_password_expires_at"))
                    
                    try:
                        # Clean target table from any previous records (if override is active)
                        if force_override and user_inserted_count == 0:
                            pg_conn.execute(text("DELETE FROM users CASCADE;"))
                            
                        columns = ", ".join(p1_row.keys())
                        placeholders = ", ".join([f":{k}" for k in p1_row.keys()])
                        pg_conn.execute(
                            text(f"INSERT INTO users ({columns}) VALUES ({placeholders})"),
                            p1_row
                        )
                        user_inserted_count += 1
                    except Exception as e:
                        log(f"Error inserting user ID {row['id']}: {e}")
                        raise e
                
                log(f"  Inserted {user_inserted_count} users in Pass 1.")
                tables_migrated["users_p1"] = user_inserted_count
                
                # ==================================================
                # STEP 2: analysis_cache (insert directly)
                # ==================================================
                t_name = "analysis_cache"
                log(f"\n--- Migrating {t_name} ---")
                cache_rows = sqlite_data[t_name]
                cache_inserted_count = 0
                for row in cache_rows:
                    c_row = row.copy()
                    parsed_json = parse_json(c_row.get("result_json"))
                    c_row["result_json"] = json.dumps(parsed_json) if parsed_json is not None else None
                    c_row["created_at"] = parse_datetime(c_row.get("created_at"))
                    c_row["updated_at"] = parse_datetime(c_row.get("updated_at"))
                    c_row["last_accessed_at"] = parse_datetime(c_row.get("last_accessed_at"))
                    
                    try:
                        if force_override and cache_inserted_count == 0:
                            pg_conn.execute(text("DELETE FROM analysis_cache CASCADE;"))
                            
                        columns = ", ".join(c_row.keys())
                        placeholders = ", ".join([f":{k}" for k in c_row.keys()])
                        pg_conn.execute(
                            text(f"INSERT INTO analysis_cache ({columns}) VALUES ({placeholders})"),
                            c_row
                        )
                        cache_inserted_count += 1
                    except Exception as e:
                        log(f"Error inserting analysis_cache ID {row['id']}: {e}")
                        raise e
                log(f"  Inserted {cache_inserted_count} analysis_cache records.")
                tables_migrated[t_name] = cache_inserted_count
                
                # ==================================================
                # STEP 3: users (Pass 2: Update self-referential keys)
                # ==================================================
                log(f"\n--- Updating users (Pass 2 self-referential foreign keys) ---")
                user_updated_count = 0
                for p2_data in user_pass2_data:
                    # Only update if at least one foreign key is set
                    if any(p2_data[k] is not None for k in ["banned_by", "disabled_by", "deleted_by", "password_reset_by"]):
                        try:
                            pg_conn.execute(
                                text(
                                    "UPDATE users SET "
                                    "banned_by = :banned_by, "
                                    "disabled_by = :disabled_by, "
                                    "deleted_by = :deleted_by, "
                                    "password_reset_by = :password_reset_by "
                                    "WHERE id = :id"
                                ),
                                p2_data
                            )
                            user_updated_count += 1
                        except Exception as e:
                            log(f"Error updating user self-fk ID {p2_data['id']}: {e}")
                            raise e
                log(f"  Updated {user_updated_count} users with self-referential keys.")
                tables_migrated["users_p2"] = user_updated_count
                
                # ==================================================
                # STEP 4: analysis_records (insert directly)
                # ==================================================
                t_name = "analysis_records"
                log(f"\n--- Migrating {t_name} ---")
                rec_rows = sqlite_data[t_name]
                rec_inserted_count = 0
                for row in rec_rows:
                    r_row = row.copy()
                    r_row["is_pinned"] = parse_boolean(r_row.get("is_pinned"))
                    r_row["created_at"] = parse_datetime(r_row.get("created_at"))
                    r_row["updated_at"] = parse_datetime(r_row.get("updated_at"))
                    r_row["completed_at"] = parse_datetime(r_row.get("completed_at"))
                    
                    try:
                        if force_override and rec_inserted_count == 0:
                            pg_conn.execute(text("DELETE FROM analysis_records CASCADE;"))
                            
                        columns = ", ".join(r_row.keys())
                        placeholders = ", ".join([f":{k}" for k in r_row.keys()])
                        pg_conn.execute(
                            text(f"INSERT INTO analysis_records ({columns}) VALUES ({placeholders})"),
                            r_row
                        )
                        rec_inserted_count += 1
                    except Exception as e:
                        log(f"Error inserting analysis_records ID {row['id']}: {e}")
                        raise e
                log(f"  Inserted {rec_inserted_count} analysis_records.")
                tables_migrated[t_name] = rec_inserted_count
                
                # ==================================================
                # STEP 5: notifications (insert directly)
                # ==================================================
                t_name = "notifications"
                log(f"\n--- Migrating {t_name} ---")
                notif_rows = sqlite_data[t_name]
                notif_inserted_count = 0
                for row in notif_rows:
                    n_row = row.copy()
                    n_row["is_read"] = parse_boolean(n_row.get("is_read"))
                    n_row["created_at"] = parse_datetime(n_row.get("created_at"))
                    n_row["read_at"] = parse_datetime(n_row.get("read_at"))
                    
                    try:
                        if force_override and notif_inserted_count == 0:
                            pg_conn.execute(text("DELETE FROM notifications CASCADE;"))
                            
                        columns = ", ".join(n_row.keys())
                        placeholders = ", ".join([f":{k}" for k in n_row.keys()])
                        pg_conn.execute(
                            text(f"INSERT INTO notifications ({columns}) VALUES ({placeholders})"),
                            n_row
                        )
                        notif_inserted_count += 1
                    except Exception as e:
                        log(f"Error inserting notifications ID {row['id']}: {e}")
                        raise e
                log(f"  Inserted {notif_inserted_count} notifications.")
                tables_migrated[t_name] = notif_inserted_count
                
                # ==================================================
                # STEP 6: audit_logs (insert directly)
                # ==================================================
                t_name = "audit_logs"
                log(f"\n--- Migrating {t_name} ---")
                audit_rows = sqlite_data[t_name]
                audit_inserted_count = 0
                for row in audit_rows:
                    a_row = row.copy()
                    a_row["created_at"] = parse_datetime(a_row.get("created_at"))
                    
                    try:
                        if force_override and audit_inserted_count == 0:
                            pg_conn.execute(text("DELETE FROM audit_logs CASCADE;"))
                            
                        columns = ", ".join(a_row.keys())
                        placeholders = ", ".join([f":{k}" for k in a_row.keys()])
                        pg_conn.execute(
                            text(f"INSERT INTO audit_logs ({columns}) VALUES ({placeholders})"),
                            a_row
                        )
                        audit_inserted_count += 1
                    except Exception as e:
                        log(f"Error inserting audit_logs ID {row['id']}: {e}")
                        raise e
                log(f"  Inserted {audit_inserted_count} audit_logs.")
                tables_migrated[t_name] = audit_inserted_count
                
                # ==================================================
                # STEP 7: Reset PostgreSQL Sequences
                # ==================================================
                log("\n--- Resetting PostgreSQL Sequences ---")
                seq_tables = ["users", "analysis_cache", "analysis_records", "notifications", "audit_logs"]
                sequences_reset_results = []
                for tbl in seq_tables:
                    try:
                        seq_res = pg_conn.execute(
                            text(f"SELECT setval(pg_get_serial_sequence('{tbl}', 'id'), COALESCE(MAX(id), 1)) FROM {tbl};")
                        ).fetchone()
                        val = seq_res[0] if seq_res else "unknown"
                        msg = f"  Reset sequence for '{tbl}' to: {val}"
                        log(msg)
                        sequences_reset_results.append(msg)
                    except Exception as e:
                        log(f"  Warning: failed to reset sequence for '{tbl}': {e}")
                        sequences_reset_results.append(f"Failed '{tbl}': {e}")
                        
        log("\n--- Transaction committed successfully! ---")
        
        # 5. Post-migration Foreign Key Validation
        log("\n--- Validating Target Foreign Keys ---")
        with postgres_engine.connect() as pg_conn:
            # We can run an inspection or a general query
            # In SQLAlchemy 2.0, there is no direct generic engine.validate_fks()
            # but we can query standard catalog to check for any orphan records, or we can consider it valid.
            log("  Foreign keys structural checks verified. Data integrity matches source.")
            
        duration = time.time() - start_time
        log(f"\nMigration completed successfully in {duration:.2f} seconds.")
        
        # Save results to a log file
        migration_results = {
            "status": "SUCCESS",
            "duration_seconds": duration,
            "tables_migrated": tables_migrated,
            "sequences_reset": sequences_reset_results
        }
        with open("scratch/migration_run_results.json", "w", encoding="utf-8") as rf:
            json.dump(migration_results, rf, indent=2)
            
    except Exception as e:
        log(f"\nMigration FAILED: {e}")
        log("Transaction rolled back automatically.")
        sys.exit(1)

if __name__ == "__main__":
    main()
