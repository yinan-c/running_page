# Pulling upstream code without upstream's runs

This repository is a fork of [fankangsong/running_page](https://github.com/fankangsong/running_page)
(itself a fork of [yihong0618/running_page](https://github.com/yihong0618/running_page)).
It is kept for the code — the extended data model, `ActivityCurves`,
`KmSplitsTable`, the Strava sync scheduler — and not for the activity data.

Upstream commits its own workouts daily (`sync and update data`), so merging it
naively drags another athlete's runs into this page.

## One-time setup per clone

`.gitattributes` marks every data path with `merge=keepmine`, but Git only
honours it once the driver is registered locally:

```bash
git config merge.keepmine.driver true
```

`true` is the shell builtin that exits 0 without touching the file, which tells
Git the merge "succeeded" and leaves our version in place.

## Merging upstream

```bash
git fetch upstream
git merge upstream/master
```

Code changes merge normally; `activities.json`, `data.db`, the generated SVGs
and the raw exports keep our versions.

Verify before pushing — activity count should be ours, not upstream's:

```bash
python -c "import json; print(len(json.load(open('src/static/activities.json'))))"
```

## If data does slip through

```bash
git checkout --ours src/static/activities.json run_page/data.db
python run_page/strava_sync.py $CLIENT_ID $CLIENT_SECRET $REFRESH_TOKEN --only-run
```

The sync rebuilds `activities.json` from `data.db`, so restoring the database
and re-running the sync is always a valid recovery path.
