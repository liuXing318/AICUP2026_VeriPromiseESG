"""驗證提交 CSV 格式是否符合競賽要求。"""

import sys
import pandas as pd

VALID_PROMISE = {"Yes", "No"}
VALID_EVIDENCE = {"Yes", "No", "N/A"}
VALID_QUALITY = {"Clear", "Not Clear", "Misleading", "N/A"}
VALID_TIMELINE = {"already", "within_2_years", "between_2_and_5_years",
                  "more_than_5_years", "N/A"}
EXPECTED_COLS = ["id", "promise_status", "verification_timeline",
                 "evidence_status", "evidence_quality"]


def validate(path: str):
    df = pd.read_csv(path, keep_default_na=False, na_values=[])
    errors = []

    # Column check
    if list(df.columns) != EXPECTED_COLS:
        errors.append(f"欄位不符: 期望 {EXPECTED_COLS}, 得到 {list(df.columns)}")

    # Row count
    if len(df) != 2000:
        errors.append(f"行數不符: 期望 2000, 得到 {len(df)}")

    # ID range
    expected_ids = list(range(12001, 14001))
    actual_ids = df["id"].tolist()
    if actual_ids != expected_ids:
        errors.append(f"ID 不符: 期望 12001-14000, 實際起止 {actual_ids[0]}-{actual_ids[-1]}")

    # Null check
    null_counts = df.isnull().sum()
    if null_counts.sum() > 0:
        errors.append(f"存在空值: {null_counts[null_counts > 0].to_dict()}")

    # Value domain check
    for col, valid_set in [
        ("promise_status", VALID_PROMISE),
        ("evidence_status", VALID_EVIDENCE),
        ("evidence_quality", VALID_QUALITY),
        ("verification_timeline", VALID_TIMELINE),
    ]:
        bad = set(df[col].unique()) - valid_set
        if bad:
            errors.append(f"{col} 含非法值: {bad}")

    # Logic rules
    no_promise = df[df["promise_status"] == "No"]
    for col in ["evidence_status", "evidence_quality", "verification_timeline"]:
        bad = no_promise[no_promise[col] != "N/A"]
        if len(bad) > 0:
            errors.append(
                f"promise=No 但 {col}!=N/A: {len(bad)} 筆 "
                f"(ids: {bad['id'].head(5).tolist()})")

    evi_no = df[df["evidence_status"].isin(["No", "N/A"])]
    bad_q = evi_no[evi_no["evidence_quality"] != "N/A"]
    if len(bad_q) > 0:
        errors.append(
            f"evidence=No/N/A 但 quality!=N/A: {len(bad_q)} 筆 "
            f"(ids: {bad_q['id'].head(5).tolist()})")

    if errors:
        print("FAIL — 發現以下問題:")
        for e in errors:
            print(f"  - {e}")
        return False
    else:
        print("PASS — 格式完全合規")
        print(f"  行數: {len(df)}")
        print(f"  ID: {df['id'].iloc[0]} ~ {df['id'].iloc[-1]}")
        print(f"  分佈:")
        for col in EXPECTED_COLS[1:]:
            print(f"    {col}: {df[col].value_counts().to_dict()}")
        return True


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "submission.csv"
    validate(path)
