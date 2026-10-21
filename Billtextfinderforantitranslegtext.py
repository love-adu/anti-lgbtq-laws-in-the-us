# grabs the full text of every bill in the aclu tracker csvs
# this goes through legiscan
#
# pip install pandas requests beautifulsoup4 pypdf python-dateutil
# free key at legiscan.com/legiscan, put it in LEGISCAN_API_KEY (they cap queries per month!!)
#
#   python billtextfinderforantitranslegtext.py --data ./csvs --dry-run     no api calls
#   python billtextfinderforantitranslegtext.py --data ./csvs --limit 10    just 10 bills
#   python billtextfinderforantitranslegtext.py --data ./csvs               everything
#

import argparse, base64, glob, io, json, os, re, sys, time, unicodedata, zipfile
import pandas as pd
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

API = "https://api.legiscan.com/"
OUT_DIR = "billtextdeclassed"
CLEAN_CSV = "billstofindcleaned.csv"
RESULTS_CSV = "resultsfromanalysisforantitranslegdata.csv"
FILE_PREFIX = "billis"

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
    "puerto rico": "PR",
}

# the pro-equality categories get dropped unless you pass --keep-all!!!!
GOOD = {"lgbtq equality bills", "nondiscrimination protections", "other good bills",
        "sex work discriminalization bills", "allowing updated gender markers on id",
        "protections in healthcare"}

# set in main()
KEY = None
CACHE = None
SLEEP = 0.25


def get_state(s):
    s = (s or "").strip().replace("\u02bb", "").replace("'", "")
    if s.upper() in STATES.values():
        return s.upper()
    return STATES.get(s.lower())


def parse_bill(txt):
    # S.B.9 -> ("SB", 9, None). colorado does HB 20-1114, which is bill 1114 from 2020
    p = re.sub(r"[\.\s]", "", txt.upper())
    m = re.match(r"^([A-Z]+)(\d{2})-(\d+)$", p)
    if m:
        return m.group(1), int(m.group(3)), 2000 + int(m.group(2))
    # a letter on the end is just an amended version. LC is rhode island drafts, can't search those
    m = re.match(r"^([A-Z]+)0*(\d+)-?[A-Z]?$", p)
    if m and m.group(1) != "LC":
        return m.group(1), int(m.group(2)), None
    return None


def read_csvs(folder):
    dfs = []
    for f in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        first = open(f, encoding="utf-8", errors="ignore").readline()
        skip = 1 if first.count(",") == 0 else 0  # the 2020 file has a title row on top
        d = pd.read_csv(f, skiprows=skip, dtype=str)
        d.columns = [c.strip() for c in d.columns]
        if "Bill Name" not in d.columns:
            print("skipping", f, "(no Bill Name column)")
            continue
        d["source_file"] = os.path.basename(f)
        dfs.append(d)
    if not dfs:
        sys.exit("no csvs in " + folder)
    return pd.concat(dfs, ignore_index=True)


def year_from_name(fname):
    m = re.search(r"(20\d\d)(?!-\d\d-\d\d)", fname)
    return int(m.group(1)) if m else None


def clean_rows(raw, keep_all=False):
    for c in ["State", "Bill Name", "Issues", "Status", "Status Detail", "Status Date", "In Court Link"]:
        if c not in raw.columns:
            raw[c] = ""
        raw[c] = raw[c].fillna("").str.strip()

    rows = []
    gone = {"blank": 0, "footer": 0, "good": 0, "state": 0, "bill": 0}
    for r in raw.to_dict("records"):
        if not r["State"] and not r["Bill Name"]:
            gone["blank"] += 1
            continue
        if r["State"].lower().startswith("data is current"):
            gone["footer"] += 1
            continue
        st = get_state(r["State"])
        if not st:
            gone["state"] += 1
            continue
        cat = r["Issues"].split("|")[0].strip().lower()
        if not keep_all and cat in GOOD:
            gone["good"] += 1
            continue
        try:
            sd = dateparser.parse(r["Status Date"]) if r["Status Date"] else None
        except (ValueError, OverflowError):
            sd = None
        # some cells have two bills in them, like SB 2077/HB 1572
        for part in re.split(r"\s*(?:/|;|,|&|\band\b)\s*", r["Bill Name"]):
            if not part.strip():
                continue
            pb = parse_bill(part)
            if not pb:
                gone["bill"] += 1
                continue
            yr = sd.year if sd else (pb[2] or year_from_name(r["source_file"]))
            rows.append({
                "state": st, "bill_raw": r["Bill Name"], "bill_key": pb[0] + str(pb[1]), "year": yr,
                "status_date": sd.date().isoformat() if sd else "",
                "issue_category": r["Issues"].split("|")[0].strip(), "issue_detail": r["Issues"],
                "status": r["Status"], "status_detail": r["Status Detail"],
                "court_link": r["In Court Link"], "source_file": r["source_file"]})
    print("dropped:", gone)

    df = pd.DataFrame(rows)
    df["year"] = df["year"].astype("Int64")
    # the same bill is in a bunch of files so squash to one row per state/bill/year
    df = df.sort_values("status_date").groupby(["state", "bill_key", "year"], dropna=False).agg(
        bill_raw=("bill_raw", "first"), status_date=("status_date", "last"),
        status=("status", "last"), status_detail=("status_detail", "last"),
        issue_category=("issue_category", lambda s: " | ".join(dict.fromkeys(s))),
        issue_detail=("issue_detail", lambda s: " || ".join(dict.fromkeys(s))),
        court_link=("court_link", lambda s: next((x for x in s if x), "")),
        source_file=("source_file", lambda s: " | ".join(dict.fromkeys(s))),
    ).reset_index()
    # a row with no year is a dupe if that bill already has one with a year
    dated = df[df["year"].notna()].set_index(["state", "bill_key"]).index
    dupe = df["year"].isna() & df.set_index(["state", "bill_key"]).index.isin(dated)
    return df[~dupe].reset_index(drop=True)


class Quota(Exception):
    pass


def legiscan(op, name, **params):
    path = os.path.join(CACHE, "api", name + ".json")
    if os.path.exists(path):
        return json.load(open(path))
    params.update(key=KEY, op=op)
    for i in range(4):
        try:
            data = requests.get(API, params=params, timeout=60).json()
            break
        except (requests.RequestException, ValueError):
            time.sleep(2 ** i)
    else:
        raise RuntimeError(op + " kept failing")
    if data.get("status") != "OK":
        msg = (data.get("alert") or {}).get("message", str(data))
        if re.search(r"quota|limit|exceed", msg, re.I):
            raise Quota(msg)
        return {}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(data, open(path, "w"))
    time.sleep(SLEEP)
    return data


def search(state, key, year):
    d = legiscan("getSearch", f"search_{state}_{key}_{year}", state=state, bill=key, year=year)
    hits = []
    for k, v in d.get("searchresult", {}).items():
        if not (isinstance(v, dict) and "bill_id" in v):
            continue
        pb = parse_bill(v.get("bill_number", ""))
        if v.get("state") == state and pb and pb[0] + str(pb[1]) == key:
            hits.append(v)
    return hits


def find_bill(state, key, year, sdate):
    hits = search(state, key, int(year)) if year else []
    if not hits:
        hits = search(state, key, 1)  # 1 means all years
    if not hits:
        return None
    # more than one session? take the one closest to the status date
    if len(hits) > 1:
        if sdate:
            t = pd.Timestamp(sdate)
            hits.sort(key=lambda h: abs(pd.Timestamp(h.get("last_action_date") or "1900-01-01") - t))
        else:
            hits.sort(key=lambda h: h.get("last_action_date") or "", reverse=True)
    return hits[0]


def to_text(blob, mime):
    mime = (mime or "").lower()
    if "html" in mime:
        soup = BeautifulSoup(blob.decode("utf-8", errors="ignore"), "html.parser")
        for t in soup(["script", "style"]):
            t.decompose()
        return soup.get_text("\n")
    if "pdf" in mime:
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(blob)).pages)
    if "wordprocessingml" in mime or mime.endswith("docx"):
        xml = zipfile.ZipFile(io.BytesIO(blob)).read("word/document.xml").decode("utf-8", errors="ignore")
        return re.sub(r"<[^>]+>", "", xml.replace("</w:p>", "\n"))
    if mime.startswith("text/"):
        return blob.decode("utf-8", errors="ignore")
    return None  # old .doc / rtf / wordperfect, skipping those


def tidy(t):
    t = unicodedata.normalize("NFKC", t).replace("\xa0", " ")
    keep = []
    for ln in t.splitlines():
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        if re.fullmatch(r"\d{1,3}", ln):  # line numbers and page numbers on their own
            continue
        keep.append(ln)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip()


def pick_versions(texts, want):
    if not texts:
        return {}
    texts = sorted(texts, key=lambda x: (x.get("date") or "", x.get("doc_id", 0)))
    first = next((x for x in texts if "introduc" in (x.get("type") or "").lower()), texts[0])
    both = {"introduced": first, "latest": texts[-1]}
    return {k: v for k, v in both.items() if k in want}


def main():
    global KEY, CACHE, SLEEP
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=".")
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--key", default=os.environ.get("LEGISCAN_API_KEY"))
    ap.add_argument("--versions", default="introduced,latest")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-all", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.25)
    a = ap.parse_args()
    KEY, CACHE, SLEEP = a.key, os.path.join(a.out, "cache"), a.sleep

    os.makedirs(os.path.join(a.out, "text"), exist_ok=True)
    rows = clean_rows(read_csvs(a.data), a.keep_all)
    rows.to_csv(os.path.join(a.out, CLEAN_CSV), index=False)
    print(len(rows), "rows after cleaning")
    if a.dry_run:
        print("dry run, nothing fetched. look at", os.path.join(a.out, CLEAN_CSV))
        return
    if not KEY:
        sys.exit("need a legiscan key (--key or LEGISCAN_API_KEY)")

    want = set(a.versions.split(","))
    if a.limit:
        rows = rows.head(a.limit)
    results, seen = [], {}
    res_path = os.path.join(a.out, RESULTS_CSV)

    try:
        for i, r in enumerate(rows.to_dict("records"), 1):
            base = dict(r, legiscan_bill_id="", legiscan_url="", version="", doc_type="",
                        doc_date="", mime="", text_path="", n_words=0, fetch_status="")
            print(f"{i}/{len(rows)} {r['state']} {r['bill_key']} {r['year']}", end=" ... ")
            hit = find_bill(r["state"], r["bill_key"], r["year"], r["status_date"])
            if not hit:
                results.append(dict(base, fetch_status="not_found"))
                print("not found")
                continue
            bid = hit["bill_id"]
            base["legiscan_bill_id"] = bid

            # only download each bill once, even if it's in the list a few times
            if bid not in seen:
                bill = legiscan("getBill", f"bill_{bid}", id=bid).get("bill")
                got = []
                for v, tx in pick_versions((bill or {}).get("texts", []), want).items():
                    fn = f"{FILE_PREFIX}_{r['state']}_{r['bill_key']}_{bid}_{v}.txt"
                    path = os.path.join(a.out, "text", fn)
                    if not os.path.exists(path):
                        t = legiscan("getBillText", f"text_{tx['doc_id']}", id=tx["doc_id"]).get("text")
                        txt = to_text(base64.b64decode(t["doc"]), t.get("mime", "")) if t else None
                        if not txt or not txt.strip():
                            got.append((v, tx, "", (t or {}).get("mime", ""), "no_text_or_bad_mime"))
                            continue
                        open(path, "w", encoding="utf-8").write(tidy(txt))
                    got.append((v, tx, path, tx.get("mime", ""), "ok"))
                seen[bid] = (bill, got)

            bill, got = seen[bid]
            base["legiscan_url"] = (bill or {}).get("url", "")
            if not got:
                results.append(dict(base, fetch_status="no_texts_listed"))
                print("no versions listed")
                continue
            for v, tx, path, mime, status in got:
                row = dict(base, version=v, doc_type=tx.get("type", ""), doc_date=tx.get("date", ""),
                           mime=mime, text_path=path, fetch_status=status)
                if path:
                    row["n_words"] = len(open(path, encoding="utf-8").read().split())
                results.append(row)
            print("ok")
            if i % 25 == 0:
                pd.DataFrame(results).to_csv(res_path, index=False)
    except Quota as e:
        print("\nhit the quota, stopping. run it again later, the cache keeps your progress.", e)
    except KeyboardInterrupt:
        print("\nstopped, progress is cached")
    finally:
        pd.DataFrame(results).to_csv(res_path, index=False)
        print("results saved to", res_path)


if __name__ == "__main__":
    main()
