use chrono::{DateTime, Datelike, LocalResult, NaiveDate, NaiveTime, SecondsFormat, TimeZone, Utc};
use chrono_tz::Tz;
use rusqlite::{Connection, ErrorCode, OpenFlags, TransactionBehavior, params};
use serde_json::{Value, json};
use std::{path::Path, time::Duration};

pub type Result<T> = std::result::Result<T, &'static str>;
const MAX_WINDOW: i64 = 31 * 86_400;
const GRACE_SECONDS: i64 = 60;

fn sql(error: rusqlite::Error) -> &'static str {
    match error.sqlite_error_code() {
        Some(ErrorCode::DatabaseBusy | ErrorCode::DatabaseLocked) => "store_busy",
        _ => "database_error",
    }
}

pub fn time(value: &str) -> Result<DateTime<Utc>> {
    let parsed = DateTime::parse_from_rfc3339(value)
        .map_err(|_| "invalid_timestamp")?
        .with_timezone(&Utc);
    if !(2000..=2100).contains(&parsed.year()) || parsed.timestamp_subsec_nanos() != 0 {
        return Err("unsupported_timestamp");
    }
    Ok(parsed)
}

fn stamp(value: i64) -> String {
    DateTime::from_timestamp(value, 0)
        .unwrap()
        .to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 48
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_".contains(&b))
}

// region schema
pub fn init(path: &Path) -> Result<Value> {
    if path.exists() {
        return Err("database_exists");
    }
    let mut db = Connection::open(path).map_err(sql)?;
    db.busy_timeout(Duration::ZERO).map_err(sql)?;
    db.execute_batch(
        "PRAGMA journal_mode=DELETE; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;",
    )
    .map_err(sql)?;
    let tx = db
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(sql)?;
    tx.execute_batch(
        "CREATE TABLE schedules (
            id TEXT PRIMARY KEY NOT NULL,
            zone TEXT NOT NULL,
            hour INTEGER NOT NULL CHECK(hour BETWEEN 0 AND 23),
            minute INTEGER NOT NULL CHECK(minute BETWEEN 0 AND 59),
            misfire TEXT NOT NULL CHECK(misfire IN ('coalesce','skip')),
            cursor_utc INTEGER NOT NULL
         ) STRICT;
         CREATE TABLE tasks (
            trigger_id TEXT PRIMARY KEY NOT NULL,
            schedule_id TEXT NOT NULL REFERENCES schedules(id),
            due_utc INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind='daily_report'),
            state TEXT NOT NULL CHECK(state='queued'),
            UNIQUE(schedule_id, due_utc)
         ) STRICT;
         PRAGMA user_version=1;",
    )
    .map_err(sql)?;
    tx.commit().map_err(sql)?;
    Ok(json!({"status":"initialized", "schema":1}))
}
// endregion schema

pub fn open(path: &Path) -> Result<Connection> {
    // Read/write without CREATE: a missing path must not become an empty database.
    let db = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_WRITE).map_err(sql)?;
    db.busy_timeout(Duration::ZERO).map_err(sql)?;
    db.execute_batch("PRAGMA foreign_keys=ON; PRAGMA synchronous=FULL;")
        .map_err(sql)?;
    let version: i64 = db
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .map_err(sql)?;
    if version != 1 {
        return Err("unsupported_schema");
    }
    let integrity: String = db
        .query_row("PRAGMA quick_check", [], |row| row.get(0))
        .map_err(sql)?;
    if integrity != "ok" {
        return Err("corrupt_database");
    }
    Ok(db)
}

#[derive(Debug, Clone)]
struct Schedule {
    id: String,
    zone: Tz,
    hour: u32,
    minute: u32,
    misfire: String,
    cursor: i64,
}

fn validate(id: &str, zone: &str, hhmm: &str, misfire: &str) -> Result<(Tz, NaiveTime)> {
    if !identifier(id) {
        return Err("invalid_id");
    }
    let zone = zone.parse::<Tz>().map_err(|_| "invalid_timezone")?;
    let local = NaiveTime::parse_from_str(hhmm, "%H:%M").map_err(|_| "invalid_local_time")?;
    if !matches!(misfire, "coalesce" | "skip") {
        return Err("invalid_misfire");
    }
    Ok((zone, local))
}

pub fn add(
    db: &mut Connection,
    id: &str,
    zone: &str,
    hhmm: &str,
    misfire: &str,
    start: &str,
) -> Result<Value> {
    use chrono::Timelike;
    let (_, local) = validate(id, zone, hhmm, misfire)?;
    let start = time(start)?.timestamp();
    let tx = db
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(sql)?;
    let exists: bool = tx
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM schedules WHERE id=?1)",
            [id],
            |r| r.get(0),
        )
        .map_err(sql)?;
    if exists {
        return Err("duplicate_schedule");
    }
    let count: i64 = tx
        .query_row("SELECT count(*) FROM schedules", [], |r| r.get(0))
        .map_err(sql)?;
    if count >= 32 {
        return Err("schedule_limit");
    }
    tx.execute(
        "INSERT INTO schedules VALUES (?1,?2,?3,?4,?5,?6)",
        params![id, zone, local.hour(), local.minute(), misfire, start],
    )
    .map_err(sql)?;
    tx.commit().map_err(sql)?;
    Ok(
        json!({"status":"added", "id":id, "cursor":stamp(start), "timezone":zone, "local_time":hhmm, "misfire":misfire}),
    )
}

// region timezone
fn instants(zone: Tz, date: NaiveDate, hour: u32, minute: u32) -> Result<Vec<i64>> {
    let local = date
        .and_hms_opt(hour, minute, 0)
        .ok_or("invalid_local_time")?;
    match zone.from_local_datetime(&local) {
        LocalResult::Single(value) => Ok(vec![value.timestamp()]),
        LocalResult::Ambiguous(earlier, later) => Ok(vec![earlier.timestamp(), later.timestamp()]),
        LocalResult::None => Ok(vec![]),
    }
}

pub fn resolve(zone: &str, date: &str, hhmm: &str) -> Result<Value> {
    use chrono::Timelike;
    let (zone, local) = validate("resolve", zone, hhmm, "coalesce")?;
    let date = NaiveDate::parse_from_str(date, "%Y-%m-%d").map_err(|_| "invalid_date")?;
    if !(2000..=2100).contains(&date.year()) {
        return Err("unsupported_timestamp");
    }
    let values = instants(zone, date, local.hour(), local.minute())?;
    Ok(
        json!({"status":"resolved", "zone":zone.to_string(), "date":date.to_string(), "local_time":hhmm,
        "mapping":match values.len() {0=>"gap", 1=>"single", _=>"fold"},
        "utc":values.iter().map(|v| stamp(*v)).collect::<Vec<_>>(),
        "chosen":values.first().map(|v| stamp(*v))}),
    )
}
// endregion timezone

// region due
fn due(schedule: &Schedule, now: i64) -> Result<Vec<i64>> {
    let delta = now.checked_sub(schedule.cursor).ok_or("invalid_cursor")?;
    if delta < 0 {
        return Err("clock_regression");
    }
    if delta > MAX_WINDOW {
        return Err("scan_window_limit");
    }
    let cursor = DateTime::from_timestamp(schedule.cursor, 0).ok_or("invalid_cursor")?;
    let end = DateTime::from_timestamp(now, 0).ok_or("invalid_cursor")?;
    if !(2000..=2100).contains(&cursor.year()) {
        return Err("invalid_cursor");
    }
    // UTC dates with a margin cover the local dates for the supported date range.
    let mut date = cursor.date_naive().pred_opt().ok_or("invalid_cursor")?;
    let last = end.date_naive().succ_opt().ok_or("invalid_cursor")?;
    let mut found = Vec::new();
    while date <= last {
        // Choose the earlier occurrence in a fold. A gap contributes no trigger.
        if let Some(instant) =
            instants(schedule.zone, date, schedule.hour, schedule.minute)?.first()
            && *instant > schedule.cursor
            && *instant <= now
        {
            found.push(*instant);
        }
        date = date.succ_opt().ok_or("invalid_cursor")?;
    }
    found.sort_unstable();
    found.dedup();
    Ok(found)
}

fn select_due(values: &[i64], now: i64, misfire: &str) -> Option<i64> {
    values
        .last()
        .copied()
        .filter(|latest| misfire == "coalesce" || now - latest <= GRACE_SECONDS)
}
// endregion due

fn schedules(db: &Connection) -> Result<Vec<Schedule>> {
    let mut stmt = db
        .prepare("SELECT id,zone,hour,minute,misfire,cursor_utc FROM schedules ORDER BY id")
        .map_err(sql)?;
    let rows = stmt
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, u32>(2)?,
                r.get::<_, u32>(3)?,
                r.get::<_, String>(4)?,
                r.get::<_, i64>(5)?,
            ))
        })
        .map_err(sql)?;
    let mut all = Vec::new();
    for row in rows {
        let (id, zone, hour, minute, misfire, cursor) = row.map_err(sql)?;
        let (zone, _) = validate(&id, &zone, &format!("{hour:02}:{minute:02}"), &misfire)?;
        let cursor_date = DateTime::from_timestamp(cursor, 0).ok_or("invalid_cursor")?;
        if !(2000..=2100).contains(&cursor_date.year()) {
            return Err("invalid_cursor");
        }
        all.push(Schedule {
            id,
            zone,
            hour,
            minute,
            misfire,
            cursor,
        });
        if all.len() > 32 {
            return Err("schedule_limit");
        }
    }
    Ok(all)
}

fn enqueue(db: &Connection, id: &str, instant: i64) -> Result<usize> {
    db.execute(
        "INSERT INTO tasks(trigger_id,schedule_id,due_utc,kind,state)
        VALUES (?1,?2,?3,'daily_report','queued') ON CONFLICT(schedule_id,due_utc) DO NOTHING",
        params![format!("{id}@{instant}"), id, instant],
    )
    .map_err(sql)
}

// region transaction
pub fn tick(db: &mut Connection, now: &str, fault: &str) -> Result<Value> {
    let now = time(now)?.timestamp();
    let tx = db
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(sql)?;
    let mut reports = Vec::new();
    for schedule in schedules(&tx)? {
        let values = due(&schedule, now)?;
        let selected = select_due(&values, now, &schedule.misfire);
        let inserted = if let Some(instant) = selected {
            enqueue(&tx, &schedule.id, instant)?
        } else {
            0
        };
        if inserted > 0 {
            let count: i64 = tx
                .query_row("SELECT count(*) FROM tasks", [], |r| r.get(0))
                .map_err(sql)?;
            if count > 4096 {
                return Err("queue_limit");
            }

            if fault == "--fail-after-insert" {
                return Err("injected_after_insert");
            }
            if fault == "--exit-after-insert" {
                std::process::exit(73);
            }
        }
        tx.execute(
            "UPDATE schedules SET cursor_utc=?1 WHERE id=?2",
            params![now, schedule.id],
        )
        .map_err(sql)?;
        reports.push(
            json!({"id":schedule.id, "before":stamp(schedule.cursor), "cursor":stamp(now),
            "due_count":values.len(), "selected":selected.map(stamp), "inserted":inserted,
            "discarded":values.len() - usize::from(selected.is_some())}),
        );
    }
    tx.commit().map_err(sql)?;
    if fault == "--exit-after-commit" {
        std::process::exit(74);
    }
    Ok(json!({"status":"committed", "now":stamp(now), "reports":reports}))
}
// endregion transaction

pub fn show(db: &Connection) -> Result<Value> {
    // Keep schedules and tasks in one consistent read transaction.
    let tx = db.unchecked_transaction().map_err(sql)?;
    let schedules = schedules(&tx)?.iter().map(|s| json!({"id":s.id, "timezone":s.zone.to_string(),
        "local_time":format!("{:02}:{:02}",s.hour,s.minute), "misfire":s.misfire, "cursor":stamp(s.cursor)})).collect::<Vec<_>>();
    let mut statement = tx.prepare("SELECT trigger_id,schedule_id,due_utc,kind,state FROM tasks ORDER BY due_utc,schedule_id LIMIT 4097").map_err(sql)?;
    let rows = statement
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, i64>(2)?,
                r.get::<_, String>(3)?,
                r.get::<_, String>(4)?,
            ))
        })
        .map_err(sql)?;
    let mut tasks = Vec::new();
    for row in rows {
        let (trigger_id, schedule_id, due, kind, state) = row.map_err(sql)?;
        let date = DateTime::from_timestamp(due, 0).ok_or("invalid_task")?;
        if !(2000..=2100).contains(&date.year()) || trigger_id != format!("{schedule_id}@{due}") {
            return Err("invalid_task");
        }
        tasks.push(json!({"trigger_id":trigger_id,"schedule_id":schedule_id,"due":stamp(due),"kind":kind,"state":state}));
        if tasks.len() > 4096 {
            return Err("queue_limit");
        }
    }
    drop(statement);
    tx.commit().map_err(sql)?;
    Ok(json!({"status":"snapshot", "schedules":schedules, "tasks":tasks}))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn schedule(zone: &str, hhmm: &str, cursor: &str) -> Schedule {
        use chrono::Timelike;
        let (zone, local) = validate("report", zone, hhmm, "coalesce").unwrap();
        Schedule {
            id: "report".into(),
            zone,
            hour: local.hour(),
            minute: local.minute(),
            misfire: "coalesce".into(),
            cursor: time(cursor).unwrap().timestamp(),
        }
    }
    #[test]
    fn interval_is_open_then_closed() {
        let s = schedule("Asia/Shanghai", "09:00", "2026-11-07T00:59:00Z");
        let t = time("2026-11-07T01:00:00Z").unwrap().timestamp();
        assert_eq!(due(&s, t).unwrap(), vec![t]);
        assert!(due(&Schedule { cursor: t, ..s }, t).unwrap().is_empty());
    }
    #[test]
    fn dst_gap_has_no_trigger() {
        let s = schedule("America/New_York", "02:30", "2026-03-08T05:00:00Z");
        assert!(
            due(&s, time("2026-03-09T03:59:59Z").unwrap().timestamp())
                .unwrap()
                .is_empty()
        );
    }
    #[test]
    fn dst_fold_uses_earlier_once() {
        let s = schedule("America/New_York", "01:30", "2026-11-01T04:00:00Z");
        let v = due(&s, time("2026-11-01T07:00:00Z").unwrap().timestamp()).unwrap();
        assert_eq!(v, vec![time("2026-11-01T05:30:00Z").unwrap().timestamp()]);
    }
    #[test]
    fn next_daily_time_is_not_plus_86400() {
        let s = schedule("America/New_York", "09:00", "2026-03-07T00:00:00Z");
        let v = due(&s, time("2026-03-09T00:00:00Z").unwrap().timestamp()).unwrap();
        assert_eq!(v[1] - v[0], 23 * 3600);
    }
    #[test]
    fn coalesce_selects_latest() {
        assert_eq!(select_due(&[100, 200, 300], 1000, "coalesce"), Some(300));
    }
    #[test]
    fn skip_has_inclusive_grace_boundary() {
        assert_eq!(select_due(&[100], 160, "skip"), Some(100));
        assert_eq!(select_due(&[100], 161, "skip"), None);
    }
    #[test]
    fn clock_regression_and_window_reject() {
        let s = schedule("UTC", "09:00", "2026-11-07T00:00:00Z");
        assert_eq!(due(&s, s.cursor - 1), Err("clock_regression"));
        assert_eq!(due(&s, s.cursor + MAX_WINDOW + 1), Err("scan_window_limit"));
    }
    #[test]
    fn timestamps_normalize_offsets() {
        assert_eq!(
            time("2026-11-07T09:00:00+08:00"),
            time("2026-11-07T01:00:00Z")
        );
        assert!(time("2026-11-07T01:00:00.1Z").is_err());
        assert!(time("2026-11-07T01:00:00").is_err());
    }
    #[test]
    fn invalid_parameters_rejected() {
        assert!(validate("../x", "UTC", "09:00", "coalesce").is_err());
        assert!(validate("x", "wrong/zone", "09:00", "coalesce").is_err());
        assert!(validate("x", "UTC", "25:00", "coalesce").is_err());
        assert!(validate("x", "UTC", "09:00", "all").is_err());
    }
    #[test]
    fn unique_identity_is_enforced_by_sqlite() {
        let mut db = Connection::open_in_memory().unwrap();
        db.execute_batch("CREATE TABLE tasks(trigger_id TEXT PRIMARY KEY,schedule_id TEXT,due_utc INTEGER,kind TEXT,state TEXT,UNIQUE(schedule_id,due_utc));").unwrap();
        let tx = db.transaction().unwrap();
        assert_eq!(enqueue(&tx, "report", 123).unwrap(), 1);
        assert_eq!(enqueue(&tx, "report", 123).unwrap(), 0);
    }
}
