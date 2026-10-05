"""Demand-driven China/Hong Kong retrieval, source mapping and hard-filter checks.

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
from jobscout.services.notice_service import make_notice

from .html_fields import Tree
from .models import RawJob, RetrievalFailure, workflow_error
from .planning import location_region, normalized, plan_keywords, validate_request
from .sources import SourceResult
from .web_transport import AsyncWebClient, WebPage

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
CITY_CODES = {
    "北京": ("530", "010", "beijing"),
    "上海": ("538", "020", "shanghai"),
    "广州": ("763", "050020", "guangzhou"),
    "深圳": ("765", "050090", "shenzhen"),
    "杭州": ("653", "070020", "hangzhou"),
    "成都": ("801", "280020", "chengdu"),
}
COUNTRY_CN = {
    "cn",
    "china",
    "中国",
    "中國",
    "mainland china",
    "中国大陆",
    "中國大陸",
    "中国内地",
    "中國內地",
    "全国",
}
COUNTRY_HK = {"hk", "hong kong", "hongkong", "香港", "中国香港", "香港特别行政区", "香港特別行政區"}
REGION_ALIASES = {"kowloon": "九龙", "new territories": "新界", "九龍": "九龙"}
HOSTS = {
    "zhaopin": "jobs.zhaopin.com",
    "liepin": "www.liepin.com",
    "shixiseng": "www.shixiseng.com",
    "jobsdb": "hk.jobsdb.com",
}


def city_name(location: str | None) -> str | None:
    value = normalized(location or "")
    for city, (_, _, english) in CITY_CODES.items():
        if city in value or re.search(r"\b" + english + r"\b", value):
            return city
    return None


def source_keywords(request: SearchRequest, source: str) -> list[str]:
    """Only translate known direction baselines; explicit user keywords stay intact."""
    words = plan_keywords(request)
    if not request.keywords:
        mapping = {
            "data analyst": "数据分析",
            "business analyst": "商业分析",
            "data scientist": "数据科学",
        }
        if source == "jobsdb":
            reverse = {v: k for k, v in mapping.items()}
            words = [reverse.get(normalized(words[0]), words[0])]
        else:
            words = [mapping.get(normalized(words[0]), words[0])]
    return words


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
    region = location_region(request.location)
    if not request.location_unrestricted and region != ("hk" if source == "jobsdb" else "cn"):
        raise RetrievalFailure(
            "SEARCH_REGION_UNSUPPORTED", "Source does not cover the requested region."
        )
    city = city_name(request.location)
    if city and not request.location_unrestricted:
        remainder = normalized(request.location or "")
        for part in (
            CITY_CODES[city][2],
            city,
            "mainland china",
            "china",
            "中国大陆",
            "中国",
            "市",
        ):
            remainder = remainder.replace(part, "")
        if remainder.strip(" ,，"):
            raise RetrievalFailure(
                "SEARCH_LOCATION_UNSUPPORTED",
                "City subdistrict/multiple-location filtering is not verified; use one city per request.",
            )
    if (
        source != "jobsdb"
        and not request.location_unrestricted
        and not city
        and normalized(request.location or "") not in COUNTRY_CN
    ):
        raise RetrievalFailure(
            "SEARCH_LOCATION_UNSUPPORTED",
            "City has no verified native parameter mapping; refusing nationwide fallback.",
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
            "S_SOU_WORK_CITY": CITY_CODES[city][0] if city else "489",
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
        code = CITY_CODES[city][1] if city else ""
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
            if request.location_unrestricted or normalized(request.location or "") in COUNTRY_HK
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
        # Native documented-by-website work-type IDs; internship is not part-time.
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
    if job.source == "jobsdb":
        description = tree.field("data-automation", "jobAdDetails")
    elif job.source == "liepin":
        description = tree.field("data-selector", "job-intro-content")
        for node in tree.find(tag="script", attr="type", value="application/ld+json"):
            try:
                raw = "".join(c for c in node.children if isinstance(c, str))
                structured = JSON_OBJECT.validate_python(json.loads(raw, strict=False))
                if structured.get("@type") == "JobPosting":
                    description = description or string(structured.get("description"))
                    job.raw_payload["detail_structured"] = structured
            except ValueError, ValidationError:
                continue
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
        job.posted_at = posted.group(1) if posted else None
        job.expiry_at = expiry.group(1) if expiry else None
        companies = [
            n for n in tree.find(tag="a") if "/com/" in n.attrs.get("href", "") and n.text()
        ]
        job.company = (
            clean_field(tree.field("class", "com-name"))
            or (clean_field(companies[0].text()) if companies else None)
            or job.company
        )
    description = clean_field(description)
    if not description:
        raise RetrievalFailure(
            "SEARCH_RESPONSE_FORMAT",
            "Job description marker missing; detail may be unavailable or changed.",
        )
    job.description = description
    job.raw_payload["detail_description"] = description
    job.raw_payload["detail_fetched_at"] = page.fetched_at.isoformat()


def passes_location(job: RawJob, request: SearchRequest) -> bool:
    if not request.location_unrestricted:
        wanted = normalized(request.location or "")
        if job.source == "jobsdb":
            places = job.raw_payload.get("locations")
            if (
                not isinstance(places, list)
                or not places
                or any(at(obj(p), "countryCode") != "HK" for p in places)
            ):
                return False
        if wanted not in COUNTRY_CN | COUNTRY_HK:
            actual = normalized(job.location or "")
            city = city_name(request.location)
            if city:
                if city not in actual and CITY_CODES[city][2] not in actual:
                    return False
            else:
                wanted = wanted.replace("hong kong", "").replace("香港", "").strip(" ,，")
                wanted = REGION_ALIASES.get(wanted, wanted)
                actual = actual.replace("九龍", "九龙")
                for english, chinese in REGION_ALIASES.items():
                    actual = actual.replace(english, chinese)
                if wanted not in actual:
                    return False
        elif wanted in COUNTRY_CN and location_region(job.location) != "cn":
            return False
    return True


def observed_employment_type(job: RawJob) -> str | None:
    labels: JsonValue = (
        job.raw_payload.get("workType")
        if job.source == "zhaopin"
        else job.raw_payload.get("workTypes")
        if job.source == "jobsdb"
        else at(job.raw_payload, "job", "campusJobKind")
        or at(job.raw_payload, "job", "workType")
        or at(job.raw_payload, "detail_structured", "employmentType")
        or job.raw_payload.get("employment_type")
    )
    values = [labels] if isinstance(labels, str) else labels if isinstance(labels, list) else []
    types = {normalized(v) for v in values if isinstance(v, str)}
    if job.source == "shixiseng" or re.search(
        r"\bintern(?:ship)?\b|实习|實習", job.title or "", re.I
    ):
        return "internship"
    aliases = {
        "internship": {"internship", "intern", "实习", "實習"},
        "full-time": {"full time", "fulltime", "全职", "全職"},
        "part-time": {"part time", "parttime", "兼职", "兼職"},
        "contract": {"contract", "contract/temp", "合同工"},
        "freelance": {"freelance", "自由职业"},
    }
    return next((kind for kind, values in aliases.items() if types & values), None)


def passes_filters(job: RawJob, request: SearchRequest) -> bool:
    if not passes_location(job, request):
        return False
    if request.employment_type_unrestricted:
        return True
    kind = normalized(request.employment_type)
    title = (job.title or "").casefold()
    internship = (
        job.source == "shixiseng"
        or "实习" in title
        or "實習" in title
        or re.search(r"\bintern(?:ship)?\b", title) is not None
    )
    labels: JsonValue = (
        job.raw_payload.get("workType")
        if job.source == "zhaopin"
        else job.raw_payload.get("workTypes")
        if job.source == "jobsdb"
        else at(job.raw_payload, "job", "campusJobKind")
        or at(job.raw_payload, "job", "workType")
        or at(job.raw_payload, "detail_structured", "employmentType")
    )
    values = [labels] if isinstance(labels, str) else labels if isinstance(labels, list) else []
    types = {normalized(v) for v in values if isinstance(v, str)}
    internship = internship or bool(types & {"internship", "intern", "实习", "實習"})
    if kind == "internship":
        return internship
    if internship:
        return False
    aliases = {
        "full time": {"full time", "fulltime", "全职", "全職"},
        "part time": {"part time", "parttime", "兼职", "兼職"},
        "contract": {"contract", "contract/temp", "合同工"},
        "freelance": {"freelance", "自由职业"},
    }
    return bool(types & aliases.get(kind, set()))


def keyword_match_status(job: RawJob, request: SearchRequest) -> str:
    """Conservative lexical guard, not profile matching or semantic ranking.

    Reject only when a source description is available and has no query keyword match.
    Missing details/excerpts remain explicitly unverified to avoid false exclusions.
    """
    text = normalized((job.title or "") + " " + (job.description or ""))
    if request.keywords:
        matched = all(normalized(word) in text for word in request.keywords)
    else:
        alternatives = {
            "data analyst": ("data analyst", "data analysis", "数据分析", "數據分析"),
            "business analyst": (
                "business analyst",
                "business analysis",
                "商业分析",
                "業務分析",
                "业务分析",
                "商業分析",
            ),
            "data scientist": ("data scientist", "data science", "数据科学", "數據科學"),
        }
        words = alternatives.get(
            normalized(request.target_direction), tuple(source_keywords(request, job.source))
        )
        matched = any(normalized(word) in text for word in words)
    if matched:
        return "matched"
    if not job.description or (
        job.source == "jobsdb" and "detail_description" not in job.raw_payload
    ):
        return "unverified"
    return "no_match"


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
            f"{label}: demand-driven source search; confirmed location/type constraints checked locally. Relevance/ranking belongs to Group 6."
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
        unrelated = 0
        unverified = 0
        for number in range(1, self.max_pages + 1):
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
                    match_status = keyword_match_status(job, request)
                    if match_status == "no_match":
                        unrelated += 1
                        continue
                    unverified += match_status == "unverified"
                    job.raw_payload["keyword_match_status"] = match_status
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
                    f"{label}: retrieval bound reached; results are not exhaustive (pages={number}, candidates={result.candidate_count})."
                )
                break
        if detail_count >= self.detail_limit and self.name != "zhaopin":
            result.warnings.append(
                f"{label}: detail budget={self.detail_limit}; some descriptions may be missing/excerpts."
            )
        if filtered:
            result.warnings.append(
                f"{label}: excluded {filtered} candidates with mismatching/unknown hard filters."
            )
        if unreadable:
            result.notices.append(make_notice("coverage_limited", source=self.name))
            result.warnings.append(
                f"{label}: omitted {unreadable} unreadable-title cards after bounded detail retrieval; coverage is incomplete, increase detail_limit to request more details."
            )
        if unrelated:
            result.notices.append(make_notice("coverage_limited", source=self.name))
            result.warnings.append(
                f"{label}: excluded {unrelated} candidates without lexical keyword matches in available title/description; this conservative check may miss synonyms."
            )
        if unverified:
            result.warnings.append(
                f"{label}: {unverified} candidates have unverified keyword matches because description is missing/an excerpt; downstream review required."
            )
        return result
