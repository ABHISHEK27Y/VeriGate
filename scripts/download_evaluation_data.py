"""Download source-labelled GLUE/PAWS text into gitignored data/ (no redistribution)."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import tarfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCES = {
    "qqp": "https://dl.fbaipublicfiles.com/glue/data/QQP-clean.zip",
    "stsb": "https://dl.fbaipublicfiles.com/glue/data/STS-B.zip",
    "paws": "https://storage.googleapis.com/paws/english/paws_wiki_labeled_final.tar.gz",
}
PAWS_MIRROR = "https://datasets-server.huggingface.co/rows"
PAWS_TRAIN_COUNT = 49401  # from the official PAWS-Wiki labeled-final README
FIELDS = {
    "qqp": ("id", "question1", "question2", "is_duplicate"),
    "stsb": ("index", "sentence1", "sentence2", "score"),
    "paws": ("id", "sentence1", "sentence2", "label"),
}


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - fixed sources
        return cast(bytes, response.read())


def _paws_rows() -> tuple[list[dict[str, str | int]], list[int]]:
    """Fetch a fixed random page sample of Google's labeled-final HF mirror."""
    offsets = random.Random(42).sample(range(0, PAWS_TRAIN_COUNT - 100, 100), 20)
    rows: list[dict[str, str | int]] = []
    for offset in offsets:
        params = urllib.parse.urlencode(
            {
                "dataset": "google-research-datasets/paws",
                "config": "labeled_final",
                "split": "train",
                "offset": offset,
                "length": 100,
            }
        )
        response = json.loads(_get(f"{PAWS_MIRROR}?{params}"))
        rows.extend(item["row"] for item in response["rows"])
    return rows, offsets


def _tables(name: str, archive: bytes) -> list[tuple[str, bytes]]:
    if name == "paws":
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
            return [
                (item.name, package.extractfile(item).read())  # type: ignore[union-attr]
                for item in package.getmembers()
                if item.isfile() and Path(item.name).name in {"train.tsv", "dev.tsv", "test.tsv"}
            ]
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        return [
            (item, package.read(item))
            for item in package.namelist()
            if Path(item).name in {"train.tsv", "dev.tsv"}
        ]


def download(name: str) -> dict[str, str | int | list[str]]:
    if name not in SOURCES:
        raise ValueError(f"Unknown source: {name}")
    if name == "paws":
        rows, offsets = _paws_rows()
        DATA.mkdir(exist_ok=True)
        target = DATA / "paws.tsv"
        with target.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(
                output, fieldnames=FIELDS[name], delimiter="\t", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows({field: row[field] for field in FIELDS[name]} for row in rows)
        paws_record: dict[str, str | int | list[str]] = {
            "source": name,
            "url": PAWS_MIRROR,
            "mirror_dataset": "google-research-datasets/paws/labeled_final/train",
            "offsets": [str(offset) for offset in offsets],
            "normalized_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "rows": len(rows),
            "tables": ["train sample"],
        }
        (DATA / "paws.provenance.json").write_text(
            json.dumps(paws_record, indent=2) + "\n", encoding="utf-8"
        )
        return paws_record
    archive = _get(SOURCES[name])
    tables = _tables(name, archive)
    if not tables:
        raise ValueError(f"{name}: archive contains no labelled train/dev tables")
    DATA.mkdir(exist_ok=True)
    target = DATA / f"{name}.tsv"
    fields = FIELDS[name]
    count = 0
    with target.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for table_name, payload in tables:
            reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")), delimiter="\t")
            if not set(fields).issubset(reader.fieldnames or []):
                raise ValueError(f"{name}:{table_name}: unexpected columns")
            for row in reader:
                writer.writerow({field: row[field] for field in fields})
                count += 1
    record: dict[str, str | int | list[str]] = {
        "source": name,
        "url": SOURCES[name],
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
        "normalized_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "rows": count,
        "tables": [entry for entry, _ in tables],
    }
    (DATA / f"{name}.provenance.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="*", choices=tuple(SOURCES), default=list(SOURCES))
    for name in parser.parse_args().sources:
        record = download(name)
        print(f"{name}: {record['rows']} source-labelled pairs in {DATA / (name + '.tsv')}")


if __name__ == "__main__":
    main()
