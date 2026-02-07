from collections.abc import Generator
from typing import Any

import requests

APACHE_CONFLUENCE_BASE_URL: str = "https://wiki.apache.org/confluence"
APACHE_CONFLUENCE_DATE_FORMAT: str = "%Y-%m-%dT%H:%M:%S.000Z"
CONTENT_URL: str = APACHE_CONFLUENCE_BASE_URL + "/rest/api/content"


def get_wiki_page_info(
    space_key: str, page_title: str, timeout: int = 30
) -> dict[str, Any]:
    """Gets the details of the main KIP page"""

    wiki_request: requests.Response = requests.get(
        CONTENT_URL,
        params={
            "type": "page",
            "spaceKey": space_key,
            "title": page_title,
        },
        timeout=timeout,
    )

    wiki_request.raise_for_status()

    results: list[dict[str, Any]] = wiki_request.json()["results"]

    if len(results) == 0:
        raise RuntimeError(
            f"No results found for page {page_title} in space {space_key}"
        )

    if len(results) > 1:
        raise RuntimeError(
            f"More than 1 main page found with title {page_title} in space {space_key}: {results}"
        )

    return results[0]


def get_wiki_page_body(wiki_page_info: dict[str, Any], timeout: int = 30) -> str:
    """Gets the RAW HTML body of the wiki page using information in the
    supplied wiki page info dict."""

    wiki_body_request: requests.Response = requests.get(
        CONTENT_URL + "/" + wiki_page_info["id"],
        params={"expand": "body.view"},
        timeout=timeout,
    )

    wiki_body_request.raise_for_status()

    return wiki_body_request.json()["body"]["view"]["value"]


def child_page_generator(
    wiki_page_info, chunk: int, timeout: int
) -> Generator[dict, None, None]:
    """Generator function which will yield the child info dict of each child page of the
    supplied wiki page"""

    wiki_page_child_info_request: requests.Response = requests.get(
        APACHE_CONFLUENCE_BASE_URL + wiki_page_info["_expandable"]["children"],
        timeout=timeout,
    )

    wiki_page_child_info_request.raise_for_status()

    first_child_request: requests.Response = requests.get(
        APACHE_CONFLUENCE_BASE_URL
        + wiki_page_child_info_request.json()["_expandable"]["page"],
        params={
            "limit": str(chunk),
            "expand": "history.lastUpdated,body.view",
        },
        timeout=timeout,
    )

    first_child_request.raise_for_status()

    response_json = first_child_request.json()
    more_results: bool = True

    while more_results:
        yield from response_json["results"]

        if "next" in response_json["_links"]:
            kip_child_response: requests.Response = requests.get(
                APACHE_CONFLUENCE_BASE_URL + response_json["_links"]["next"],
                timeout=timeout,
            )
            kip_child_response.raise_for_status()
            response_json = kip_child_response.json()
            more_results = True
        else:
            more_results = False
