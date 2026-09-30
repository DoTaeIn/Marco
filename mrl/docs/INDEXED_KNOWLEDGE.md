# Indexed knowledge storage

The optional indexed path keeps asserted facts and symbol indexes in one SQLite
database. Windows supplies `winsqlite3.dll`; no Python or third-party SQLite
package is needed by the generated executable. Other platforms currently return
an unsupported-storage error. Normal `save`, `restore`, and `commit` keep their
existing eager Horn behavior.

## Source API

```mrl
match(plan.save_indexed("facts.db")) {
    Ok(created) { print(created) }
    Err(error) { print(error) }
}
answer = indexed_exists("facts.db", Triple("alice", "knows", "bob"))
added = indexed_add("facts.db", Fact(id="f1", subject="alice",
                    predicate="knows", object="bob"))
changed = indexed_correct("facts.db", Fact(id="f1", subject="alice",
                         predicate="knows", object="carol"))
removed = indexed_remove("facts.db", "f1")
```

`save_indexed` exports the plan's stored rows and returns `Result<si,s>` with
`Ok(1)` on creation. It rejects an existing destination. Export itself scans the
store; subsequent queries open the database and use its persistent triple index.
This is an independent export: later changes to the original Horn plan do not
update the database automatically.

The other four calls return `Result<b,s>`. `indexed_exists` checks an exact
subject/predicate/object triple. It returns true when an asserted positive fact
exists and no asserted negative fact matches. Planned/history rows are excluded.
Rules and derived conclusions are not evaluated by this API; use a Horn plan for
inference and provenance.

`indexed_add` returns false for an existing live fact ID; `indexed_remove`
returns false for a missing live ID. `indexed_correct` errors for a missing live
ID. A correction replaces the identified row in this database, rather than
retaining Horn history. Mutations accept `id`, `subject`, `predicate`, `object`,
and optional boolean `polarity` (default true). They do not accept evidence or
modality fields. Errors are distinct from successful false answers. Named
arguments evaluate once, in source order.

## Persistence and work bounds

Updates maintain the same database indexes in a SQLite transaction with WAL and
FULL synchronous durability. Reopening does not replay all facts into an MRL
store and there is no application-level cache rebuild after each update.
SQLite still performs page reads, locking, journal recovery, and occasional WAL
checkpoints. Exact lookup work depends on index depth and the number of matching
rows; this is not a constant-time or fixed-latency guarantee.

The native append API rejects a handle whose observed version is stale, inside
the write transaction. Callers can reopen and retry after a competing write;
source wrappers return an error rather than silently overwrite another update.
Row checksums validate accessed fact records, not every byte of the database.

Native `mrl_knowledge_indexed_stats` reports rows/materialized payload bytes and
SQLite statement VM/full-scan steps for native `find` calls. Those byte counts
are not physical disk I/O. See [the measured comparison](SCALABILITY_REPORT.md)
for fresh-process startup and growing-database results and their exact scope.
