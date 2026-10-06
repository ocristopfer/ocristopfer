"""Render the profile stats card (light and dark SVG) from the GitHub GraphQL API.

Stdlib only, so the workflow needs no pip install and no third-party service:
the public github-readme-stats instance is rate limited and has gone down
often, and a broken image on the profile is worse than no card at all.

Usage: GITHUB_TOKEN=... python3 scripts/stats_card.py <login> <out_dir>
"""

import json
import os
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

API = "https://api.github.com/graphql"

QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    name
    login
    followers { totalCount }
    pullRequests { totalCount }
    contributionsCollection {
      totalCommitContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount } }
      }
    }
    repositories(ownerAffiliations: OWNER, privacy: PUBLIC, first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        isFork
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

THEMES = {
    "light": {"bg": "#ffffff", "border": "#d0d7de", "text": "#1f2328", "muted": "#59636e", "accent": "#0969da"},
    "dark": {"bg": "#0d1117", "border": "#30363d", "text": "#e6edf3", "muted": "#8b949e", "accent": "#4493f8"},
}

WIDTH, HEIGHT, PAD = 800, 260, 24
# Five plus "Other" fills the legend's two rows of three; a seventh item falls off the card.
TOP_LANGUAGES = 5
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"


def graphql(token, variables):
    body = json.dumps({"query": QUERY, "variables": variables}).encode()
    request = urllib.request.Request(API, data=body, headers={"Authorization": f"bearer {token}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    # A partial answer would render a card with zeros that looks real; failing keeps the last good one.
    if payload.get("errors"):
        raise SystemExit(f"GraphQL error: {payload['errors']}")
    return payload["data"]["user"]


def collect(token, login):
    user, repos, cursor = None, [], None
    while True:
        page = graphql(token, {"login": login, "cursor": cursor})
        user = user or page
        repos += page["repositories"]["nodes"]
        info = page["repositories"]["pageInfo"]
        if not info["hasNextPage"]:
            break
        cursor = info["endCursor"]

    # Forks carry upstream code (RE-UE4SS is mostly C++ nobody here wrote), so they stay out of
    # the language mix; their stars still count, they were given to this account's copy.
    sizes, colors = {}, {}
    for repo in repos:
        if repo["isFork"]:
            continue
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            sizes[name] = sizes.get(name, 0) + edge["size"]
            colors[name] = edge["node"]["color"] or "#8b949e"

    calendar = user["contributionsCollection"]["contributionCalendar"]
    return {
        "name": user["name"] or user["login"],
        "login": user["login"],
        "stats": [
            ("Stars", sum(r["stargazerCount"] for r in repos)),
            ("Contributions", calendar["totalContributions"]),
            ("Commits", user["contributionsCollection"]["totalCommitContributions"]),
            ("Pull requests", user["pullRequests"]["totalCount"]),
            ("Repositories", sum(1 for r in repos if not r["isFork"])),
            ("Followers", user["followers"]["totalCount"]),
        ],
        "weeks": [sum(d["contributionCount"] for d in w["contributionDays"]) for w in calendar["weeks"]],
        "languages": top_languages(sizes, colors),
    }


def top_languages(sizes, colors):
    total = sum(sizes.values()) or 1
    ranked = sorted(sizes.items(), key=lambda item: item[1], reverse=True)
    result = [(name, size / total, colors[name]) for name, size in ranked[:TOP_LANGUAGES]]
    rest = sum(size for _, size in ranked[TOP_LANGUAGES:])
    if rest:
        result.append(("Other", rest / total, "#8b949e"))
    return result


def short(number):
    if number >= 1000:
        return f"{number / 1000:.1f}k".replace(".0k", "k")
    return str(number)


def render(data, theme):
    c = THEMES[theme]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="{FONT}">',
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="12" '
        f'fill="{c["bg"]}" stroke="{c["border"]}"/>',
        f'<text x="{PAD}" y="40" font-size="18" font-weight="600" fill="{c["text"]}">'
        f"{escape(data['name'])}</text>",
        f'<text x="{WIDTH - PAD}" y="40" font-size="12" text-anchor="end" fill="{c["muted"]}">'
        f"@{escape(data['login'])} · contributions and commits: last 12 months</text>",
    ]

    cell = (WIDTH - 2 * PAD) / len(data["stats"])
    for i, (label, value) in enumerate(data["stats"]):
        x = PAD + i * cell
        out.append(f'<text x="{x:.1f}" y="100" font-size="28" font-weight="600" fill="{c["text"]}">{short(value)}</text>')
        out.append(f'<text x="{x:.1f}" y="122" font-size="12" fill="{c["muted"]}">{label}</text>')

    out.append(f'<line x1="{PAD}" y1="146" x2="{WIDTH - PAD}" y2="146" stroke="{c["border"]}"/>')
    out += render_languages(data["languages"], c)
    out += render_weeks(data["weeks"], c)
    out.append("</svg>")
    return "\n".join(out) + "\n"


def render_languages(languages, c):
    x0, width = PAD, 356
    out = [
        f'<text x="{x0}" y="174" font-size="12" font-weight="600" fill="{c["muted"]}">Top languages</text>',
        f'<clipPath id="bar"><rect x="{x0}" y="184" width="{width}" height="8" rx="4"/></clipPath>',
        '<g clip-path="url(#bar)">',
    ]
    x = x0
    for _, share, color in languages:
        out.append(f'<rect x="{x:.2f}" y="184" width="{share * width + 0.5:.2f}" height="8" fill="{color}"/>')
        x += share * width
    out.append("</g>")
    for i, (name, share, color) in enumerate(languages):
        lx, ly = x0 + (i % 3) * 122, 214 + (i // 3) * 22
        out.append(f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{color}" stroke="{c["muted"]}" stroke-opacity="0.5"/>')
        out.append(
            f'<text x="{lx + 15}" y="{ly}" font-size="12" fill="{c["text"]}">{escape(name)} '
            f'<tspan fill="{c["muted"]}">{share * 100:.1f}%</tspan></text>'
        )
    return out


def render_weeks(weeks, c):
    x0, width, top, bottom = 420, WIDTH - PAD - 420, 186, 240
    out = [f'<text x="{x0}" y="174" font-size="12" font-weight="600" fill="{c["muted"]}">Contributions per week</text>']
    peak = max(weeks, default=0) or 1
    step = width / max(len(weeks), 1)
    for i, count in enumerate(weeks):
        # Square root, not linear: one busy week would otherwise flatten the rest of the year into
        # a line. An empty week still gets a 2px stub, so the axis reads as a year, not missing data.
        level = (count / peak) ** 0.5
        height = max(2, (bottom - top) * level)
        opacity = 0.25 if count == 0 else 0.4 + 0.6 * level
        out.append(
            f'<rect x="{x0 + i * step:.2f}" y="{bottom - height:.2f}" width="{step * 0.7:.2f}" '
            f'height="{height:.2f}" rx="1" fill="{c["accent"]}" fill-opacity="{opacity:.2f}"/>'
        )
    return out


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    login, out_dir = sys.argv[1], Path(sys.argv[2])
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is not set")
    data = collect(token, login)
    out_dir.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        # newline="\n": on Windows text mode would write CRLF and every run would look like a change.
        (out_dir / f"stats-{theme}.svg").write_text(render(data, theme), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
