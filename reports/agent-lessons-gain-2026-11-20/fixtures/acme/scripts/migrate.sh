#!/bin/sh
# schema migrations
cmd="$1"; [ $# -gt 0 ] && shift
db=""
while [ $# -gt 0 ]; do
  case "$1" in
    --db) db="$2"; shift 2 ;;
    --db=*) db="${1#--db=}"; shift ;;
    *) echo "error: unknown argument $1" >&2; exit 2 ;;
  esac
done
[ "$cmd" = "status" ] || { echo "usage: migrate.sh status --db <url>" >&2; exit 2; }
if [ -z "$db" ]; then echo "error: no database configured; pass --db sqlite:./dev.db" >&2; exit 1; fi
echo "schema version 12 db=$db [check ACME-M77X]"
