"""
jalankan: python scripts/test_pipeline.py
pastikan server sudah jalan dan dokumen sudah diupload.
"""
import asyncio
import httpx

BASE_URL = "http://localhost:8000"

TEST_CASES = [
    # ── S1: query normal, satu dokumen relevan ──────────────────────────────
    {
        "id": "S1",
        "desc": "Query normal - satu dokumen relevan (resep)",
        "query": "Apa saja bahan-bahan untuk membuat nasi goreng kampung?",
        "expect_conflict": False,
        "expect_not_found": False,
        "expect_keywords": ["nasi goreng"],
    },
    # ── S2: multi dokumen relevan, tidak ada konflik ─────────────────────────
    {
        "id": "S2",
        "desc": "Query normal - multi dokumen, tidak ada konflik",
        "query": "Siapa yang tidak hadir dalam rapat dan bagaimana mereka diwakili?",
        "expect_conflict": False,
        "expect_not_found": False,
        "expect_keywords": ["Ava", "Sophia"],
    },
    # ── S3: konflik nyata - tanggal berbeda untuk event yang sama ────────────
    {
        "id": "S3",
        "desc": "Konflik nyata - tanggal deployment Beta v3 berbeda antar dokumen",
        "query": "Kapan target tanggal deployment Beta v3 yang telah disepakati?",
        "expect_conflict": True,
        "expect_not_found": False,
        "expect_keywords": ["15 November", "3 Desember"],
        "expect_sources_not_contain": ["email_sprint_retrospective.txt"],
    },
    # ── S4: konflik nyata - PIC berbeda untuk tugas yang sama ────────────────
    {
        "id": "S4",
        "desc": "Konflik nyata - PIC deployment Beta v3 berbeda antar dokumen",
        "query": "Siapa PIC deployment Beta v3?",
        "expect_conflict": True,
        "expect_not_found": False,
        "expect_keywords": ["Ava", "Liam"],
        "expect_sources_not_contain": ["email_sprint_retrospective.txt"],
    },
    # ── S5: informasi tidak ada di dokumen manapun ───────────────────────────
    {
        "id": "S5",
        "desc": "Informasi tidak ditemukan di dokumen manapun",
        "query": "Apa kebijakan cuti tahunan dan tunjangan kesehatan karyawan?",
        "expect_conflict": False,
        "expect_not_found": True,
        "expect_keywords": [],
        "expect_empty_sources": True,
    },
    # ── S6: query di luar topik semua dokumen (off-topic) ────────────────────
    {
        "id": "S6",
        "desc": "Query off-topic - tidak berhubungan dengan dokumen apapun",
        "query": "Berapa nilai tukar dolar Amerika hari ini?",
        "expect_conflict": False,
        "expect_not_found": True,
        "expect_keywords": [],
        "expect_empty_sources": True,
    },
    # ── S7: dokumen pengetahuan umum ──────────────────────────────────────────
    {
        "id": "S7",
        "desc": "Query dari dokumen pengetahuan - bukan rapat",
        "query": "Bagaimana cara menyeduh kopi dengan metode pour over?",
        "expect_conflict": False,
        "expect_not_found": False,
        "expect_keywords": ["kopi"],
    },
    # ── S8: sintesis action items dari satu rapat ────────────────────────────
    {
        "id": "S8",
        "desc": "Query sintesis - action items dari rapat product launch",
        "query": "Apa saja action items dari rapat perencanaan peluncuran produk?",
        "expect_conflict": False,
        "expect_not_found": False,
        "expect_keywords": [],
    },
    # ── S9: query dari dokumen chat/WA ───────────────────────────────────────
    {
        "id": "S9",
        "desc": "Query dari dokumen chat WhatsApp",
        "query": "Apa yang dibahas tim engineering di WhatsApp terkait incident?",
        "expect_conflict": False,
        "expect_not_found": False,
        "expect_keywords": [],
    },
    # ── S10: tokoh yang sama muncul di banyak dokumen ────────────────────────
    {
        "id": "S10",
        "desc": "Query ambigu - tokoh yang sama di banyak dokumen",
        "query": "Apa peran dan tanggung jawab Emma dalam tim?",
        "expect_conflict": False,
        "expect_not_found": False,
        "expect_keywords": ["Emma"],
    },
]

GREEN = "\033[92m"
RED   = "\033[91m"
CYAN  = "\033[96m"
RESET = "\033[0m"
BOLD  = "\033[1m"


def check(condition: bool, label: str) -> bool:
    mark = f"{GREEN}✓{RESET}" if condition else f"{RED}✗{RESET}"
    print(f"  {mark} {label}")
    return condition


async def run_tests():
    passed = 0
    failed = 0

    async with httpx.AsyncClient(timeout=60) as client:
        for tc in TEST_CASES:
            print(f"\n{BOLD}{CYAN}[{tc['id']}] {tc['desc']}{RESET}")
            print(f"  Query : \"{tc['query']}\"")
            print("  " + "-" * 66)

            try:
                resp = await client.post(f"{BASE_URL}/api/query", json={"query": tc["query"]})
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  {RED}ERROR: {e}{RESET}")
                failed += 1
                continue

            answer        = data.get("answer", "")
            trust_label   = data.get("trust", {}).get("label", "?")
            has_conflict  = data.get("has_conflict", False)
            sources       = data.get("sources", [])
            source_ids    = list({s["doc_id"] for s in sources})
            conflict_parties = list({s["doc_id"] for s in sources if s.get("is_conflict_party")})

            print(f"  Jawaban : {answer[:180]}{'...' if len(answer) > 180 else ''}")
            print(f"  Trust   : {trust_label} | Konflik: {has_conflict} | Sumber: {source_ids}")
            if has_conflict:
                print(f"  Conflict parties: {conflict_parties}")

            ok = True
            ok &= check(
                has_conflict == tc["expect_conflict"],
                f"conflict={'True' if tc['expect_conflict'] else 'False'} - dapat {has_conflict}"
            )
            ok &= check(
                (trust_label == "not_found") == tc["expect_not_found"],
                f"not_found={'True' if tc['expect_not_found'] else 'False'} - trust={trust_label}"
            )
            if has_conflict:
                ok &= check(
                    len(conflict_parties) >= 2,
                    f"minimal 2 conflict parties - dapat {conflict_parties}"
                )
            if tc.get("expect_empty_sources"):
                ok &= check(len(source_ids) == 0, f"sources kosong saat not_found - dapat {source_ids}")
            for doc in tc.get("expect_sources_not_contain", []):
                ok &= check(doc not in source_ids, f"'{doc}' tidak muncul sebagai sumber")
            for kw in tc.get("expect_keywords", []):
                found = kw.lower() in answer.lower()
                ok &= check(found, f"keyword '{kw}'")

            if ok:
                passed += 1
            else:
                failed += 1

    total = len(TEST_CASES)
    print(f"\n{BOLD}{'=' * 70}{RESET}")
    print(f"{BOLD}HASIL: {GREEN}{passed} passed{RESET}  {RED}{failed} failed{RESET}  / {total} total{RESET}")
    print(f"{BOLD}{'=' * 70}{RESET}\n")


if __name__ == "__main__":
    asyncio.run(run_tests())
