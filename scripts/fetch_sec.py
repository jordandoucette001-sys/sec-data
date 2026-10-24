#!/usr/bin/env python3
"""Fetch free SEC EDGAR data for the tickers in symbols.txt:
  data/earnings_8k.csv    - every 8-K with Item 2.02 (results of operations = earnings release), 2018+
  data/eps_frames.csv     - quarterly diluted EPS as reported (XBRL frames), 2018+
  data/shares_frames.csv  - shares outstanding per quarter (XBRL frames), 2018+
  data/missing_tickers.txt
SEC asks for a descriptive User-Agent with contact info and <= 10 requests/second.
"""
import csv, json, os, sys, time, urllib.request, urllib.error

UA = os.environ.get("SEC_UA", "research-bot contact@example.com")
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
SLEEP = 0.12  # ~8 requests/second


def get_json(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                time.sleep(SLEEP)
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def main():
    os.makedirs("data", exist_ok=True)
    symbols = [l.strip().upper().replace(".", "-") for l in open("symbols.txt") if l.strip()]

    # 1) ticker -> CIK map
    tick = get_json("https://www.sec.gov/files/company_tickers.json")
    if not tick:
        print("could not load company_tickers.json"); sys.exit(1)
    t2c = {}
    for v in tick.values():
        t2c[v["ticker"].upper().replace(".", "-")] = int(v["cik_str"])
    missing = [s for s in symbols if s not in t2c]
    open("data/missing_tickers.txt", "w").write("\n".join(missing) + "\n")
    print(f"{len(symbols)} symbols, {len(missing)} not found in SEC map")

    # 2) 8-K item 2.02 filings per company (recent block + older pages)
    rows = []
    for i, s in enumerate(symbols):
        cik = t2c.get(s)
        if not cik:
            continue
        sub = get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        if not sub:
            continue
        blocks = [sub.get("filings", {}).get("recent", {})]
        for f in sub.get("filings", {}).get("files", []):
            if f.get("filingTo", "0000") >= "2018":
                older = get_json("https://data.sec.gov/submissions/" + f["name"])
                if older:
                    blocks.append(older)
        for b in blocks:
            forms = b.get("form", []); items = b.get("items", [])
            fdate = b.get("filingDate", []); rdate = b.get("reportDate", [])
            acc = b.get("accessionNumber", []); atime = b.get("acceptanceDateTime", [])
            for k in range(len(forms)):
                if forms[k] in ("8-K", "8-K/A") and "2.02" in (items[k] or "").split(",") and fdate[k] >= "2018-01-01":
                    rows.append([s, cik, fdate[k], rdate[k] if k < len(rdate) else "",
                                 atime[k] if k < len(atime) else "", acc[k] if k < len(acc) else ""])
        if (i + 1) % 100 == 0:
            print(f"{i+1}/{len(symbols)} companies, {len(rows)} earnings 8-Ks so far", flush=True)
    rows.sort()
    with open("data/earnings_8k.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["ticker", "cik", "filingDate", "reportDate", "acceptanceDateTime", "accession"]); w.writerows(rows)
    print(f"wrote {len(rows)} earnings 8-K rows")

    # 3) XBRL frames: diluted EPS (quarterly durations) and shares outstanding (instants)
    want = set(t2c[s] for s in symbols if s in t2c)
    years = range(2018, 2027)
    eps_rows, sh_rows = [], []
    for y in years:
        for q in (1, 2, 3, 4):
            fr = get_json(f"https://data.sec.gov/api/xbrl/frames/us-gaap/EarningsPerShareDiluted/USD-per-shares/CY{y}Q{q}.json")
            if fr:
                for d in fr.get("data", []):
                    if d.get("cik") in want:
                        eps_rows.append([d["cik"], f"CY{y}Q{q}", d.get("start"), d.get("end"), d.get("val"), d.get("accn"), d.get("fy"), d.get("fp")])
            fr2 = get_json(f"https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/CY{y}Q{q}I.json")
            if fr2:
                for d in fr2.get("data", []):
                    if d.get("cik") in want:
                        sh_rows.append([d["cik"], f"CY{y}Q{q}I", d.get("end"), d.get("val"), d.get("accn")])
    c2t = {}
    for s in symbols:
        if s in t2c:
            c2t.setdefault(t2c[s], s)
    with open("data/eps_frames.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["cik", "ticker", "frame", "start", "end", "eps_diluted", "accession", "fy", "fp"])
        for r in sorted(eps_rows):
            w.writerow([r[0], c2t.get(r[0], ""), *r[1:]])
    with open("data/shares_frames.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["cik", "ticker", "frame", "end", "shares_outstanding", "accession"])
        for r in sorted(sh_rows):
            w.writerow([r[0], c2t.get(r[0], ""), *r[1:]])
    print(f"wrote {len(eps_rows)} EPS rows and {len(sh_rows)} shares rows")


if __name__ == "__main__":
    main()
