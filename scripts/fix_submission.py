"""修復 submission CSV：填回 N/A 字串、補齊遺漏的 ID、強制邏輯規則。"""

import sys
import pandas as pd

EXPECTED_COLS = ["id", "promise_status", "verification_timeline",
                 "evidence_status", "evidence_quality"]

VALID_PROMISE = {"Yes", "No"}
VALID_EVIDENCE = {"Yes", "No", "N/A"}
VALID_QUALITY = {"Clear", "Not Clear", "Misleading", "N/A"}
VALID_TIMELINE = {"already", "within_2_years", "between_2_and_5_years",
                  "more_than_5_years", "N/A"}


def fix(path):
    df = pd.read_csv(path, keep_default_na=False, na_values=[])

    print(f"讀取 {path}: {len(df)} 筆")

    # 補齊遺漏的 ID
    all_ids = set(range(12001, 14001))
    existing_ids = set(df["id"].tolist())
    missing_ids = sorted(all_ids - existing_ids)
    if missing_ids:
        print(f"補齊 {len(missing_ids)} 筆遺漏的 ID: {missing_ids[:10]}...")
        missing_rows = []
        for mid in missing_ids:
            missing_rows.append({
                "id": mid,
                "promise_status": "No",
                "verification_timeline": "N/A",
                "evidence_status": "N/A",
                "evidence_quality": "N/A",
            })
        df = pd.concat([df, pd.DataFrame(missing_rows)], ignore_index=True)

    # 修復每一行
    fixes = 0
    for idx, row in df.iterrows():
        changed = False

        # 修復空值或無效值
        ps = str(row["promise_status"]).strip()
        es = str(row["evidence_status"]).strip()
        eq = str(row["evidence_quality"]).strip()
        vt = str(row["verification_timeline"]).strip()

        if ps not in VALID_PROMISE:
            ps = "No"
            changed = True
        if es not in VALID_EVIDENCE:
            es = "N/A"
            changed = True
        if eq not in VALID_QUALITY:
            eq = "N/A"
            changed = True
        if vt not in VALID_TIMELINE:
            vt = "N/A"
            changed = True

        # 邏輯規則
        if ps == "No":
            if es != "N/A" or eq != "N/A" or vt != "N/A":
                es, eq, vt = "N/A", "N/A", "N/A"
                changed = True

        if ps == "Yes":
            if es == "N/A":
                es = "No"
                changed = True
            if vt == "N/A":
                vt = "between_2_and_5_years"
                changed = True

        if es in ("No", "N/A"):
            if eq != "N/A":
                eq = "N/A"
                changed = True

        if changed:
            fixes += 1
            df.at[idx, "promise_status"] = ps
            df.at[idx, "evidence_status"] = es
            df.at[idx, "evidence_quality"] = eq
            df.at[idx, "verification_timeline"] = vt

    df = df.sort_values("id").reset_index(drop=True)
    df = df[EXPECTED_COLS]
    df.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
    print(f"修復 {fixes} 筆，補齊 {len(missing_ids)} 筆，已存回 {path}（共 {len(df)} 筆）")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "submission.csv"
    fix(path)
