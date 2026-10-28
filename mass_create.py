"""
Mass create FunPay offers with auto-delivery.
Usage: PYTHONIOENCODING=utf-8 uv run python mass_create.py
"""
import sys, time, json, re
sys.path.insert(0, "src")
from funpay_mcp.client import FunPayClient
from bs4 import BeautifulSoup

c = FunPayClient(cookies_file=r"src/cookies.txt")

def check_session():
    r = c.session.get("https://funpay.com/", timeout=30)
    if "L1zard52" not in r.text:
        print("Auth FAILED. Run browser_login first.")
        return False
    c._authenticated = True
    return True

def scan_ad_nodes(limit=500):
    """Scan first N nodes for auto-delivery capability"""
    r = c.session.get("https://funpay.com/", timeout=30)
    soup = BeautifulSoup(r.text, "lxml")
    nodes = {}
    for a in soup.select("a[href*='/lots/']"):
        href = a.get("href","")
        txt = a.get_text(strip=True)
        if "/lots/" in href:
            nid = href.rstrip("/").split("/")[-1]
            if nid.isdigit():
                nodes[nid] = txt

    simple_ad = []
    for i, (nid, name) in enumerate(nodes.items()):
        if i >= limit:
            break
        try:
            r = c.session.get(f"https://funpay.com/lots/offerEdit?node={nid}", timeout=15)
            s = BeautifulSoup(r.text, "lxml")
            form = s.select_one("form[action*=offerSave]")
            if not form or not form.select_one("[name=secrets]"):
                continue

            selects = [el for el in form.select("select[name]")
                       if el.get("name","") not in ["csrf_token"]]

            extra = {}
            for sel in selects:
                for o in sel.select("option"):
                    if o.get("value",""):
                        extra[sel.get("name")] = o.get("value")
                        break

            sid = s.select_one("[name=server_id]")
            if sid:
                for o in sid.select("option"):
                    if o.get("value",""):
                        extra["server_id"] = o.get("value")
                        break

            simple_ad.append((nid, name, extra))
            print(f"  AD: {nid} {name} extra={extra}")
        except Exception as e:
            pass
        time.sleep(0.15)

    with open("ad_simple.json","w") as f:
        json.dump(simple_ad, f, ensure_ascii=False)
    print(f"\nFound {len(simple_ad)} simple AD nodes")
    return simple_ad

def create_single(nid, name, extra):
    """Create 3 offers for one node"""
    url = f"https://funpay.com/lots/offerEdit?node={nid}"
    r = c.session.get(url, timeout=30)
    s = BeautifulSoup(r.text, "lxml")

    body = s.select_one("body")
    if body and body.get("data-app-data"):
        ad = json.loads(body["data-app-data"])
        t = ad.get("csrf-token")
        if t:
            c.csrf_token = t

    form = s.select_one("form[action*=offerSave]")
    base = {}
    for el in form.select("input[name], textarea[name], select[name]"):
        n = el.get("name","")
        if not n:
            continue
        if el.name == "select":
            opt = el.select_one("option[selected]") or el.select_one("option")
            base[n] = opt.get("value","") if opt else ""
        elif el.name == "textarea":
            base[n] = el.get_text() or ""
        else:
            if el.get("type","") == "checkbox":
                if el.has_attr("checked"):
                    base[n] = "on"
            else:
                base[n] = el.get("value","")

    base.update(extra)
    headers = {"X-Requested-With": "XMLHttpRequest", "Referer": url}

    titles = [
        f"{name}: Guide for beginners",
        f"{name}: Tips and secrets",
        f"{name}: Best strategies",
    ]

    ok = 0
    for title in titles:
        d = dict(base)
        d["csrf_token"] = c.get_csrf_token()
        d["form_created_at"] = str(int(time.time()))
        d["offer_id"] = "0"
        d["node_id"] = nid
        d["fields[summary][ru]"] = title
        d["fields[summary][en]"] = title
        d["fields[desc][ru]"] = title
        d["fields[desc][en]"] = title
        d["fields[payment_msg][ru]"] = "Spasibo!"
        d["fields[payment_msg][en]"] = "Thanks!"
        d["price"] = "5"
        d["amount"] = "99999"
        d["active"] = "on"
        d["auto_delivery"] = "on"
        d["secrets"] = f"=== {title.upper()} ===\n1. Step one\n2. Step two\n3. Pro tips"

        try:
            resp = c.session.post(
                "https://funpay.com/lots/offerSave", data=d, headers=headers, timeout=30
            )
            rj = resp.json()
            if rj.get("done"):
                ok += 1
            else:
                err = rj.get("error","") or str(rj.get("errors",""))
                if err:
                    print(f"  FAIL {nid}: {title[:40]} -> {err[:100]}")
        except Exception as e:
            print(f"  ERR {nid}: {e}")
        time.sleep(0.3)
    return ok

if __name__ == "__main__":
    if not check_session():
        sys.exit(1)

    # Use cached or scan
    try:
        with open("ad_simple.json","r") as f:
            nodes = json.load(f)
        print(f"Loaded {len(nodes)} cached AD nodes")
    except FileNotFoundError:
        nodes = scan_ad_nodes(500)

    total = 0
    for i, (nid, name, extra) in enumerate(nodes):
        created = create_single(nid, name, extra)
        total += created
        print(f"[{i+1}/{len(nodes)}] {name}: +{created} (total: {total})")
        time.sleep(1)

    print(f"\n=== CREATED: {total} ===")

    r = c.session.get("https://funpay.com/users/19702923/", timeout=30)
    s = BeautifulSoup(r.text, "lxml")
    total_offers = len(s.select("a[href*='offer?id=']"))
    print(f"Total on account: {total_offers}")
