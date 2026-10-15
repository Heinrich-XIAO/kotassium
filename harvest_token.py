"""Headless-Firefox token harvester: load a logged-out player page, replay its own
/api/token call in page context, return the fresh access token."""
import json, sys, time

def harvest(timeout=60):
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    opts = Options()
    opts.add_argument("-headless")
    opts.binary_location = "/usr/bin/firefox"
    d = webdriver.Firefox(options=opts)
    try:
        d.get("https://open.spotify.com/search/harvest")
        t0 = time.time()
        mint_url = None
        while time.time() - t0 < timeout:
            mint_url = d.execute_script(
                "const es = performance.getEntriesByType('resource').map(e => e.name)"
                ".filter(n => n.includes('/api/token')); return es.length ? es[es.length-1] : null;")
            if mint_url:
                break
            time.sleep(1)
        if not mint_url:
            raise RuntimeError("page never minted a token")
        tok = d.execute_script(
            "return fetch(arguments[0]).then(r => r.json()).then(j => j.accessToken || JSON.stringify(j))",
            mint_url)
        return tok
    finally:
        d.quit()

if __name__ == "__main__":
    print(harvest())
