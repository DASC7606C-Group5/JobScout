"""Search China/Hong Kong job websites and check location and employment preferences.

These are website interfaces, not promised public developer APIs. No ranking,
cross-source deduplication, skill extraction or vacancy expiry inference here.
"""

import json
import re
from collections.abc import Generator
from dataclasses import dataclass
from html import unescape
from urllib.parse import urlencode, urljoin, urlsplit
from uuid import uuid4

from pydantic import JsonValue, TypeAdapter, ValidationError

from jobscout.schemas.search import SearchRequest
from jobscout.services.location_service import get_location_catalog, within
from jobscout.services.notice_service import make_notice

from .employment import source_employment_label
from .html_fields import Tree
from .models import RawJob, RetrievalFailure, workflow_error
from .planning import normalized, plan_keywords, validate_request
from .sources import SourceResult
from .web_transport import AsyncWebClient, WebPage

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
HOSTS = {
    "zhaopin": "jobs.zhaopin.com",
    "liepin": "www.liepin.com",
    "shixiseng": "www.shixiseng.com",
    "jobsdb": "hk.jobsdb.com",
}


def source_keywords(request: SearchRequest, source: str) -> list[str]:
    """Use the search keywords supplied by the agent."""
    return plan_keywords(request)


@dataclass(frozen=True)
class SearchPlan:
    url: str
    body: dict[str, object] | None
    headers: dict[str, str]
    keywords: tuple[str, ...]


def build_search_plan(
    request: SearchRequest, source: str, page: int = 1, page_size: int = 10
) -> SearchPlan:
    validate_request(request)
    if source not in HOSTS:
        raise RetrievalFailure("SEARCH_UNKNOWN_SOURCE", "Unknown source.")
    if not 1 <= page <= 5 or not 1 <= page_size <= 50:
        raise RetrievalFailure("SEARCH_INPUT", "Invalid page bounds.")
    ref = request.location_ref
    if not request.location_unrestricted and ref is None:
        raise RetrievalFailure(
            "SEARCH_LOCATION_UNSUPPORTED", "A resolved directory location is required."
        )
    region = ref.region if ref else None
    if not request.location_unrestricted and region != ("hk" if source == "jobsdb" else "cn"):
        raise RetrievalFailure(
            "SEARCH_REGION_UNSUPPORTED", "Source does not cover the requested region."
        )
    catalog = get_location_catalog()
    city_ref = catalog.city(ref) if ref else None
    city = city_ref.name if city_ref and city_ref.level != "country" else None
    if (
        source in {"zhaopin", "liepin"}
        and ref
        and ref.level != "country"
        and source not in ref.source_codes
    ):
        raise RetrievalFailure(
            "SEARCH_LOCATION_UNSUPPORTED",
            "No verified search parameter is available for this location on the source website.",
        )
    if (
        source == "shixiseng"
        and not request.employment_type_unrestricted
        and normalized(request.employment_type) != "internship"
    ):
        raise RetrievalFailure(
            "SEARCH_FILTER_UNSUPPORTED", "This Shixiseng adapter covers internships only."
        )
    words = source_keywords(request, source)
    keyword = " ".join(words)
    if normalized(request.employment_type) == "internship" and source != "shixiseng":
        keyword += " intern" if source == "jobsdb" else " 实习"
    headers = {"Referer": f"https://{HOSTS[source]}/"}
    body: dict[str, object] | None = None
    if source == "zhaopin":
        url = "https://fe-api.zhaopin.com/c/i/search/positions"
        headers.update(
            {
                "Origin": "https://www.zhaopin.com",
                "Referer": "https://www.zhaopin.com/",
                "x-zp-page-code": "4019",
                "x-zp-platform": "13",
                "x-zp-business-system": "1",
            }
        )
        body = {
            "S_SOU_FULL_INDEX": keyword,
            "S_SOU_WORK_CITY": ref.source_codes["zhaopin"] if ref else "489",
            "order": 0,
            "sortType": "DEFAULT",
            "pageIndex": page,
            "pageSize": page_size,
            "anonymous": 1,
            "eventScenario": "pcSearchedSouSearch",
            "platform": 13,
            "version": "0.0.0",
        }
    elif source == "liepin":
        url = "https://api-c.liepin.com/api/com.liepin.searchfront4c.pc-search-job"
        headers.update(
            {
                "Origin": "https://www.liepin.com",
                "X-Client-Type": "web",
                "X-Fscp-Version": "1.1",
                "X-Requested-With": "XMLHttpRequest",
                "X-Fscp-Std-Info": '{"client_id":"40108"}',
                "X-Fscp-Trace-Id": str(uuid4()),
            }
        )
        code = ref.source_codes.get("liepin", "") if ref else ""
        body = {
            "data": {
                "mainSearchPcConditionForm": {
                    "city": code,
                    "dq": code,
                    "pubTime": "",
                    "currentPage": page - 1,
                    "pageSize": page_size,
                    "key": keyword,
                    "suggestTag": "",
                    "workYearCode": "0",
                    "compId": "",
                    "compName": "",
                    "compTag": "",
                    "industry": "",
                    "salary": "",
                    "jobKind": "",
                    "compScale": "",
                    "compKind": "",
                    "compStage": "",
                    "eduLevel": "",
                },
                "passThroughForm": {"scene": "init", "skeyword": keyword, "sfrom": "search_job_pc"},
            }
        }
    elif source == "jobsdb":
        where = (
            "Hong Kong"
            if request.location_unrestricted or (ref and ref.level == "country")
            else request.location
        )
        params: dict[str, str | int | None] = {
            "siteKey": "HK-Main",
            "where": where,
            "keywords": keyword,
            "page": page,
            "pageSize": page_size,
            "sourcesystem": "houston",
            "locale": "en-HK",
        }
        # Work-type IDs documented by the website; internship is not part-time.
        worktype = {"full time": "242", "part time": "243", "contract": "244"}.get(
            normalized(request.employment_type)
        )
        if worktype:
            params["worktype"] = worktype
        url = "https://hk.jobsdb.com/api/jobsearch/v5/search?" + urlencode(params)
    else:
        url = "https://www.shixiseng.com/interns?" + urlencode(
            {"keyword": keyword, "city": city or "全国", "page": page}
        )
    return SearchPlan(url, body, headers, tuple(words))


def obj(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def at(record: dict[str, JsonValue], *path: str) -> JsonValue:
    value: JsonValue = record
    for key in path:
        value = obj(value).get(key)
    return value


def string(value: JsonValue) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def clean_field(value: str | None) -> str | None:
    # Font-obfuscated values are unknown; never manufacture decoded salaries.
    value = unescape(value) if value else value
    return None if value and any(0xE000 <= ord(c) <= 0xF8FF for c in value) else value


def decode_json(page: WebPage) -> dict[str, JsonValue]:
    try:
        return JSON_OBJECT.validate_json(page.text)
    except ValidationError as exc:
        raise RetrievalFailure(
            "SEARCH_RESPONSE_FORMAT",
            "Expected source JSON object; received malformed data or an interstitial.",
        ) from exc


def parse_listing(source: str, page: WebPage) -> list[dict[str, JsonValue]]:
    if (
        page.text.lstrip().startswith("<")
        and "intern-wrap" not in page.text
        and re.search(
            r"captcha|verify you are human|access denied|安全验证|安全驗證|访问受限",
            page.text,
            re.I,
        )
    ):
        raise RetrievalFailure("SEARCH_AUTH", "Source requires verification; not an empty result.")
    if source == "shixiseng":
        tree = Tree(page.text).root
        cards = tree.find(attr="class", value="intern-wrap")
        if not cards and not any(
            s in tree.text() for s in ("暂无相关职位", "暂无搜索结果", "没有找到", "暂无职位")
        ):
            raise RetrievalFailure(
                "SEARCH_RESPONSE_FORMAT",
                "Shixiseng listing markers missing; cannot confirm an empty result.",
            )
        records: list[dict[str, JsonValue]] = []
        for card in cards:
            links = [n for n in card.find(tag="a") if "/intern/" in n.attrs.get("href", "")]
            if not links:
                records.append({})
                continue
            companies = card.find(attr="class", value="intern-detail__company")
            company = companies[0].field("class", "title") if companies else None
            records.append(
                {
                    "id": card.attrs.get("data-intern-id"),
                    "url": links[0].attrs["href"],
                    "title": clean_field(links[0].attrs.get("title") or links[0].text()),
                    "location": card.field("class", "city"),
                    "company": clean_field(company),
                    "salary": clean_field(card.field("class", "day")),
                    "listing_text": card.text(),
                    "employment_type": "internship",
                }
            )
        return records
    data = decode_json(page)
    if source == "zhaopin" and at(data, "data", "isVerification") not in (None, 0, "0", False):
        raise RetrievalFailure("SEARCH_AUTH", "Source requires verification; not an empty result.")
    code = data.get("code") if source == "zhaopin" else data.get("flag")
    if source != "jobsdb" and code != (200 if source == "zhaopin" else 1):
        error = (
            "SEARCH_RATE_LIMIT"
            if code == 429
            else "SEARCH_AUTH"
            if code in (401, 403)
            else "SEARCH_SOURCE_REJECTED"
        )
        raise RetrievalFailure(
            error, "Source business status rejected the query; not an empty result."
        )
    value = (
        at(data, "data", "list")
        if source == "zhaopin"
        else at(data, "data", "data", "jobCardList")
        if source == "liepin"
        else data.get("data")
    )
    if not isinstance(value, list):
        raise RetrievalFailure("SEARCH_RESPONSE_FORMAT", "Expected source jobs array.")
    # Malformed individual records are dealt with separately by the adapter.
    return [r if isinstance(r, dict) else {} for r in value]


def map_listing(source: str, record: dict[str, JsonValue], page: WebPage, direction: str) -> RawJob:
    if not record:
        raise RetrievalFailure("SEARCH_RESPONSE_FORMAT", "Invalid empty job record.")
    if source == "zhaopin":
        data = {
            "source_job_id": record.get("jobId"),
            "title": record.get("name"),
            "company": record.get("companyName"),
            "location": record.get("workCity"),
            "salary": record.get("salary60"),
            "source_url": record.get("positionURL") or record.get("positionUrl"),
            "posted_at": record.get("publishTime"),
            "description": at(record, "jobDetailData", "position", "desc", "description"),
            "expiry_at": at(record, "jobDetailData", "position", "date", "dateEnd"),
        }
    elif source == "liepin":
        data = {
            "source_job_id": at(record, "job", "jobId"),
            "title": at(record, "job", "title"),
            "company": at(record, "comp", "compName"),
            "location": at(record, "job", "dq"),
            "salary": at(record, "job", "salary"),
            "source_url": at(record, "job", "link"),
            "posted_at": at(record, "job", "refreshTime"),
        }
    elif source == "jobsdb":
        places = record.get("locations")
        labels = [string(obj(p).get("label")) for p in places] if isinstance(places, list) else []
        identifier = record.get("id")
        data = {
            "source_job_id": identifier,
            "title": record.get("title"),
            "company": at(record, "advertiser", "description"),
            "location": ", ".join(s for s in labels if s) or None,
            "salary": record.get("salaryLabel") or record.get("salary"),
            "source_url": f"https://hk.jobsdb.com/job/{identifier}"
            if identifier is not None
            else None,
            "posted_at": record.get("listingDate"),
            "description": record.get("teaser"),
        }
    else:
        data = {
            "source_job_id": record.get("id"),
            "title": record.get("title"),
            "location": record.get("location"),
            "company": record.get("company"),
            "salary": record.get("salary"),
            "source_url": record.get("url"),
        }
    if isinstance(data.get("source_job_id"), bool):
        raise RetrievalFailure("SEARCH_RESPONSE_FORMAT", "Invalid boolean job ID.")
    if isinstance(data.get("source_job_id"), (int, str)):
        data["source_job_id"] = str(data["source_job_id"])
    # Enough source data for Group 5 without unrelated recruiter profiles.
    payload = {
        k: v
        for k, v in record.items()
        if k
        not in {
            "staffCard",
            "recruiter",
            "qrUrl",
            "dataParams",
            "dataInfo",
            "tracking",
            "solMetadata",
        }
    }
    try:
        return RawJob.model_validate(
            {
                "source": source,
                "fetched_at": page.fetched_at,
                "target_direction": direction,
                "raw_payload": payload,
                **{k: None if v == "" else v for k, v in data.items()},
            }
        )
    except ValidationError as exc:
        raise RetrievalFailure(
            "SEARCH_RESPONSE_FORMAT", "Unexpected source job field types."
        ) from exc


def detail_url(job: RawJob) -> str | None:
    if not job.source_url:
        return None
    try:
        parts = urlsplit(urljoin(f"https://{HOSTS[job.source]}", job.source_url))
        valid = (
            parts.hostname == HOSTS[job.source]
            and parts.scheme in {"http", "https"}
            and not parts.username
            and not parts.password
            and parts.port in {None, 80, 443}
        )
    except ValueError:
        valid = False
    if not valid:
        raise RetrievalFailure("SEARCH_RESPONSE_FORMAT", "Unexpected job detail host.")
    return "https://" + parts.netloc + parts.path


def add_detail(job: RawJob, page: WebPage) -> None:
    if job.description:
        job.raw_payload.setdefault("listing_description", job.description)
        job.raw_payload.setdefault("listing_fetched_at", job.fetched_at.isoformat())
    tree = Tree(page.text).root
    structured_description: str | None = None
    for node in tree.find(tag="script", attr="type", value="application/ld+json"):
        try:
            source_json = "".join(child for child in node.children if isinstance(child, str))
            structured = JSON_OBJECT.validate_python(json.loads(source_json, strict=False))
        except ValueError, ValidationError:
            continue
        if structured.get("@type") != "JobPosting":
            continue
        job.raw_payload["detail_structured"] = structured
        structured_description = string(structured.get("description"))
        job.posted_at = string(structured.get("datePosted")) or job.posted_at
        job.expiry_at = string(structured.get("validThrough")) or job.expiry_at
        address = obj(at(structured, "jobLocation", "address"))
        location = ", ".join(
            value
            for key in ("addressLocality", "addressRegion", "addressCountry")
            if (value := string(address.get(key)))
        )
        job.location = location or job.location
        job.employment_type = observed_employment_type(job) or job.employment_type
    if job.source == "jobsdb":
        description = tree.field("data-automation", "jobAdDetails")
    elif job.source == "liepin":
        description = tree.field("data-selector", "job-intro-content")
    else:
        description = tree.field("class", "job_detail")
        headings = tree.find(tag="h1")
        job.title = clean_field(tree.field("class", "new_job_name")) or job.title
        if headings:
            job.title = clean_field(headings[0].text()) or job.title
        job.location = clean_field(tree.field("class", "job_position")) or job.location
        # Source labels delimit these values; no numeric/font guessing.
        text = tree.text()
        job.salary = clean_field(tree.field("class", "job_money"))
        posted = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*刷新", text)
        expiry = re.search(r"截止日期[：:]\s*(\d{4}-\d{2}-\d{2})", text)
        job.posted_at = posted.group(1) if posted else job.posted_at
        job.expiry_at = expiry.group(1) if expiry else job.expiry_at
        companies = [
            n for n in tree.find(tag="a") if "/com/" in n.attrs.get("href", "") and n.text()
        ]
        job.company = (
            clean_field(tree.field("class", "com-name"))
            or (clean_field(companies[0].text()) if companies else None)
            or job.company
        )
    description = clean_field(description)
    description = description or structured_description
    if not description:
        raise RetrievalFailure(
            "SEARCH_RESPONSE_FORMAT",
            "Job description marker missing; detail may be unavailable or changed.",
        )
    job.description = description
    job.raw_payload["detail_description"] = description
    job.raw_payload["detail_fetched_at"] = page.fetched_at.isoformat()


def passes_location(job: RawJob, request: SearchRequest) -> bool:
    if job.source == "jobsdb":
        places = job.raw_payload.get("locations")
        if isinstance(places, list) and any(
            at(obj(place), "countryCode") not in {None, "HK"} for place in places
        ):
            return False
    if request.location_unrestricted or request.location_ref is None:
        return True
    actual = get_location_catalog().find(job.location or "")
    # An unresolved location is assessed later using the original job details.
    if len(actual) != 1:
        return True
    wanted = request.location_ref
    return within(actual[0], wanted) or within(wanted, actual[0])


def observed_employment_type(job: RawJob) -> str | None:
    if job.source == "shixiseng":
        return "internship"
    native = (
        job.raw_payload.get("workType")
        if job.source == "zhaopin"
        else job.raw_payload.get("workTypes")
        if job.source == "jobsdb"
        else [at(job.raw_payload, "job", "campusJobKind"), at(job.raw_payload, "job", "workType")]
    )
    values: list[object] = []
    for labels in (
        native,
        at(job.raw_payload, "detail_structured", "employmentType"),
        job.raw_payload.get("employment_type"),
    ):
        values.extend(labels if isinstance(labels, list) else [labels])
    return source_employment_label(values)


def passes_filters(job: RawJob, request: SearchRequest) -> bool:
    # Work-hours labels and employment types can coexist (a full-time
    # internship). The model considers all supplied job details.
    return passes_location(job, request)


class LocalAdapter:
    def __init__(
        self,
        name: str,
        client: AsyncWebClient,
        *,
        max_pages: int = 1,
        page_size: int = 10,
        candidate_limit: int = 60,
        result_limit: int = 10,
        detail_limit: int = 3,
    ) -> None:
        if (
            name not in HOSTS
            or not 1 <= max_pages <= 5
            or not 1 <= page_size <= 50
            or not 1 <= candidate_limit <= 250
            or not 1 <= result_limit <= 100
            or not 0 <= detail_limit <= 100
        ):
            raise ValueError("Invalid source or retrieval bounds")
        self.name, self.client = name, client
        self.max_pages, self.page_size = max_pages, page_size
        self.candidate_limit, self.result_limit, self.detail_limit = (
            candidate_limit,
            result_limit,
            detail_limit,
        )

    async def search_async(
        self, request: SearchRequest, *, result: SourceResult | None = None
    ) -> SourceResult:
        if request.location_ref is not None:
            mapped = await get_location_catalog().source_location(request.location_ref, self.name)
            request = request.model_copy(update={"location_ref": mapped})
        steps = self._search_steps(request, result if result is not None else SourceResult())
        try:
            plan = next(steps)
            while True:
                try:
                    page = await self.client.request_async(
                        plan.url, body=plan.body, headers=plan.headers
                    )
                except RetrievalFailure as exc:
                    plan = steps.throw(exc)
                else:
                    plan = steps.send(page)
        except StopIteration as done:
            return done.value  # type: ignore[no-any-return]
        finally:
            steps.close()

    def _search_steps(
        self, request: SearchRequest, result: SourceResult
    ) -> Generator[SearchPlan, WebPage, SourceResult]:
        build_search_plan(request, self.name)
        label = f"{self.name}/{request.target_direction}"
        result.warnings.append(
            f"{label}: searched the website for requested roles; location and employment preferences checked locally. Jobs are compared and ordered during recommendation."
        )
        if request.salary_range:
            result.warnings.append(
                f"{label}: salary_range is a preference, not applied; pass to Group 6."
            )
        if request.work_mode:
            result.warnings.append(f"{label}: work_mode is advisory; source cannot verify it.")
        if request.employment_type_unrestricted:
            result.warnings.append(
                f"{label}: employment type unrestricted; unknown types retained."
            )
        seen: set[str] = set()
        detail_count = 0
        filtered = 0
        unreadable = 0
        for number in range(request.page, min(5, request.page + self.max_pages - 1) + 1):
            plan = build_search_plan(request, self.name, number, self.page_size)
            try:
                page = yield plan
                records = parse_listing(self.name, page)
            except RetrievalFailure as exc:
                result.errors.append(
                    workflow_error(
                        exc.code,
                        str(exc),
                        source=self.name,
                        target_direction=request.target_direction,
                        page=number,
                    )
                )
                break
            if page.cached:
                result.warnings.append(
                    f"{label}: cached listing, fetched_at={page.fetched_at.isoformat()}."
                )
            if not records:
                break
            new_count = 0
            for record in records:
                if result.candidate_count >= self.candidate_limit:
                    break
                result.candidate_count += 1
                try:
                    job = map_listing(self.name, record, page, request.target_direction)
                    job.source_url = detail_url(job)
                    identity = job.source_job_id or job.source_url
                    if identity and identity in seen:
                        continue
                    if identity:
                        seen.add(identity)
                    new_count += 1
                    if not passes_location(job, request):
                        filtered += 1
                        continue
                    # These records already expose the fields needed to reject a mismatch.
                    if (
                        self.name == "jobsdb"
                        or (
                            self.name == "liepin"
                            and normalized(request.employment_type) == "internship"
                        )
                    ) and not passes_filters(job, request):
                        filtered += 1
                        continue
                    if self.name != "zhaopin" and detail_count < self.detail_limit:
                        url = detail_url(job)
                        if url:
                            detail_count += 1
                            try:
                                detail_page = yield SearchPlan(url, None, {}, ())
                                add_detail(job, detail_page)
                                job.raw_payload["detail_status"] = "ok"
                            except RetrievalFailure as exc:
                                result.errors.append(
                                    workflow_error(
                                        exc.code,
                                        str(exc),
                                        source=self.name,
                                        target_direction=request.target_direction,
                                        source_job_id=job.source_job_id or "",
                                        phase="detail",
                                    )
                                )
                                job.raw_payload["detail_status"] = "failed"
                        else:
                            job.raw_payload["detail_status"] = "missing_url"
                    elif self.name != "zhaopin":
                        job.raw_payload["detail_status"] = "limit_reached"
                    if not passes_filters(job, request):
                        filtered += 1
                        continue
                    if self.name == "shixiseng" and not job.title:
                        # Do not pad the candidate list with font-obfuscated, nameless cards.
                        unreadable += 1
                        continue
                    job.raw_payload["search_keywords"] = list(plan.keywords)
                    job.description_is_excerpt = bool(
                        not job.description
                        or (self.name == "jobsdb" and "detail_description" not in job.raw_payload)
                    )
                    job.employment_type = observed_employment_type(job)
                    job.raw_payload["description_is_excerpt"] = job.description_is_excerpt
                    job.raw_payload["missing_fields"] = [
                        name
                        for name in ("title", "source_url", "company", "location", "description")
                        if not getattr(job, name)
                    ]
                    if not job.source_url or not job.title:
                        result.warnings.append(
                            f"{label}: {job.source_job_id}: missing core source field; null retained."
                        )
                    if not job.description:
                        result.warnings.append(
                            f"{label}: {job.source_job_id}: description unavailable; null retained."
                        )
                    result.jobs.append(job)
                    if len(result.jobs) >= self.result_limit:
                        break
                except RetrievalFailure as exc:
                    result.errors.append(
                        workflow_error(
                            exc.code,
                            str(exc),
                            source=self.name,
                            target_direction=request.target_direction,
                            page=number,
                        )
                    )
            if not new_count:
                result.notices.append(make_notice("coverage_limited", source=self.name))
                result.warnings.append(
                    f"{label}: repeated page; stopped without claiming complete coverage."
                )
                break
            if (
                len(result.jobs) >= self.result_limit
                or result.candidate_count >= self.candidate_limit
                or number == self.max_pages
            ):
                result.notices.append(make_notice("coverage_limited", source=self.name))
                result.warnings.append(
                    f"{label}: reached a page or job limit; more jobs may be available (pages={number}, candidates={result.candidate_count})."
                )
                break
        if detail_count >= self.detail_limit and self.name != "zhaopin":
            result.warnings.append(
                f"{label}: detail budget={self.detail_limit}; some descriptions may be missing/excerpts."
            )
        if filtered:
            result.warnings.append(
                f"{label}: excluded {filtered} jobs that did not pass the location or employment checks."
            )
        if unreadable:
            result.notices.append(make_notice("coverage_limited", source=self.name))
            result.warnings.append(
                f"{label}: omitted {unreadable} jobs whose titles could not be read within the detail request limit; increase detail_limit to fetch more details."
            )
        return result
