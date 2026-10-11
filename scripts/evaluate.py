"""
ESG 永續承諾驗證 — 驗證集評估腳本
計算加權準確率和各標籤的 confusion matrix。
"""

import argparse
import sys
import pandas as pd
from collections import Counter


WEIGHTS = {
    "promise_status": 0.20,
    "evidence_status": 0.30,
    "evidence_quality": 0.35,
    "verification_timeline": 0.15,
}

LABEL_COLUMNS = ["promise_status", "verification_timeline",
                 "evidence_status", "evidence_quality"]


def normalize_label(val):
    """統一 NaN 和各種 N/A 寫法。"""
    if pd.isna(val):
        return "N/A"
    s = str(val).strip()
    if s.lower() in ("nan", "n/a", "na", ""):
        return "N/A"
    return s


def evaluate(pred_df: pd.DataFrame, gold_df: pd.DataFrame):
    merged = pred_df.merge(gold_df, on="id", suffixes=("_pred", "_gold"))
    n = len(merged)
    print(f"評估樣本數: {n}\n")

    total_weighted = 0.0
    for col in LABEL_COLUMNS:
        pred_col = f"{col}_pred"
        gold_col = f"{col}_gold"

        merged[pred_col] = merged[pred_col].apply(normalize_label)
        merged[gold_col] = merged[gold_col].apply(normalize_label)

        correct = (merged[pred_col] == merged[gold_col]).sum()
        acc = correct / n
        weighted = acc * WEIGHTS[col]
        total_weighted += weighted

        print(f"--- {col} (權重 {WEIGHTS[col]:.0%}) ---")
        print(f"  準確率: {correct}/{n} = {acc:.4f}")
        print(f"  加權分數: {weighted:.4f}")

        # Confusion matrix
        gold_labels = sorted(merged[gold_col].unique())
        pred_labels = sorted(merged[pred_col].unique())
        all_labels = sorted(set(gold_labels) | set(pred_labels))

        print(f"  {'':>15s}", end="")
        for pl in all_labels:
            print(f"  pred={pl:>12s}", end="")
        print()

        for gl in all_labels:
            print(f"  gold={gl:>12s}", end="")
            for pl in all_labels:
                cnt = ((merged[gold_col] == gl) & (merged[pred_col] == pl)).sum()
                print(f"  {cnt:>17d}", end="")
            print()
        print()

    print(f"=== 總加權準確率: {total_weighted:.4f} ===")
    return total_weighted


def main():
    parser = argparse.ArgumentParser(description="ESG 驗證集評估")
    parser.add_argument("--pred", required=True, help="預測結果 CSV")
    parser.add_argument("--gold", required=True, help="正確答案 CSV（含標籤）")
    args = parser.parse_args()

    pred_df = pd.read_csv(args.pred)
    gold_df = pd.read_csv(args.gold)

    gold_cols = ["id"] + LABEL_COLUMNS
    available = [c for c in gold_cols if c in gold_df.columns]
    gold_df = gold_df[available]

    evaluate(pred_df, gold_df)


if __name__ == "__main__":
    main()
