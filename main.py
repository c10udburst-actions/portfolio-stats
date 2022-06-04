import asyncio
import json
from datetime import datetime, timedelta
from os import getenv
from sys import stderr

from api import Api, traverse_object


async def github():
    # fetch data
    token = getenv("GH_TOKEN")
    api = Api("https://api.github.com/graphql", {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    })
    basic = traverse_object(await api.query("github/basic"), "data>viewer")  # statistics like followers, issues etc
    repos = await asyncio.gather(
        api.paginated_query("github/owner-repos",
                            "data>viewer>repositories>nodes",
                            "data>viewer>repositories>pageInfo>endCursor"),
        api.paginated_query("github/contributed-repos",
                            "data>viewer>repositoriesContributedTo>nodes",
                            "data>viewer>repositories>pageInfo>endCursor")
    )
    repos = [item for sublist in repos for item in sublist]  # flatten list
    prs = await api.paginated_query("github/prs",
                                    "data>viewer>pullRequests>nodes",
                                    "data>viewer>pullRequests>pageInfo>endCursor")
    gists = await api.paginated_query("github/gists",
                                      "data>viewer>gists>nodes",
                                      "data>viewer>gists>pageInfo>endCursor")
    await api.session.close()

    # parse data
    stats = {
        'timestamp': int(datetime.now().timestamp()),
        'followers': basic['followers']['totalCount'] or 0,
        'issues': basic['issues']['totalCount'] or 0,
        'organizations': basic['organizations']['totalCount'] or 0,
        'comments': (
                basic['commitComments']['totalCount'] or 0 +
                basic['gistComments']['totalCount'] or 0 +
                basic['issueComments']['totalCount'] or 0 +
                basic['repositoryDiscussionComments']['totalCount'] or 0
        ),
        'pullRequestReviews': basic['contributionsCollection']['totalPullRequestReviewContributions'] or 0,
        'commits': basic['contributionsCollection']['totalCommitContributions' or 0],
        'repos': {
            'count': 0,
            'issues': 0,
            'stars': 0,
            'forks': 0,
            'watches': 0,
            'pullRequests': 0,
            'releases': 0,
            'diskUsage': 0
        },
        'prs': {
            'total': 0,
            'merged': 0,
            'open': 0,
            'commits': 0,
            'additions': 0,
            'deletions': 0
        },
        'languages': {}
    }

    for repo in repos:  # go through all repositories and increment values accordingly
        # skip repositories viewer doesn't own or that are forks
        if repo['viewerPermission'] != "ADMIN" or repo['isFork']:
            continue

        stats['repos']['count'] += 1
        stats['repos']['issues'] += repo['issues']['totalCount'] or 0
        stats['repos']['stars'] += repo['stargazers']['totalCount'] or 0
        stats['repos']['forks'] += repo['forks']['totalCount'] or 0
        stats['repos']['watches'] += repo['watchers']['totalCount'] or 0
        stats['repos']['pullRequests'] += repo['pullRequests']['totalCount'] or 0
        stats['repos']['releases'] += repo['releases']['totalCount'] or 0
        stats['repos']['diskUsage'] += repo['diskUsage'] or 0

        for language in repo['languages']['edges']:
            name = language['node']['name']
            stats['languages'].setdefault(name, 0)
            stats['languages'][name] += language['size']

    for pr in prs:  # go through all pull requests and increment values accordingly
        stats['prs']['total'] += 1
        if pr['state'] == "OPEN":
            stats['prs']['open'] += 1
        elif pr['state'] == "MERGED":
            stats['prs']['merged'] += 1
            stats['prs']['commits'] += pr['commits']['totalCount']
            stats['prs']['additions'] += pr['additions']
            stats['prs']['deletions'] += pr['deletions']

    for gist in gists:  # go through all gists and increment values accordingly
        stats['repos']['stars'] += gist['stargazers']['totalCount']
        stats['repos']['forks'] += gist['forks']['totalCount']
        for file in gist['files']:
            stats['repos']['diskUsage'] += file['size']

            lang_name = file['language']['name']
            stats['languages'].setdefault(lang_name, 0)
            stats['languages'][lang_name] += file['size']

    # save data
    with open("./github-stats.json", "w+") as fp:
        json.dump(stats, fp, sort_keys=True, ensure_ascii=True)


async def cloudflare():
    token = getenv("CF_TOKEN")
    account = getenv("CF_ACCOUNT")
    api = Api("https://api.cloudflare.com/client/v4/graphql", {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    })
    stats = {
        'unique': 0,
        'requests': 0
    }

    # fetch and parse

    for delta in range(30):
        date = (datetime.now().date() - timedelta(days=delta)).isoformat()
        resp = await api.query("cloudflare/http", account=f'"{account}"', date=f'"{date}"')
        res = traverse_object(resp, "data>viewer>accounts>[0]>httpRequests1dGroups")
        if not res:
            break
        for entry in res:
            stats['unique'] += entry['uniq']['uniques'] or 0
            stats['requests'] += entry['sum']['requests'] or 0

    # save
    with open("./cloudflare-stats.json", "w+") as fp:
        json.dump(stats, fp, sort_keys=True, ensure_ascii=True)


async def main():
    return await asyncio.gather(github(), cloudflare(), return_exceptions=True)

if __name__ == '__main__':
    res = asyncio.run(main())
    errors = [ex for ex in res if isinstance(ex, Exception)]
    if errors:
        for error in errors:
            print(error, file=stderr)
        raise SystemExit(1)
