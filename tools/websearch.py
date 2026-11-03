import json
import js

DESCRIPTION = "Search the web. Returns JSON array of results with title, url, snippet."

async def run(query, max_results=10):
    query = str(query).strip()
    if not query:
        raise ValueError("query must not be empty")

    max_results = max(1, min(20, int(max_results)))

    # DuckDuckGo's HTML endpoint gives normal server-rendered search results.
    target = (
        "https://html.duckduckgo.com/html/?q="
        + str(js.encodeURIComponent(query))
    )

    # Direct DuckDuckGo fetch is normally blocked by browser CORS, so fetch the
    # raw HTML through a CORS-capable proxy. No Python networking modules needed.
    proxy_urls = [
        "https://api.codetabs.com/v1/proxy?quest="
        + str(js.encodeURIComponent(target)),
        "https://api.allorigins.win/raw?url="
        + str(js.encodeURIComponent(target)),
    ]

    html = None
    errors = []
    for proxy_url in proxy_urls:
        try:
            response = await js.fetch(proxy_url)
            if response.ok:
                html = str(await response.text())
                if html:
                    break
            else:
                errors.append("HTTP " + str(response.status))
        except Exception as error:
            errors.append(str(error))

    if not html:
        raise RuntimeError(
            "web search fetch failed: " + "; ".join(errors)
        )

    # Parse the real DDG result DOM in JavaScript; this avoids BeautifulSoup,
    # html.parser, urllib, requests, sockets, etc.
    document = js.DOMParser.new().parseFromString(html, "text/html")
    nodes = document.querySelectorAll(".result")
    results = []
    seen = set()

    for index in range(int(nodes.length)):
        if len(results) >= max_results:
            break

        node = nodes.item(index)
        anchor = node.querySelector(".result__a")
        if anchor is None:
            continue

        title = str(anchor.textContent or "").strip()
        href = str(anchor.getAttribute("href") or "").strip()
        if not title or not href:
            continue

        # Skip DuckDuckGo ad/tracking links.
        if "duckduckgo.com/aclick" in href or "duckduckgo.com/y.js" in href:
            continue

        # DDG usually wraps result URLs as /l/?uddg=<real-url>.
        try:
            parsed = js.URL.new(href, target)
            real_url = parsed.searchParams.get("uddg")
            if real_url is not None and str(real_url):
                href = str(real_url)
            else:
                href = str(parsed.href)
        except Exception:
            pass

        if not href.startswith("http"):
            continue
        if href in seen:
            continue

        snippet_node = node.querySelector(".result__snippet")
        snippet = (
            str(snippet_node.textContent or "").strip()
            if snippet_node is not None
            else ""
        )

        seen.add(href)
        results.append({
            "title": title,
            "url": href,
            "snippet": snippet,
        })

    if not results:
        raise RuntimeError("search returned no parseable results")

    return json.dumps(results)
