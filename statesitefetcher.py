# gets bill text straight from state legislature sites, for the bills legiscan didn't give us
#
# python statesitefetcher.py                 (reads billtextdeclassed/missing_bills.csv)
# python statesitefetcher.py --states SC,FL

import argparse, os, re, time
from urllib.parse import urljoin
import pandas as pd
import requests
from bs4 import BeautifulSoup
from billtextfinderforantitranslegtext import to_text, tidy, FILE_PREFIX, OUT_DIR

RESULTS_CSV = "resultsfromstatesites.csv"

sess = requests.Session()
sess.headers["User-Agent"] = "Mozilla/5.0 (bill text research script)"


def get(url):
    for i in range(3):
        try:
            r = sess.get(url, timeout=60)
            time.sleep(0.5)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r
        except requests.RequestException:
            time.sleep(2 ** i)
    return None


def soup_of(r):
    return BeautifulSoup(r.text, "html.parser")


EXT_MIME = {".pdf": "application/pdf", ".docx": "application/docx", ".doc": "application/msword",
            ".htm": "text/html", ".html": "text/html"}


def doc_via_word(blob):
    # old binary .doc (puerto rico) -> text, using word through powershell
    import subprocess, tempfile
    d = tempfile.mkdtemp()
    src, dst = os.path.join(d, "in.doc"), os.path.join(d, "out.txt")
    open(src, "wb").write(blob)
    ps = (f"$w = New-Object -ComObject Word.Application; $w.Visible = $false; "
          f"$doc = $w.Documents.Open('{src}', $false, $true); $doc.SaveAs([ref]'{dst}', [ref]7); "
          f"$doc.Close($false); $w.Quit()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=180)
    if not os.path.exists(dst):
        return None
    raw = open(dst, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw[1:2] == b"\x00":  # utf-16le with no bom
        return raw.decode("utf-16-le", errors="ignore")
    return raw.decode("cp1252", errors="ignore")


def fetch_doc(url):
    # -> (text, mime) or (None, mime)
    r = get(url)
    if not r:
        return None, ""
    mime = r.headers.get("content-type", "").split(";")[0]
    if mime in ("", "application/octet-stream"):
        ext = os.path.splitext(url.split("?")[0].lower())[1]
        mime = EXT_MIME.get(ext, mime)
    if mime == "application/msword":
        return doc_via_word(r.content), mime
    return to_text(r.content, mime), mime


def split_key(key):
    m = re.match(r"^([A-Z]+)(\d+)$", key)
    return m.group(1), int(m.group(2))


# each one returns {version: url} plus an id for the file name, or None if not found

def sc(key, year):
    _, n = split_key(key)
    for y in (year, year - 2):
        start = y if y % 2 else y - 1
        base = f"https://www.scstatehouse.gov/sess{124 + (start - 2021) // 2}_{start}-{start + 1}"
        r = get(f"{base}/bills/{n}.htm")
        if not r or not re.search(rf"Bill {n}\b", r.text):
            continue
        # older sessions link these as '../prever/...'
        prev = sorted(urljoin(f"{base}/bills/", a["href"]) for a in soup_of(r).find_all("a", href=True)
                      if "/prever/" in a["href"])
        return f"sc{start}", {"introduced": prev[0] if prev else f"{base}/bills/{n}.htm",
                              "latest": f"{base}/bills/{n}.htm"}
    return None


def wv(key, year):
    _, n = split_key(key)
    for y in (year, year - 1, year + 1):
        r = get(f"https://www.wvlegislature.gov/Bill_Status/Bills_history.cfm?input={n}&year={y}&sessiontype=RS")
        if not r:
            continue
        pdfs = [a["href"] for a in soup_of(r).find_all("a", href=True)
                if "/Bill_Text_HTML/" in a["href"] and a["href"].lower().endswith(".pdf")
                and re.search(rf"/{key.lower()} ", a["href"].lower())]
        if not pdfs:
            continue
        pdfs = ["https://www.wvlegislature.gov" + p.replace(" ", "%20") for p in dict.fromkeys(pdfs)]
        intr = next((p for p in pdfs if "%20intr" in p.lower()), pdfs[-1])
        return f"wv{y}", {"introduced": intr, "latest": pdfs[0]}  # newest is listed first
    return None


def fl(key, year):
    ch, n = split_key(key)
    for y in (year, year - 1):
        r = get(f"https://www.flsenate.gov/Session/Bill/{y}/{n}")
        if not r or not re.search(rf"\b{ch} {n}\b", r.text):
            continue
        vers = [a["href"] for a in soup_of(r).find_all("a", href=True)
                if re.search(r"/BillText/[^/]+/PDF$", a["href"])]
        vers = list(dict.fromkeys(vers[1:] or vers))  # first link is the 'current version' shortcut
        if not vers:
            continue
        vers = ["https://www.flsenate.gov" + v for v in vers]
        intr = next((v for v in vers if "/Filed/" in v), vers[0])
        return f"fl{y}", {"introduced": intr, "latest": vers[-1]}
    return None


def wy(key, year):
    ch, n = split_key(key)
    bill = f"{ch}{n:04d}"
    for y in (year, year - 1):
        r = get(f"https://web.wyoleg.gov/LsoService/api/BillInformation/{y}/{bill}?calendarDate=")
        if not r:
            continue
        try:
            j = r.json()
        except ValueError:
            continue
        if not j or not j.get("introduced"):
            continue
        out = {"introduced": "https://wyoleg.gov/" + j["introduced"]}
        latest = j.get("enrolledAct") or j.get("engrossedVersion") or j["introduced"]
        out["latest"] = "https://wyoleg.gov/" + latest.lstrip("/")
        return f"wy{y}", out
    return None


def exists(url):
    r = get(url)
    return bool(r) and len(r.content) > 500


def id_(key, year):
    ch, n = split_key(key)
    code = f"{ch[0]}{n:04d}"
    r = get(f"https://legislature.idaho.gov/sessioninfo/{year}/legislation/{code}/")
    if not r:
        return None
    pdfs = [a["href"] for a in soup_of(r).find_all("a", href=True)
            if re.search(rf"/legislation/{code}[A-Z0-9]*\.pdf$", a["href"])]
    # skip statement of purpose / fiscal note pdfs, keep bill, amendments (A), engrossments (E1..)
    pdfs = [p if p.startswith("http") else "https://legislature.idaho.gov" + p
            for p in dict.fromkeys(pdfs) if not re.search(r"SOP|FN", p.rsplit("/", 1)[-1])]
    if not pdfs:
        return None
    intr = next((p for p in pdfs if p.endswith(f"/{code}.pdf")), pdfs[0])
    eng = sorted(p for p in pdfs if re.search(rf"/{code}E\d+\.pdf$", p))
    return f"id{year}", {"introduced": intr, "latest": eng[-1] if eng else intr}


def ri(key, year):
    ch, n = split_key(key)
    yy, house = year % 100, "House" if ch == "HB" else "Senate"
    base = f"https://webserver.rilegislature.gov/BillText/BillText{yy}/{house}Text{yy}/{ch[0]}{n:04d}"
    if not exists(base + ".pdf"):
        return None
    latest = base + ".pdf"
    for suf in ("A", "Aaa", "B", "Baa"):  # sub A, sub A as amended, ...
        if exists(base + suf + ".pdf"):
            latest = base + suf + ".pdf"
    return f"ri{year}", {"introduced": base + ".pdf", "latest": latest}


def nc(key, year):
    ch, n = split_key(key)
    start = year if year % 2 else year - 1
    house = "House" if ch == "HB" else "Senate"
    base = f"https://www.ncleg.gov/Sessions/{start}/Bills/{house}/PDF/{ch[0]}{n}v"
    vers = []
    for k in range(1, 12):
        if not exists(f"{base}{k}.pdf"):
            break
        vers.append(f"{base}{k}.pdf")
    return (f"nc{start}", {"introduced": vers[0], "latest": vers[-1]}) if vers else None


def nh(key, year):
    ch, n = split_key(key)
    for y in (year, year - 1):
        u = f"https://gc.nh.gov/legislation/{y}/{ch}{n:04d}.html"
        r = get(u)
        if r and re.search(rf"{ch}\s*{n}\b", r.text):
            return f"nh{y}", {"introduced": u, "latest": u}
    return None


def oh(key, year):
    ch, n = split_key(key)
    ga = 135 + (year - 2023) // 2
    base = f"https://search-prod.lis.state.oh.us/api/v2/general_assembly_{ga}/legislation/{ch.lower()}{n}"
    if not exists(f"{base}/00_IN/pdf/"):
        return None
    latest = f"{base}/00_IN/pdf/"
    for v in ("01_RH", "02_PH", "03_RS", "04_PS", "05_EN"):
        if exists(f"{base}/{v}/pdf/"):
            latest = f"{base}/{v}/pdf/"
    return f"oh{ga}", {"introduced": f"{base}/00_IN/pdf/", "latest": latest}


VA_API = "https://lis.virginia.gov"
VA_KEY = {"WebAPIKey": "FCE351B6-9BD8-46E0-B18F-5572F4CCA5B9"}  # the public key lis.virginia.gov's own pages use


def va(key, year):
    ch, n = split_key(key)
    bill = f"{ch[0]}J{n}"  # tracker 'H.J. 86' = HJ86 joint resolution
    for y in (year, year - 1):
        r = sess.get(VA_API + "/LegislationVersion/api/GetLegislationVersionbyBillNumberAsync",
                     params={"billNumber": bill, "sessionCode": f"{y}1"}, headers=VA_KEY, timeout=60)
        time.sleep(0.5)
        if r.status_code != 200 or not r.text:
            continue
        vers = sorted(r.json().get("LegislationsVersion") or [], key=lambda v: v.get("DraftDate") or "")
        if vers:
            u = VA_API + "/LegislationText/api/GetLegislationTextByIDAsync?legislationTextID="
            return f"va{y}", {"introduced": u + str(vers[0]["LegislationTextID"]),
                              "latest": u + str(vers[-1]["LegislationTextID"])}
    return None


def ma(key, year):
    ch, n = split_key(key)
    court = 192 + (year - 2021) // 2
    r = get(f"https://malegislature.gov/Bills/{court}/{ch}{n}")
    if not r:
        return None
    pdf = next((a["href"] for a in soup_of(r).find_all("a", href=True)
                if re.search(rf"/Bills/{court}/[A-Z]+\d+\.pdf$", a["href"])), None)
    if not pdf:
        return None
    pdf = "https://malegislature.gov" + pdf
    return f"ma{court}", {"introduced": pdf, "latest": pdf}


def me(key, year):
    ch, n = split_key(key)
    snum = 130 + (year - 2021) // 2
    u = f"https://legislature.maine.gov/legis/bills/getPDF.asp?paper={ch}{n:04d}&item=1&snum={snum}"
    return (f"me{snum}", {"introduced": u, "latest": u}) if exists(u) else None


def pr(key, year):
    ch, n = split_key(key)
    num = f"{ch}{n:04d}"
    r = get(f"https://sutra.oslpr.org/medidas?num_medida={num}&cuatrienio_id={2025 if year >= 2025 else 2021}")
    if not r:
        return None
    mid = next((h for h, t in re.findall(r'href="/medidas/(\d+)"[^>]*>(.*?)</a>', r.text, re.S)
                if re.search(rf"\b{num}\b", t)), None)
    if not mid:
        return None
    r = get(f"https://sutra.oslpr.org/medidas/{mid}")
    docs = list(dict.fromkeys(a["href"] for a in soup_of(r).find_all("a", href=True) if "/SutraFiles" in a["href"])) if r else []
    if not docs:
        return None
    docs = ["https://sutra.oslpr.org" + d.replace(" ", "%20") for d in docs]
    intr = next((d for d in docs if re.search(rf"/{num}\.(docx?|pdf)$", d, re.I)), docs[0])
    return f"pr{mid}", {"introduced": intr, "latest": docs[-1] if len(docs) > 1 else intr}


def md(key, year):
    # 'MD HD 3468' isn't a maryland number (theirs stop ~1500); it's massachusetts HD.3468 -> H.1536
    return ma(key, year) if key == "HD3468" else None


def va_text(url):
    r = sess.get(url, headers=VA_KEY, timeout=60)
    time.sleep(0.5)
    if r.status_code != 200 or not r.text:
        return None, ""
    j = r.json()
    item = (j.get("TextsList") or [j])[0]
    return to_text((item.get("DraftText") or "").encode("utf-8"), "text/html"), "text/html"


SITES = {"SC": sc, "WV": wv, "FL": fl, "WY": wy, "ID": id_, "RI": ri, "NC": nc, "NH": nh,
         "OH": oh, "VA": va, "MA": ma, "ME": me, "PR": pr, "MD": md}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--missing", default=os.path.join(OUT_DIR, "missing_bills.csv"))
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--states")
    ap.add_argument("--results", default=RESULTS_CSV)
    a = ap.parse_args()

    rows = pd.read_csv(a.missing, dtype=str).fillna("")
    if a.states:
        rows = rows[rows.state.isin(a.states.split(","))]
    os.makedirs(os.path.join(a.out, "text"), exist_ok=True)
    res_path = os.path.join(a.out, a.results)

    # remember successful lookups so reruns don't hammer the sites again
    import json
    cache_path = os.path.join(a.out, "cache", "statesites.json")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    found_cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    results, seen = [], {}
    try:
        for i, r in enumerate(rows.to_dict("records"), 1):
            base = dict(r, source="state_site", source_id="", version="", source_url="",
                        mime="", text_path="", n_words=0, fetch_status="")
            print(f"{i}/{len(rows)} {r['state']} {r['bill_key']} {r['year']}", end=" ... ")
            site = SITES.get(r["state"])
            if not site:
                results.append(dict(base, fetch_status="no_fetcher_for_state"))
                print("no fetcher")
                continue
            ck = (r["state"], r["bill_key"], r["year"])
            if ck not in seen:
                hit = found_cache.get("|".join(ck))
                if not hit and r["year"]:
                    hit = site(r["bill_key"], int(r["year"]))
                    if hit:
                        found_cache["|".join(ck)] = hit
                seen[ck] = hit
            found = seen[ck]
            if not found:
                results.append(dict(base, fetch_status="not_found"))
                print("not found")
                continue
            sid, vers = found
            for v, url in vers.items():
                fn = f"{FILE_PREFIX}_{r['state']}_{r['bill_key']}_{sid}_{v}.txt"
                path = os.path.join(a.out, "text", fn)
                status, mime = "ok", ""
                if not os.path.exists(path):
                    txt, mime = va_text(url) if url.startswith(VA_API) else fetch_doc(url)
                    if not txt or not txt.strip():
                        status, path = "no_text_or_bad_mime", ""
                    else:
                        open(path, "w", encoding="utf-8").write(tidy(txt))
                row = dict(base, source_id=sid, version=v, source_url=url, mime=mime,
                           text_path=path, fetch_status=status)
                if path:
                    row["n_words"] = len(open(path, encoding="utf-8").read().split())
                results.append(row)
            print("ok")
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        json.dump(found_cache, open(cache_path, "w"))
        pd.DataFrame(results).to_csv(res_path, index=False)
        print("results saved to", res_path)


if __name__ == "__main__":
    main()
