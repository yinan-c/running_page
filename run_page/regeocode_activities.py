#!/usr/bin/env python3
"""Rewrite location_country for activities already in the database.

Activities synced before the geocoder switched to English carry Nominatim's
full localised address, e.g.

    Nine Elms, London Borough of Wandsworth, 大倫敦;大伦敦, 英格兰;英格蘭, SW11 7AY, 英国;英國

OSM packs both Chinese scripts into a single name:zh tag, so the site rendered
countries as "英国;英國". This re-geocodes each activity from the first point of
its stored polyline and replaces the value with "City, State, Country".

    python run_page/regeocode_activities.py            # rewrite everything
    python run_page/regeocode_activities.py --dry-run  # show what would change
    python run_page/regeocode_activities.py --only-legacy  # skip clean rows

Nominatim allows one request per second; the delay is not optional.
"""

import argparse
import sys
import time

import polyline
from config import SQL_FILE
from generator.db import Activity, init_db, reverse_geocode

# Nominatim's usage policy: at most one request per second.
REQUEST_DELAY_SECONDS = 1.1


def start_point(summary_polyline):
    """First (lat, lon) of an encoded polyline, or None when unusable."""
    if not summary_polyline:
        return None
    try:
        points = polyline.decode(summary_polyline)
    except Exception:
        return None
    return points[0] if points else None


def looks_legacy(value):
    """True for the localised free-form addresses written by the old geocoder."""
    if not value:
        return False
    # ";" only ever appears in the duplicated OSM name tags, and a long address
    # means the whole display_name was stored rather than three components.
    return ";" in value or value.count(",") > 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the replacements without writing them",
    )
    parser.add_argument(
        "--only-legacy",
        action="store_true",
        help="skip activities whose location already looks clean",
    )
    options = parser.parse_args()

    session = init_db(SQL_FILE)
    activities = session.query(Activity).all()
    print(f"{len(activities)} activities in {SQL_FILE}")

    updated = skipped = failed = 0
    for index, activity in enumerate(activities, 1):
        if options.only_legacy and not looks_legacy(activity.location_country):
            skipped += 1
            continue

        point = start_point(activity.summary_polyline)
        if point is None:
            print(f"  [{index}] {activity.run_id}: no polyline, skipped")
            skipped += 1
            continue

        try:
            location = reverse_geocode(point[0], point[1])
        except Exception as exc:
            print(f"  [{index}] {activity.run_id}: geocode failed ({exc})")
            failed += 1
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        if not location:
            print(f"  [{index}] {activity.run_id}: no address returned")
            failed += 1
        elif location == activity.location_country:
            skipped += 1
        else:
            print(f"  [{index}] {activity.run_id}: {location}")
            if not options.dry_run:
                activity.location_country = location
            updated += 1

        time.sleep(REQUEST_DELAY_SECONDS)

    if options.dry_run:
        print(
            f"\ndry run: {updated} would change, {skipped} unchanged, {failed} failed"
        )
        return 0

    session.commit()
    print(f"\nupdated {updated}, unchanged {skipped}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
