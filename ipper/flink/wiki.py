import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from bs4 import BeautifulSoup
from bs4.element import Tag

from ipper.common.constants import NOT_SET_STR, UNKNOWN_STR, IPState
from ipper.common.jira import JiraStatus, get_apache_jira_status
from ipper.common.wiki import (
    APACHE_CONFLUENCE_BASE_URL,
    child_page_generator,
    get_wiki_page_info,
)

logger = logging.getLogger(__name__)

FLIP_PATTERN: re.Pattern = re.compile(r"FLIP-(?P<flip>\d+)", re.IGNORECASE)
FLINK_JIRA_PATTERN: re.Pattern = re.compile(r"FLINK-\d+")
RELEASE_NUMBER_PATTERN: re.Pattern = re.compile(r"(\d+\.?\d*\.?\d*)")

TEMPLATE_BOILER_PLATE_PREFIX = "here (<-"

DISCUSSION_THREAD_KEY = "discussion_thread"
VOTE_THREAD_KEY = "vote_thread"
JIRA_ID_KEY = "jira_id"
JIRA_LINK_KEY = "jira_link"
RELEASE_COMPONENT_KEY = "release_component"
RELEASE_VERSION_KEY = "release_version"
FLINK_COMPONENT_STR = "Flink"


def get_flip_main_page_info(timeout: int = 30) -> dict[str, Any]:
    """Gets the details of the main KIP page"""

    return get_wiki_page_info(
        space_key="FLINK",
        page_title="Flink Improvement Proposals",
        timeout=timeout,
    )


def _find_Jira_key_and_link(row_data: Tag) -> tuple[str | None, str | None]:

    jira_div = row_data.find("div", {"class": "content-wrapper"})

    if jira_div:
        jira_span = cast(Tag, jira_div).find(
            "span",
            {"class": "jira-issue conf-macro output-block"},
        )
    else:
        return None, None

    if jira_span:
        if cast(Tag, jira_span).has_attr("data-jira-key"):
            jira_id_values: list[str] | str | None = cast(Tag, jira_span).get(
                "data-jira-key"
            )
            if isinstance(jira_id_values, list):
                jira_id = jira_id_values[0]
            else:
                jira_id = cast(str, jira_id_values)
        else:
            jira_id = None

        link = jira_span.find("a")
        if link and cast(Tag, link).has_attr("href"):
            jira_link_values: list[str] | str | None = cast(Tag, link).get("href")
            if isinstance(jira_link_values, list):
                jira_link = jira_link_values[0]
            else:
                jira_link = cast(str, jira_link_values)
        else:
            jira_link = None

        return jira_id, jira_link

    return None, None


def _add_row_data(
    header: str, row_data: Tag, flip_dict: dict[str, str | int | list[str]]
) -> None:

    if "discussion" in header:
        if TEMPLATE_BOILER_PLATE_PREFIX in row_data.text:
            flip_dict[DISCUSSION_THREAD_KEY] = NOT_SET_STR
            return

        link = row_data.find("a")
        if link and isinstance(link, Tag):
            href = link.get("href")
            flip_dict[DISCUSSION_THREAD_KEY] = href if href else NOT_SET_STR
        else:
            flip_dict[DISCUSSION_THREAD_KEY] = NOT_SET_STR

        return

    if "vote" in header:
        if TEMPLATE_BOILER_PLATE_PREFIX in row_data.text:
            flip_dict[VOTE_THREAD_KEY] = NOT_SET_STR
            return

        link = row_data.find("a")
        if link and isinstance(link, Tag):
            href = link.get("href")
            flip_dict[VOTE_THREAD_KEY] = href if href else NOT_SET_STR
        else:
            flip_dict[VOTE_THREAD_KEY] = NOT_SET_STR

        return

    if "jira" in header:
        if TEMPLATE_BOILER_PLATE_PREFIX in row_data.text:
            flip_dict[JIRA_ID_KEY] = NOT_SET_STR
            flip_dict[JIRA_LINK_KEY] = NOT_SET_STR
            return

        jira_id, jira_link = _find_Jira_key_and_link(row_data)

        if jira_id:
            flip_dict[JIRA_ID_KEY] = jira_id
        else:
            flip_dict[JIRA_ID_KEY] = NOT_SET_STR

        if jira_link:
            flip_dict[JIRA_LINK_KEY] = jira_link
        else:
            flip_dict[JIRA_LINK_KEY] = NOT_SET_STR

        return

    if "release" in header:
        component, version = _get_release_version(row_data.text)

        logger.debug("\tTarget Release:")
        logger.debug("\t\tComponent:\t\t%s", component)
        logger.debug("\t\tVersion:\t\t%s", version)

        if component:
            flip_dict[RELEASE_COMPONENT_KEY] = component
        else:
            flip_dict[RELEASE_COMPONENT_KEY] = NOT_SET_STR

        flip_dict[RELEASE_VERSION_KEY] = version


def _get_release_version(release_row_text) -> tuple[str | None, str]:
    """Returns the component (Flink by default) and version the release row refers to."""

    release_split = RELEASE_NUMBER_PATTERN.split(release_row_text.strip())

    if len(release_split) < 2:
        # There was no match
        return None, NOT_SET_STR

    component = FLINK_COMPONENT_STR

    if release_split[0]:
        component = release_split[0].strip(r"[-_]")

    if len(release_split) == 3:
        version = release_split[1]
    else:
        # We have more than 1 version numbers in the release text so we join them together
        version = ", ".join(
            sorted(RELEASE_NUMBER_PATTERN.findall(release_row_text.strip()))
        )

    return component, version


def check_if_set(flip_dict, key):

    if key not in flip_dict:
        return False

    return bool(flip_dict[key] != UNKNOWN_STR and flip_dict[key] != NOT_SET_STR)


def _determine_state(flip_dict) -> IPState:

    has_discussion_thread = check_if_set(flip_dict, DISCUSSION_THREAD_KEY)
    has_vote_thread = check_if_set(flip_dict, VOTE_THREAD_KEY)
    has_jira = check_if_set(flip_dict, JIRA_LINK_KEY)
    has_target_release = check_if_set(flip_dict, RELEASE_VERSION_KEY)

    logger.debug("\tDetermining state:")
    logger.debug("\t\tDiscussion Thread:\t%s", has_discussion_thread)
    logger.debug("\t\tVote Thread:\t\t%s", has_vote_thread)
    logger.debug("\t\tJIRA:\t\t\t%s", has_jira)
    logger.debug("\t\tTarget Release:\t\t%s", has_target_release)

    if has_discussion_thread and not has_jira and not has_target_release:
        logger.debug("\t\tFLIP State:\t\t%s", IPState.UNDER_DISCUSSION)
        return IPState.UNDER_DISCUSSION

    if has_jira:
        jira_id_match: re.Match | None = FLINK_JIRA_PATTERN.search(
            flip_dict[JIRA_LINK_KEY]
        )
        if jira_id_match:
            jira_id = jira_id_match.group()
        else:
            logger.warning(
                "Could not find JIRA ID from url: %s", flip_dict[JIRA_LINK_KEY]
            )
            logger.debug("\t\tFLIP State:\t\t%s", IPState.UNKNOWN)
            return IPState.UNKNOWN

        jira_state: JiraStatus = get_apache_jira_status(jira_id)
        logger.debug("\t\tJIRA State:\t\t%s", jira_state)

        if jira_state == JiraStatus.RESOLVED:
            logger.debug("\t\tFLIP State:\t\t%s", IPState.COMPLETED)
            return IPState.COMPLETED

        if jira_state == JiraStatus.CLOSED:
            if has_target_release:
                logger.debug("\t\tFLIP State:\t\t%s", IPState.COMPLETED)
                return IPState.COMPLETED

            logger.debug("\t\tFLIP State:\t\t%s", IPState.NOT_ACCEPTED)
            return IPState.NOT_ACCEPTED

        if jira_state in (JiraStatus.OPEN, JiraStatus.IN_PROGRESS):
            logger.debug("\t\tFLIP State:\t\t%s", IPState.IN_PROGRESS)
            return IPState.IN_PROGRESS

    return IPState.UNKNOWN


def _enrich_flip_info(
    flip_id: int, body_html: str, flip_dict: dict[str, str | int | list[str]]
) -> None:
    """Parses the body of the FLIP wiki page pointed to by the 'content_url'
    key in the supplied dictionary. It will add the derived data to the
    supplied dict.

    Search process:
        1. Find the first table in the body (some flips don't have a table and will be ignored)
        2. Identify if there is a Discussion Thread, Vote Thread, JIRA or Release entry.
           Add the details to the flip_dict.
        3. If there is a release, set the status as RELEASED.
        4.
    """

    parsed_body: BeautifulSoup = BeautifulSoup(body_html, "html.parser")

    tables = parsed_body.find_all("table")

    # Setup the status entries to default unknown
    flip_dict[DISCUSSION_THREAD_KEY] = UNKNOWN_STR
    flip_dict[VOTE_THREAD_KEY] = UNKNOWN_STR
    flip_dict[RELEASE_COMPONENT_KEY] = UNKNOWN_STR
    flip_dict[RELEASE_VERSION_KEY] = UNKNOWN_STR
    flip_dict["state"] = IPState.UNKNOWN

    if not tables:
        logger.warning(
            "No summary table in FLIP-%s. This FLIP state will be set to %s.",
            flip_id,
            UNKNOWN_STR,
        )
        return

    # We assume that the first table on the page is the summary table
    summary_table = tables[0]
    summary_rows = summary_table.findAll("tr")
    if not summary_rows:
        logger.warning(
            "No information in summary table in FLIP-%s. "
            "This FLIP state will be set to %s.",
            flip_id,
            UNKNOWN_STR,
        )
        return

    for row in summary_rows:
        header_tag = row.find("th")
        if header_tag:
            header = header_tag.text.lower()
        else:
            # We have no idea what this row is
            continue

        row_data = row.find("td")
        if row_data:
            _add_row_data(header, row_data, flip_dict)

    flip_dict["state"] = _determine_state(flip_dict)


def process_child_kip(flip_id: int, child: dict):
    """Process and enrich the KIP child page dictionary"""

    logger.info("Processing FLIP %s wiki page", flip_id)
    child_dict: dict[str, int | str | list[str]] = {}
    child_dict["id"] = flip_id
    child_dict["title"] = child["title"]
    child_dict["web_url"] = APACHE_CONFLUENCE_BASE_URL + child["_links"]["webui"]
    child_dict["content_url"] = child["_links"]["self"]
    child_dict["created_on"] = child["history"]["createdDate"]
    child_dict["created_by"] = child["history"]["createdBy"]["displayName"]
    child_dict["last_modified_on"] = child["history"]["lastUpdated"]["when"]
    child_dict["last_modified_by"] = child["history"]["lastUpdated"]["by"][
        "displayName"
    ]
    _enrich_flip_info(flip_id, child["body"]["view"]["value"], child_dict)

    return child_dict


def get_flip_information(
    flip_main_info,
    chunk: int = 100,
    timeout: int = 30,
    existing_cache: dict | None = None,
    refresh_days: int = 30,
):

    output = existing_cache if existing_cache else {}

    # Calculate refresh cutoff date
    refresh_cutoff = datetime.now(UTC) - timedelta(days=refresh_days)

    if existing_cache:
        logger.info(
            "Updating FLIP Wiki information with new FLIPs and refreshing FLIPs "
            "created within %s days",
            refresh_days,
        )
    else:
        logger.info("Downloading FLIP Wiki information for all FLIPs")

    for child in child_page_generator(flip_main_info, chunk, timeout):
        flip_match: re.Match | None = re.search(FLIP_PATTERN, child["title"])
        if flip_match:
            flip_id: int = int(flip_match.groupdict()["flip"])

            # Check if FLIP already exists in cache
            if flip_id in output:
                # Parse the created_on date from the cached FLIP
                try:
                    created_on_str = output[flip_id]["created_on"]
                    # Handle ISO format with 'Z' or timezone info
                    created_date = datetime.fromisoformat(
                        created_on_str.replace("Z", "+00:00")
                    )

                    # Skip if FLIP was created outside the refresh window
                    if created_date < refresh_cutoff:
                        logger.info(
                            "Skipping FLIP-%s (created %s, outside %s-day "
                            "refresh window)",
                            flip_id,
                            created_on_str,
                            refresh_days,
                        )
                        continue
                    else:
                        logger.info(
                            "Refreshing FLIP-%s (created recently: %s)",
                            flip_id,
                            created_on_str,
                        )
                except (KeyError, ValueError) as e:
                    logger.warning(
                        "Could not parse created_on date for FLIP-%s, "
                        "refreshing anyway: %s",
                        flip_id,
                        e,
                    )

            output[flip_id] = process_child_kip(flip_id, child)

            if flip_id not in (existing_cache or {}):
                logger.info("Added new FLIP-%s to cache", flip_id)

    return output
