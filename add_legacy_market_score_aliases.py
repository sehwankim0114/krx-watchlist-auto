#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
기존 시장점수(score/reason)를 v6 전환용 별도 칼럼으로 안전하게 복제한다.

목적
- 기존 score/reason은 현재 자동화의 후보 정렬과 추천 선정에 계속 사용한다.
- 동시에 legacy_market_score/legacy_market_reason을 추가해,
  기업실적·밸류에이션이 포함될 미래 v6 최종점수와 명확히 구분한다.
- 원본 score/reason을 삭제하거나 이름을 바꾸지 않으므로 기존 자동화와 호환된다.

처리 대상
- latest 폴더의 모든 CSV 중 score 또는 reason 칼럼이 있는 파일
- score가 있으면 legacy_market_score를 생성·동기화
- reason이 있으면 legacy_market_reason을 생성·동기화

출력
- 해당 CSV를 UTF-8 BOM 형식으로 안전하게 갱신
- latest/legacy_market_score_alias_run_log_latest.txt
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Tuple

import pandas as pd


SCRIPT_VERSION = "add_legacy_market_score_aliases.py v1.0.0"
SCORE_SOURCE = "score"
SCORE_ALIAS = "legacy_market_score"
REASON_SOURCE = "reason"
REASON_ALIAS = "legacy_market_reason"
DEFAULT_LATEST_DIR = "latest"
LOG_FILENAME = "legacy_market_score_alias_run_log_latest.txt"
KST = timezone(timedelta(hours=9))


def read_csv_safely(path: Path) -> pd.DataFrame:
    """UTF-8 BOM/UTF-8/CP949 순서로 CSV를 읽는다."""
    errors: List[str] = []
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}: {exc}")
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
        except Exception as exc:
            errors.append(f"{encoding}: {type(exc).__name__}: {exc}")

    raise RuntimeError(
        f"CSV_READ_FAILED path={path} attempts={' | '.join(errors)}"
    )


def insert_or_sync_alias(
    df: pd.DataFrame,
    source: str,
    alias: str,
) -> Tuple[pd.DataFrame, bool]:
    """
    source 칼럼 값을 alias에 복제한다.
    alias가 이미 있더라도 매 실행마다 source와 동일하게 동기화한다.
    """
    if source not in df.columns:
        return df, False

    source_position = int(df.columns.get_loc(source))

    if alias in df.columns:
        df[alias] = df[source]
    else:
        df.insert(source_position + 1, alias, df[source])

    return df, True


def write_csv_atomically(df: pd.DataFrame, path: Path) -> None:
    """같은 폴더에 임시 파일을 쓴 뒤 원본과 교체한다."""
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(fd)
    temp_path = Path(temp_name)

    try:
        df.to_csv(temp_path, index=False, encoding="utf-8-sig")
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def update_one_csv(path: Path) -> Tuple[str, int]:
    """
    반환값:
    - 상태: UPDATED / SKIPPED_EMPTY / SKIPPED_NO_SCORE_FIELDS
    - 행 수
    """
    df = read_csv_safely(path)

    if df.empty and len(df.columns) == 0:
        return "SKIPPED_EMPTY", 0

    original_columns = list(df.columns)

    df, score_changed = insert_or_sync_alias(
        df,
        SCORE_SOURCE,
        SCORE_ALIAS,
    )
    df, reason_changed = insert_or_sync_alias(
        df,
        REASON_SOURCE,
        REASON_ALIAS,
    )

    if not score_changed and not reason_changed:
        return "SKIPPED_NO_SCORE_FIELDS", len(df)

    # 원본 score/reason이 그대로 남았는지 확인한다.
    if SCORE_SOURCE in original_columns and SCORE_SOURCE not in df.columns:
        raise RuntimeError(f"ORIGINAL_SCORE_LOST path={path}")
    if REASON_SOURCE in original_columns and REASON_SOURCE not in df.columns:
        raise RuntimeError(f"ORIGINAL_REASON_LOST path={path}")

    # 복제값 검증
    if SCORE_SOURCE in df.columns:
        left = df[SCORE_SOURCE].astype("string").fillna("<NA>")
        right = df[SCORE_ALIAS].astype("string").fillna("<NA>")
        if not left.equals(right):
            raise RuntimeError(f"SCORE_ALIAS_MISMATCH path={path}")

    if REASON_SOURCE in df.columns:
        left = df[REASON_SOURCE].astype("string").fillna("<NA>")
        right = df[REASON_ALIAS].astype("string").fillna("<NA>")
        if not left.equals(right):
            raise RuntimeError(f"REASON_ALIAS_MISMATCH path={path}")

    write_csv_atomically(df, path)
    return "UPDATED", len(df)


def write_log(
    log_path: Path,
    started_at: datetime,
    finished_at: datetime,
    latest_dir: Path,
    scanned: int,
    updated: List[str],
    skipped: List[str],
    failures: List[str],
) -> None:
    lines = [
        f"SCRIPT_VERSION={SCRIPT_VERSION}",
        f"STARTED_AT_KST={started_at.astimezone(KST).isoformat()}",
        f"FINISHED_AT_KST={finished_at.astimezone(KST).isoformat()}",
        f"LATEST_DIR={latest_dir.as_posix()}",
        f"SCANNED_CSV_COUNT={scanned}",
        f"UPDATED_FILE_COUNT={len(updated)}",
        f"SKIPPED_FILE_COUNT={len(skipped)}",
        f"FAILED_FILE_COUNT={len(failures)}",
        f"STATUS={'OK' if not failures else 'FAILED'}",
        "",
        "[UPDATED]",
        *(updated or ["NONE"]),
        "",
        "[SKIPPED]",
        *(skipped or ["NONE"]),
        "",
        "[FAILED]",
        *(failures or ["NONE"]),
        "",
        "NOTE=기존 score/reason은 호환성을 위해 유지되며 "
        "legacy_market_score/legacy_market_reason으로 복제되었습니다.",
        "NOTE=v6 기업실적·밸류에이션 최종점수는 아직 생성하지 않습니다.",
    ]

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="기존 score/reason을 legacy_market_* 칼럼으로 안전하게 복제"
    )
    parser.add_argument(
        "--root",
        default=".",
        help="저장소 루트 경로. 기본값: 현재 폴더",
    )
    parser.add_argument(
        "--latest-dir",
        default=DEFAULT_LATEST_DIR,
        help=f"latest 폴더 상대경로. 기본값: {DEFAULT_LATEST_DIR}",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="score/reason이 있는 파일이 하나도 없으면 오류 종료",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started_at = datetime.now(tz=KST)

    root = Path(args.root).resolve()
    latest_dir = (root / args.latest_dir).resolve()
    log_path = latest_dir / LOG_FILENAME

    updated: List[str] = []
    skipped: List[str] = []
    failures: List[str] = []

    if not latest_dir.exists():
        failures.append(f"LATEST_DIR_NOT_FOUND: {latest_dir}")
        write_log(
            log_path=log_path,
            started_at=started_at,
            finished_at=datetime.now(tz=KST),
            latest_dir=latest_dir,
            scanned=0,
            updated=updated,
            skipped=skipped,
            failures=failures,
        )
        print(f"[FAILED] latest 폴더가 없습니다: {latest_dir}", file=sys.stderr)
        return 1

    csv_paths = sorted(
        path for path in latest_dir.glob("*.csv")
        if path.is_file()
    )

    for path in csv_paths:
        relative = path.relative_to(root).as_posix()
        try:
            status, row_count = update_one_csv(path)
            message = f"{relative} rows={row_count} status={status}"

            if status == "UPDATED":
                updated.append(message)
                print(f"[UPDATED] {message}")
            else:
                skipped.append(message)
        except Exception as exc:
            message = (
                f"{relative} error={type(exc).__name__}: {exc}"
            )
            failures.append(message)
            print(f"[FAILED] {message}", file=sys.stderr)

    if args.strict and not updated and not failures:
        failures.append(
            "STRICT_MODE_NO_TARGETS: score/reason 칼럼이 있는 CSV가 없습니다."
        )

    finished_at = datetime.now(tz=KST)
    write_log(
        log_path=log_path,
        started_at=started_at,
        finished_at=finished_at,
        latest_dir=latest_dir,
        scanned=len(csv_paths),
        updated=updated,
        skipped=skipped,
        failures=failures,
    )

    print(
        "[SUMMARY] "
        f"scanned={len(csv_paths)} "
        f"updated={len(updated)} "
        f"skipped={len(skipped)} "
        f"failed={len(failures)}"
    )
    print(f"[LOG] {log_path}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
