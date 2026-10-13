#!/usr/bin/env python3
"""
Read-Only Wage Obligations & Settlement Reconciliation Tool.
Phase 3.F.3 — Worker Wage Obligations & Settlement.

This script performs non-mutating validation and audit checks on wage data:
1. Wage Obligations ledger integrity (accrued vs paid vs remaining).
2. Wage Settlements vs Wage Obligations allocation consistency.
3. Wage Settlements vs Finance Transactions linkage.
4. Historical unlinked employee wages audit.
5. Detection of anomalies requiring manual review vs auto-reconciled items.

SAFETY MANDATE:
- READ-ONLY. Zero insert, update, delete, or schema mutations.
- Does NOT execute auto-matching on ambiguous historical records.
"""

import sys
import os
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def _d(val) -> Decimal:
    if val is None:
        return Decimal("0.00")
    try:
        return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


async def run_reconciliation(db):
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "obligations": {
            "total_count": 0,
            "status_breakdown": {},
            "total_accrued_le": Decimal("0.00"),
            "total_paid_le": Decimal("0.00"),
            "total_remaining_le": Decimal("0.00"),
        },
        "settlements": {
            "total_count": 0,
            "status_breakdown": {},
            "total_amount_le": Decimal("0.00"),
        },
        "matched_data": [],
        "explainable_anomalies": [],
        "investigation_needed": [],
        "historical_unlinked": [],
    }

    # 1. Audit wage_obligations
    cursor_ob = db.wage_obligations.find({})
    obligations_list = await cursor_ob.to_list(10000) if hasattr(cursor_ob, "to_list") else []
    ob_map = {}

    for ob in obligations_list:
        report["obligations"]["total_count"] += 1
        status = ob.get("status", "unknown")
        report["obligations"]["status_breakdown"][status] = report["obligations"]["status_breakdown"].get(status, 0) + 1

        tot = _d(ob.get("total_amount_le"))
        paid = _d(ob.get("paid_amount_le"))
        rem = tot - paid

        report["obligations"]["total_accrued_le"] += tot
        report["obligations"]["total_paid_le"] += paid
        report["obligations"]["total_remaining_le"] += rem

        ob_id_str = str(ob.get("_id") or ob.get("id"))
        ob_map[ob_id_str] = ob

        # Sanity Check 1: Paid status with remaining balance > 0
        if status == "paid" and rem > Decimal("0.00"):
            report["investigation_needed"].append({
                "type": "PAID_WITH_REMAINING_BALANCE",
                "obligation_number": ob.get("obligation_number"),
                "worker_name": ob.get("worker_name"),
                "total_le": float(tot),
                "paid_le": float(paid),
                "remaining_le": float(rem),
                "detail": "Kewajiban berstatus 'paid' namun sisa saldo masih lebih besar dari 0"
            })

        # Sanity Check 2: Accrued status but fully paid
        if status == "accrued" and paid >= tot and tot > Decimal("0.00"):
            report["investigation_needed"].append({
                "type": "ACCRUED_BUT_FULLY_PAID",
                "obligation_number": ob.get("obligation_number"),
                "worker_name": ob.get("worker_name"),
                "total_le": float(tot),
                "paid_le": float(paid),
                "detail": "Kewajiban berstatus 'accrued' padahal nilai pembayaran telah memenuhi total akru"
            })

        # Sanity Check 3: Paid amount exceeds total amount
        if paid > tot:
            report["investigation_needed"].append({
                "type": "OVERPAID_OBLIGATION",
                "obligation_number": ob.get("obligation_number"),
                "worker_name": ob.get("worker_name"),
                "total_le": float(tot),
                "paid_le": float(paid),
                "detail": "Nilai pembayaran tercatat melebihi total kewajiban awal"
            })

    # 2. Audit wage_settlements
    cursor_st = db.wage_settlements.find({})
    settlements_list = await cursor_st.to_list(10000) if hasattr(cursor_st, "to_list") else []
    st_by_ob = {}

    for st in settlements_list:
        report["settlements"]["total_count"] += 1
        st_status = st.get("status", "recorded")
        report["settlements"]["status_breakdown"][st_status] = report["settlements"]["status_breakdown"].get(st_status, 0) + 1

        amt = _d(st.get("amount_le"))
        if st_status != "voided":
            report["settlements"]["total_amount_le"] += amt

        st_id = str(st.get("_id") or st.get("id"))
        allocations = st.get("allocations") or []
        alloc_sum = Decimal("0.00")

        for a in allocations:
            a_ob_id = str(a.get("wage_obligation_id"))
            a_amt = _d(a.get("amount_le"))
            alloc_sum += a_amt

            if st_status != "voided":
                st_by_ob[a_ob_id] = st_by_ob.get(a_ob_id, Decimal("0.00")) + a_amt

            # Linkage Check: Does referenced obligation exist?
            if a_ob_id not in ob_map:
                report["investigation_needed"].append({
                    "type": "ORPHAN_SETTLEMENT_ALLOCATION",
                    "settlement_number": st.get("settlement_number"),
                    "referenced_obligation_id": a_ob_id,
                    "detail": "Alokasi settlement merujuk ke ID kewajiban yang tidak ditemukan di db.wage_obligations"
                })

        # Allocation total vs settlement amount check
        if alloc_sum != amt:
            report["investigation_needed"].append({
                "type": "ALLOCATION_SUM_MISMATCH",
                "settlement_number": st.get("settlement_number"),
                "settlement_amount_le": float(amt),
                "allocation_sum_le": float(alloc_sum),
                "detail": "Jumlah alokasi per item tidak sama dengan nominal total settlement"
            })

        # Finance Transaction Linkage Check
        ft_id = st.get("finance_transaction_id")
        if not ft_id and st_status != "voided":
            report["investigation_needed"].append({
                "type": "MISSING_FINANCE_LINKAGE",
                "settlement_number": st.get("settlement_number"),
                "detail": "Settlement tercatat tanpa tautan finance_transaction_id"
            })
        elif ft_id:
            ft = await db.finance_transactions.find_one({"_id": ft_id}) if hasattr(db.finance_transactions, "find_one") else None
            if not ft:
                report["investigation_needed"].append({
                    "type": "BROKEN_FINANCE_LINKAGE",
                    "settlement_number": st.get("settlement_number"),
                    "finance_transaction_id": ft_id,
                    "detail": "finance_transaction_id yang dirujuk tidak ditemukan di db.finance_transactions"
                })

    # 3. Cross-Check Obligation Paid Amounts vs Active Settlement Allocations
    for ob_id, ob in ob_map.items():
        recorded_paid = _d(ob.get("paid_amount_le"))
        settled_alloc = st_by_ob.get(ob_id, Decimal("0.00"))

        if recorded_paid == settled_alloc and recorded_paid > Decimal("0.00"):
            report["matched_data"].append({
                "obligation_number": ob.get("obligation_number"),
                "worker_name": ob.get("worker_name"),
                "settled_amount_le": float(recorded_paid)
            })
        elif recorded_paid != settled_alloc:
            report["investigation_needed"].append({
                "type": "OBLIGATION_ALLOCATION_DISCREPANCY",
                "obligation_number": ob.get("obligation_number"),
                "recorded_paid_le": float(recorded_paid),
                "computed_settlements_le": float(settled_alloc),
                "detail": "Nominal paid_amount_le pada kewajiban tidak cocok dengan total alokasi settlement aktif"
            })

    # 4. Audit Historical Unlinked Employee Wages (Modul Finance Lama)
    cursor_ft = db.finance_transactions.find({
        "type": "expense",
        "category": {"$regex": "upah|wage|pekerja", "$options": "i"},
        "wage_settlement_id": None
    })
    unlinked_txns = await cursor_ft.to_list(1000) if hasattr(cursor_ft, "to_list") else []

    for ft in unlinked_txns:
        report["historical_unlinked"].append({
            "transaction_id": str(ft.get("_id") or ft.get("id")),
            "date": ft.get("date"),
            "recipient_name": ft.get("recipient_employee_name") or ft.get("description"),
            "amount_le": float(_d(ft.get("amount"))),
            "currency": ft.get("currency"),
            "detail": "Pengeluaran upah manual historis sebelum Phase 3.F.3 (tidak memiliki tautan kewajiban SPK)"
        })

    return report


def print_markdown_report(report):
    print("# Laporan Rekonsiliasi Buku Besar Upah & Settlement (Phase 3.F.3)")
    print(f"**Waktu Rekonsiliasi**: `{report['timestamp']}`\n")

    print("## 1. Ringkasan Kewajiban Upah (`db.wage_obligations`)")
    print(f"- **Total Kewajiban Tercatat**: {report['obligations']['total_count']}")
    print(f"- **Status Breakdown**: {report['obligations']['status_breakdown']}")
    print(f"- **Total Akrual**: `{float(report['obligations']['total_accrued_le']):.2f} LE`")
    print(f"- **Total Terbayar**: `{float(report['obligations']['total_paid_le']):.2f} LE`")
    print(f"- **Total Sisa Terutang**: `{float(report['obligations']['total_remaining_le']):.2f} LE`\n")

    print("## 2. Ringkasan Pembayaran Upah (`db.wage_settlements`)")
    print(f"- **Total Settlement Tercatat**: {report['settlements']['total_count']}")
    print(f"- **Status Breakdown**: {report['settlements']['status_breakdown']}")
    print(f"- **Total Nominal Kas Keluar**: `{float(report['settlements']['total_amount_le']):.2f} LE`\n")

    print(f"## 3. Data Rekonsiliasi Cocok ({len(report['matched_data'])} items)")
    if report["matched_data"]:
        print("| No. Kewajiban | Pekerja | Nominal Selesai |")
        print("| :--- | :--- | :--- |")
        for m in report["matched_data"][:10]:
            print(f"| {m['obligation_number']} | {m['worker_name']} | {m['settled_amount_le']:.2f} LE |")
        if len(report["matched_data"]) > 10:
            print(f"| ... dan {len(report['matched_data']) - 10} kewajiban lainnya cocok sempurna | | |")
    else:
        print("_Belum ada kewajiban yang dilunasi atau data masih kosong._")
    print()

    print(f"## 4. Anomali Membutuhkan Investigasi ({len(report['investigation_needed'])} kasus)")
    if report["investigation_needed"]:
        for inv in report["investigation_needed"]:
            print(f"- **[{inv['type']}]**: {inv['detail']}")
    else:
        print("✅ **Nol Anomali Terdeteksi.** Seluruh kewajiban dan alokasi settlement konsisten.")
    print()

    print(f"## 5. Transaksi Upah Historis Tanpa Tautan ({len(report['historical_unlinked'])} transaksi)")
    if report["historical_unlinked"]:
        print(f"Ditemukan {len(report['historical_unlinked'])} transaksi pengeluaran kategori Pekerja dari modul Finance lama yang tercatat sebelum implementasi settlement SPK.")
        print("> **Kebijakan Rekonsiliasi**: Transaksi historis ini **TIDAK di-auto match** secara otomatis untuk mencegah kesalahan pemetaan masa lalu. Rekomendasi: biarkan sebagai arsip jurnal historis atau lakukan review manual bila ada klaim pekerja.")
    else:
        print("_Tidak ada transaksi upah historis tanpa tautan._")


if __name__ == "__main__":
    print("Skrip ini dirancang untuk dijalankan dengan database terisolasi/staging.")
    print("Contoh eksekusi: python reconcile_wage_obligations_and_settlements.py")
