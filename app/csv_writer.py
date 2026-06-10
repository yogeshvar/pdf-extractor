"""Render packages into the "New Package(s) Template" CSV format."""

import csv
import io

from .schema import CSV_COLUMNS, Package


def packages_to_csv(packages: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_COLUMNS)
    for raw in packages:
        pkg = Package.model_validate(raw)
        writer.writerow(pkg.to_csv_row())
    return buf.getvalue()
