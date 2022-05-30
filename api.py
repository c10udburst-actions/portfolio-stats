import asyncio
from os import getenv

import aiohttp


class RetryException(RuntimeError):
    pass


def traverse_object(obj, key_path: str):
    for key in key_path.split(">"):
        obj = obj[key]
    return obj


class Api:
    def __init__(self, max_connections: int = 10):
        self.token = getenv("GH_TOKEN")
        if not self.token:
            raise RuntimeError("No token found.")
        self.session = aiohttp.ClientSession(headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Cache-Control": "no-cache"
        })
        self.semaphore = asyncio.Semaphore(10)

    async def _query(self, script_name: str, **kwargs):
        query = open(f"./graphql/{script_name}.graphql", "r").read()

        for key, value in kwargs.items():  # replace kwarg variables
            query = query.replace(f"${key}", value)

        async with self.semaphore:
            r = await self.session.post("https://api.github.com/graphql", json={"query": query})

        if r.status == 204 or r.status == 202:
            raise RetryException()

        result = await r.json()
        if result is None:
            raise RetryException()

        return result

    async def query(self, script_name: str, **kwargs):
        for _ in range(25):
            try:
                return await self._query(script_name, **kwargs)
            except RetryException:
                print(f"[{script_name}] Retrying...")

    async def paginated_query(self, script_name: str, key_path: str, **kwargs):
        res = traverse_object(await self.query(script_name, cursor=""), key_path)
        page_info = res['pageInfo']
        nodes = res['nodes']
        while page_info['hasNextPage']:  # if has next page, fetch it and append nodes
            res = traverse_object(await self.query(script_name,
                                                   cursor=f"after: \"{page_info['endCursor']}\"",
                                                   **kwargs),
                                  key_path)
            nodes += res['nodes']
            page_info = res['pageInfo']
        return nodes
