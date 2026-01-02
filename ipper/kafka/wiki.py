import re
import json
from typing import Any, Optional, Union, cast
from pathlib import Path

from bs4 import BeautifulSoup
from bs4.element import Tag

from ipper.common.wiki import (
    APACHE_CONFLUENCE_BASE_URL,
    get_wiki_page_info,
    get_wiki_page_body,
    child_page_generator,
)
from ipper.common.constants import IPState, UNKNOWN_STR

KIP_PATTERN: re.Pattern = re.compile(r"KIP-(?P<kip>\d+)", re.IGNORECASE)
ACCEPTED_TERMS: list[str] = [
    "accepted",
    "approved",
    "adopted",
    "adopt",
    "implemented",
    "committed",
    "completed",
    "merged",
    "released",
    "accept",
    "vote passed",
]
UNDER_DISCUSSION_TERMS: list[str] = [
    "discussion",
    "discuss",
    "discusion",
    "voting",
    "under vote",
    "draft",
    "wip",
    "under review",
]
NOT_ACCEPTED_TERMS: list[str] = [
    "rejected",
    "discarded",
    "superseded",
    "subsumed",
    "withdrawn",
    "cancelled",
    "abandoned",
    "replaced",
    "moved to",
]


def get_kip_main_page_info(timeout: int = 30) -> dict[str, Any]:
    """Gets the details of the main KIP page"""

    return get_wiki_page_info(
        space_key="KAFKA",
        page_title="Kafka Improvement Proposals",
        timeout=timeout,
    )


def get_kip_main_page_body(kip_main_info: dict[str, Any], timeout: int = 30) -> str:
    """Gets the RAW HTML body of the KIP main page"""

    return get_wiki_page_body(kip_main_info, timeout=timeout)


def get_current_state(html: str) -> Optional[str]:
    """Discerns the state of the kip from the supplied current state html paragraph"""

    if any(option in html.lower() for option in ACCEPTED_TERMS):
        return IPState.ACCEPTED

    if any(option in html.lower() for option in UNDER_DISCUSSION_TERMS):
        return IPState.UNDER_DISCUSSION

    if any(option in html.lower() for option in NOT_ACCEPTED_TERMS):
        return IPState.NOT_ACCEPTED

    return None


def enrich_kip_info(body_html: str, kip_dict: dict[str, Union[list[str], str, int]]) -> None:
    """Parses the body of the KIP wiki page pointed to by the 'content_url'
    key in the supplied dictionary. It will add the derived data to the
    supplied dict."""

    parsed_body: BeautifulSoup = BeautifulSoup(body_html, "html.parser")

    state_processed: bool = False
    jira_processed: bool = False
    discussion_processed: bool = False
    vote_processed: bool = False

    for para in parsed_body.find_all("p"):

        if not state_processed and "current state" in para.text.lower():
            state: Optional[str] = get_current_state(para.text)
            if state:
                kip_dict["state"] = state
            else:
                print(f"Could not discern KIP state from {para}")
                kip_dict["state"] = IPState.UNKNOWN

            state_processed = True

        elif not jira_processed and "jira" in para.text.lower():
            link: Tag = para.find("a")
            if link:
                href: Optional[Union[list, str]] = link.get("href")
            else:
                href = None

            if href:
                kip_dict["jira"] = href
            else:
                print(f"Could not discern JIRA link from {para}")
                kip_dict["jira"] = UNKNOWN_STR

            jira_processed = True

        elif not discussion_processed and "discussion thread" in para.text.lower():
            link: Tag = para.find("a")
            if link:
                href: Optional[Union[list, str]] = link.get("href")
            else:
                href = None

            if href:
                kip_dict["discussion_thread"] = href
            else:
                print(f"Could not discern discussion thread link from {para}")
                kip_dict["discussion_thread"] = UNKNOWN_STR

            discussion_processed = True

        elif not vote_processed and "voting thread" in para.text.lower():
            link: Tag = para.find("a")
            if link:
                href: Optional[Union[list, str]] = link.get("href")
            else:
                href = None

            if href:
                kip_dict["vote_thread"] = href
            else:
                print(f"Could not discern voting thread link from {para}")
                kip_dict["vote_thread"] = UNKNOWN_STR

            vote_processed = True

    if not state_processed:
        kip_dict["state"] = UNKNOWN_STR

    if not jira_processed:
        kip_dict["jira"] = UNKNOWN_STR

    if not discussion_processed:
        kip_dict["discussion_thread"] = UNKNOWN_STR

    if not vote_processed:
        kip_dict["vote_thread"] = UNKNOWN_STR


def process_child_kip(kip_id: int, child: dict):
    """Process and enrich the KIP child page dictionary"""

    print(f"Processing KIP {kip_id} wiki page")
    child_dict: dict[str, Union[list[str], str, int]] = {}
    child_dict["kip_id"] = kip_id
    child_dict["title"] = child["title"]
    child_dict["web_url"] = APACHE_CONFLUENCE_BASE_URL + child["_links"]["webui"]
    child_dict["content_url"] = child["_links"]["self"]
    child_dict["created_on"] = child["history"]["createdDate"]
    child_dict["created_by"] = child["history"]["createdBy"]["displayName"]
    child_dict["last_modified_on"] = child["history"]["lastUpdated"]["when"]
    child_dict["last_modified_by"] = child["history"]["lastUpdated"]["by"][
        "displayName"
    ]
    enrich_kip_info(child["body"]["view"]["value"], child_dict)

    return child_dict


def get_kip_information(
    kip_main_info: dict[str, Any],
    chunk: int = 100,
    update: bool = False,
    overwrite_cache: bool = False,
    cache_filepath: str = "cache/kip_wiki_cache.json",
    timeout: int = 30,
) -> dict[int, dict[str, Union[int, str]]]:
    """Gets the details of all child pages of the KIP main page that relate
    to a KIP. This takes a long time so will cache its results in a json file."""

    if update and overwrite_cache:
        update = False

    cache_file_path: Path = Path(cache_filepath)
    if cache_file_path.exists() and not overwrite_cache:
        print(f"Loading KIP Wiki information from cache file: {cache_file_path}")
        with open(cache_file_path, "r", encoding="utf8") as cache_file:
            output: dict[int, dict[str, Union[int, str]]] = {
                int(k): v for k, v in json.load(cache_file).items()
            }
        if not update:
            return output
    else:
        cache_file_path.parent.mkdir(parents=True, exist_ok=True)
        output = {}

    if cache_file_path.exists() and update:
        print("Updating KIP Wiki information with new KIPs")
    else:
        print("Downloading KIP Wiki information for all KIPS")

    for child in child_page_generator(kip_main_info, chunk, timeout):
        kip_match: Optional[re.Match] = re.search(KIP_PATTERN, child["title"])
        if kip_match:
            kip_id: int = int(kip_match.groupdict()["kip"])
            if kip_id not in output:
                output[kip_id] = process_child_kip(kip_id, child)
            # TODO: Add check of last modified versus the stored one
            # to indicate an update is needed.

    with open(cache_file_path, "w", encoding="utf8") as cache_file:
        json.dump(output, cache_file)

    return output


def get_kip_tables(kip_main_info: dict[str, Any]) -> dict[str, Tag]:
    """Gets the tables from the KIP main page.

    Returns
    -------
    dict
        A dict mapping from the table name [adopted, discussion,
        discarded, recordings] to the Table element."""

    body_html: str = get_kip_main_page_body(kip_main_info)
    parsed_body: BeautifulSoup = BeautifulSoup(body_html, "html.parser")

    tables: list[Tag] = list(parsed_body.find_all("table"))

    kip_tables: dict[str, Tag] = {
        "adopted": tables[0],
        "discussion": tables[1],
        "discarded": tables[2],
        "recordings": tables[3],
    }

    return kip_tables


def process_discussion_table(
    discussion_table: Tag, kip_child_urls: dict[int, dict[str, Union[str, int]]]
) -> dict[int, dict[str, str]]:
    """Process the KIPs under discussion table"""

    # Skip the first row as that is the header
    discussion_rows: list[Tag] = discussion_table.find_all("tr")[1:]

    output: dict[int, dict[str, str]] = {}

    for row in discussion_rows:
        kip_dict: dict[str, str] = {}
        columns: list[Tag] = row.find_all("td")

        if not columns[0].a:
            continue

        kip_text: str = columns[0].a.text
        kip_match: Optional[re.Match] = re.search(KIP_PATTERN, kip_text)

        if kip_match:
            kip_id: int = int(kip_match.groupdict()["kip"])
            kip_dict["text"] = kip_text
            kip_dict["comment"] = columns[1].text
            try:
                kip_dict["url"] = cast(str, kip_child_urls[kip_id]["web_url"])
            except KeyError:
                href: Optional[Union[list[str], str]] = columns[0].a.get("href")
                if href:
                    if isinstance(href, list):
                        kip_dict["url"] = href[0]
                    else:
                        kip_dict["url"] = href
                else:
                    kip_dict["url"] = "Unknown"
            output[kip_id] = kip_dict
        else:
            continue

    return output
