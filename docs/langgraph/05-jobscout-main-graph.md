# 构建 JobScout 主 graph

[返回学习入口](README.md) · 适用：第 2、3 组 · 前置：[JobScout 状态与数据契约](04-jobscout-state-contracts.md)

**教学精简示例。**以下代码用 Mock 数据演示节点、条件边和执行，不需要 API key。它省略 `plan_search`、岗位标准化、去重、时效检查、完整 `RecommendationResult` 和服务注入；澄清分支是占位，不是 JobScout 的完整交互流程。正式流程以[开发指南第 2、3 节](../JobScout_Development_Guide.md#2-端到端用户流程)为准。

代码中的 `Profile`、`Job`、`Result` 是局部教学类型，不是项目 schema。`match_score` 仅用于演示内部排序；MVP 不要求前端显示数字分数。

```python
from typing import Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph


class Profile(TypedDict):
    target_directions: list[str]
    skills: list[str]
    preferences: dict[str, object]


class Job(TypedDict):
    job_id: str
    title: str
    company: str
    location: str
    required_skills: list[str]


class Result(TypedDict):
    job_id: str
    title: str
    company: str
    match_score: float
    missing_skills: list[str]
    preparation_suggestions: list[str]


class JobScoutState(TypedDict):
    resume_text: str
    target_directions: list[str]
    preferences: dict[str, object]
    profile: NotRequired[Profile]
    clarification_question: NotRequired[str]
    jobs: NotRequired[list[Job]]
    results: NotRequired[list[Result]]
    answer: NotRequired[str]


MOCK_JOBS: list[Job] = [
    {
        "job_id": "job-001",
        "title": "Junior Data Analyst",
        "company": "Northstar Labs",
        "location": "Hong Kong",
        "required_skills": ["Python", "SQL", "Tableau"],
    },
    {
        "job_id": "job-002",
        "title": "Business Intelligence Analyst",
        "company": "Harbour Analytics",
        "location": "Hong Kong",
        "required_skills": ["SQL", "Power BI", "statistics"],
    },
]


def extract_profile(state: JobScoutState) -> dict[str, Profile]:
    skills = [
        skill
        for skill in ("Python", "SQL", "Tableau", "Power BI", "statistics")
        if skill.lower() in state["resume_text"].lower()
    ]
    profile: Profile = {
        "target_directions": state["target_directions"],
        "skills": skills,
        "preferences": state["preferences"],
    }
    return {"profile": profile}


def validate_profile(state: JobScoutState) -> dict[str, str]:
    profile = state["profile"]
    if not profile["target_directions"]:
        return {"clarification_question": "你希望申请哪些岗位？"}
    return {"clarification_question": ""}


def route_after_validation(
    state: JobScoutState,
) -> Literal["clarify", "search"]:
    return "clarify" if state.get("clarification_question") else "search"


def clarify(state: JobScoutState) -> dict[str, str]:
    return {"answer": state["clarification_question"]}


def retrieve_jobs(state: JobScoutState) -> dict[str, list[Job]]:
    location = state["profile"]["preferences"].get("location")
    jobs = [job for job in MOCK_JOBS if not location or job["location"] == location]
    return {"jobs": jobs}


def recommend(state: JobScoutState) -> dict[str, list[Result]]:
    profile_skills = {skill.lower() for skill in state["profile"]["skills"]}
    results: list[Result] = []
    for job in state["jobs"]:
        required = {skill.lower() for skill in job["required_skills"]}
        gaps = sorted(required - profile_skills)
        score = len(required & profile_skills) / len(required) if required else 0.0
        results.append(
            {
                "job_id": job["job_id"],
                "title": job["title"],
                "company": job["company"],
                "match_score": round(score, 2),
                "missing_skills": gaps,
                "preparation_suggestions": [f"补强技能：{skill}" for skill in gaps],
            }
        )
    results.sort(key=lambda item: item["match_score"], reverse=True)
    return {"results": results[:5]}


def format_output(state: JobScoutState) -> dict[str, str]:
    lines = [
        f"{item['title']} | {item['company']} | 教学排序 {item['match_score']:.0%}"
        for item in state["results"]
    ]
    return {"answer": "\n".join(lines) or "没有找到符合条件的岗位。"}


builder = StateGraph(JobScoutState)
builder.add_node("extract_profile", extract_profile)
builder.add_node("validate_profile", validate_profile)
builder.add_node("clarify", clarify)
builder.add_node("retrieve_jobs", retrieve_jobs)
builder.add_node("recommend", recommend)
builder.add_node("format_output", format_output)
builder.add_edge(START, "extract_profile")
builder.add_edge("extract_profile", "validate_profile")
builder.add_conditional_edges(
    "validate_profile",
    route_after_validation,
    {"clarify": "clarify", "search": "retrieve_jobs"},
)
builder.add_edge("clarify", END)
builder.add_edge("retrieve_jobs", "recommend")
builder.add_edge("recommend", "format_output")
builder.add_edge("format_output", END)

jobscout_graph = builder.compile()
output = jobscout_graph.invoke(
    {
        "resume_text": "Skills: Python, SQL, Tableau",
        "target_directions": ["Data Analyst"],
        "preferences": {"location": "Hong Kong"},
    }
)
print(output["answer"])
```

这里的 `clarify` 只返回提示并结束。真实项目必须把问题返回前端，接收答案后更新画像、重新校验，再继续搜索。见[人工澄清：interrupt 与恢复](06-clarification-and-resume.md)。