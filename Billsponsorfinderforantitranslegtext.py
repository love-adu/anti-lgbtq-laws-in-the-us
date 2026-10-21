# this finds out who introduced and sponsored each bill
# run this AFTER billtextfinderforantitranslegtext.py
#
#
#   python billsponsorfinderforantitranslegtext.py
#   python billsponsorfinderforantitranslegtext.py --out billtextdeclassed

import argparse, json, os, re
import pandas as pd

OUT_DIR = "billtextdeclassed"
RESULTS_CSV = "resultsfromanalysisforantitranslegdata.csv"
SPONSORS_CSV = "sponsorsfromanalysisforantitranslegdata.csv"
BILLS_CSV = "introducersbybillforantitranslegdata.csv"
INTRO, COSP = "introducer", "cosponsor"

TITLES = r"(?:senators?|representatives?|reps?\.?|sens?\.?|delegates?|assembly\s?(?:members?|man|woman)|councilmembers?|hon\.?|mr\.?|mrs\.?|ms\.?|dr\.?)"
# if the "name" has one of these in it we grabbed the wrong thing
JUNK = {"committee", "bill", "act", "referred", "relating", "session", "house", "senate", "legislature",
        "general", "assembly", "state", "read", "first", "second", "time", "law", "code", "title", "chapter"}

INTRO_PATS = [
    re.compile(r"\b(?:introduced|presented|offered|filed|sponsored)\s+by\s*:?\s+(?P<who>[^\n]{3,220})", re.I),
    re.compile(r"^\s*by\s*:?\s+(?=" + TITLES + r"\b)(?P<who>[^\n]{3,220})", re.I | re.M),
]
COSP_PAT = re.compile(r"\bco-?sponsor(?:s|ed\s+by)?\s*:?\s+(?P<who>[^\n]{3,300})", re.I)


def clean_names(chunk):
    # stop where the sentence moves on ("referred to committee" etc)
    chunk = re.split(r"\s*(?:;|\(|\s-\s|,?\s+(?:and\s+)?(?:referred|read|to the|to committee|a bill|an act|for an act|relating)\b)", chunk, 1, flags=re.I)[0]
    names = []
    for p in re.split(r"\s*(?:,|&|\band\b)\s*", chunk):
        p = re.sub(r"^(?:" + TITLES + r"\s+)+", "", p.strip(), flags=re.I)
        p = re.sub(r"\s*[\(\[]?\b[DRI]-\w+.*$", "", p)  # party tags like D-12
        toks = p.strip(" .:").split()
        if not 1 <= len(toks) <= 4:
            continue
        if any(t.lower().strip(".,") in JUNK for t in toks):
            continue
        if not all(re.fullmatch(r"[A-Za-z][A-Za-z.'’\-]*", t) for t in toks):
            continue
        names.append(" ".join(t.capitalize() if t.isupper() and len(t) > 2 else t for t in toks))
    return names


def parse_text(txt):
    head = txt[:5000]
    intro, cos = [], []
    for pat in INTRO_PATS:
        for m in pat.finditer(head):
            for n in clean_names(m.group("who")):
                if n not in intro:
                    intro.append(n)
        if intro:
            break
    for m in COSP_PAT.finditer(head):
        for n in clean_names(m.group("who")):
            if n not in cos and n not in intro:
                cos.append(n)
    return intro, cos


def record_sponsors(bill):
    sp = bill.get("sponsors") or []
    if not sp:
        return []
    for i, s in enumerate(sp):
        s["_i"] = i
    # type 1 = primary, 3 = joint. some states give everyone type 0 though
    has_primary = any(s.get("sponsor_type_id") in (1, 3) for s in sp)
    guess_id = None
    if not has_primary:
        # no flag so best guess is whoever has the lowest sponsor_order
        people = [s for s in sp if not s.get("committee_sponsor")] or sp
        guess_id = min(people, key=lambda s: (s.get("sponsor_order") or 0, s["_i"]))["_i"]
    rows = []
    for s in sp:
        if has_primary:
            role, guess = (INTRO if s.get("sponsor_type_id") in (1, 3) else COSP), False
        else:
            role, guess = (INTRO, True) if s["_i"] == guess_id else (COSP, False)
        rows.append({"role": role, "name": s.get("name", ""), "party": s.get("party", ""),
                     "chamber_role": s.get("role", ""), "district": s.get("district", ""),
                     "people_id": s.get("people_id", ""), "sponsor_type_id": s.get("sponsor_type_id", ""),
                     "sponsor_order": s.get("sponsor_order", ""), "committee_sponsor": s.get("committee_sponsor", ""),
                     "source": "record", "introducer_is_guess": guess})
    return rows


def last_name(full):
    toks = [t for t in re.split(r"[\s,]+", full.replace(".", " ")) if t]
    toks = [t for t in toks if t.lower() not in ("jr", "sr", "ii", "iii", "iv")]
    return toks[-1].lower() if toks else ""


def text_row(role, name):
    # a sponsor row built from the bill text, so no party/district/id
    return {"role": role, "name": name, "party": "", "chamber_role": "", "district": "", "people_id": "",
            "sponsor_type_id": "", "sponsor_order": "", "committee_sponsor": "", "source": "text",
            "introducer_is_guess": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_DIR)
    a = ap.parse_args()

    res = pd.read_csv(os.path.join(a.out, RESULTS_CSV), dtype=str).fillna("")
    res = res[res["legiscan_bill_id"] != ""]
    # one row per bill, and prefer the introduced text row
    res["_pref"] = (res["version"] != "introduced").astype(int)
    bills = res.sort_values("_pref").drop_duplicates("legiscan_bill_id")
    print(len(bills), "bills to look at")

    sp_rows, bill_rows, missing = [], [], 0
    for b in bills.to_dict("records"):
        bid = b["legiscan_bill_id"]
        rec_path = os.path.join(a.out, "cache", "api", f"bill_{bid}.json")
        rec = []
        if os.path.exists(rec_path):
            rec = record_sponsors(json.load(open(rec_path)).get("bill") or {})
        else:
            missing += 1

        txt_intro, txt_cos = [], []
        tp = b.get("text_path", "")
        if tp and os.path.exists(tp):
            txt_intro, txt_cos = parse_text(open(tp, encoding="utf-8", errors="ignore").read())

        base = {"legiscan_bill_id": bid, "state": b["state"], "bill_key": b["bill_key"], "year": b["year"]}
        rows = rec[:]
        rec_intro = [r for r in rec if r["role"] == INTRO]
        if not rec_intro:
            # the record had nobody, so use whatever the text says
            rows += [text_row(INTRO, n) for n in txt_intro] + [text_row(COSP, n) for n in txt_cos]
        for r in rows:
            sp_rows.append(dict(base, **r))

        intro = [r for r in rows if r["role"] == INTRO]
        parties = [r["party"] for r in rows if r["party"]]
        agree = ""
        if rec_intro and txt_intro:
            rec_last = {last_name(r["name"]) for r in rec_intro}
            agree = any(last_name(n) in rec_last for n in txt_intro)
        guess = bool(intro) and all(r["introducer_is_guess"] for r in intro)
        party_counts = " ".join(f"{p}:{n}" for p, n in pd.Series(parties).value_counts().items()) if parties else ""
        bill_rows.append(dict(
            base, issue_category=b.get("issue_category", ""), status=b.get("status", ""),
            n_sponsors=len(rows), n_introducers=len(intro), n_cosponsors=len([r for r in rows if r["role"] == COSP]),
            introducer=" | ".join(r["name"] for r in intro),
            introducer_party=" | ".join(r["party"] for r in intro),
            introducer_district=" | ".join(str(r["district"]) for r in intro),
            introducer_source=intro[0]["source"] if intro else "",
            introducer_is_guess=guess, parties_all=party_counts,
            bipartisan=("D" in parties and "R" in parties) if parties else "",
            introducer_from_text=" | ".join(txt_intro), text_agrees_with_record=agree,
            needs_check=(not intro) or guess or (agree is False)))

    sp = pd.DataFrame(sp_rows)
    bl = pd.DataFrame(bill_rows)
    sp.to_csv(os.path.join(a.out, SPONSORS_CSV), index=False)
    bl.to_csv(os.path.join(a.out, BILLS_CSV), index=False)
    print("saved", SPONSORS_CSV, "and", BILLS_CSV)
    if missing:
        print(missing, "bills had no saved legiscan record, run script on them first")

    # which states are shaky? look at those first
    if len(bl):
        g = bl.groupby("state").agg(
            bills=("legiscan_bill_id", "size"),
            no_introducer=("n_introducers", lambda s: int((s == 0).sum())),
            guessed=("introducer_is_guess", "sum"),
            disagree=("text_agrees_with_record", lambda s: int((s == False).sum())),  # noqa: E712
            needs_check=("needs_check", "sum"))
        g["pct_needs_check"] = (100 * g["needs_check"] / g["bills"]).round(0)
        print("\nstates to look at first:")
        print(g.sort_values("pct_needs_check", ascending=False).head(12).to_string())


if __name__ == "__main__":
    main()
