"""口播全文生成（本地规则，无外部 LLM）。"""

from __future__ import annotations
import json
import os

from schemas import VideoPlan, ScriptResult
from utils import get_logger

logger = get_logger("copywriter")


def _stub_script_response() -> str:
    return json.dumps({
        "title": "为什么现在很多老板，开始重新看 AI agent？",
        "hook": "很多老板到现在，还把 AI 当聊天工具，但真正厉害的地方，根本不在聊天。",
        "full_script": (
            "很多老板到现在，还把 AI 当聊天工具，但真正厉害的地方，根本不在聊天。"
            "AI agent 能做的，是真正承担工作流——比如自动跟进销售线索、自动生成报告、自动处理客服对话。"
            "它不需要你手把手指挥，它能判断、能决策、能行动。"
            "这就是为什么越来越多的老板开始认真对待 AI agent——不是因为潮流，"
            "而是因为它真的能替你的团队干活。"
            "你真正该思考的，不是用不用 AI，而是怎么让 AI 真的去公司里干活。"
        ),
        "cta": "你真正该思考的，不是用不用 AI，而是怎么让 AI 真的去公司里干活。",
    }, ensure_ascii=False)


def _is_eco_topic(plan: VideoPlan) -> bool:
    blob = f"{plan.topic}{plan.industry}{plan.style}"
    keys = ("环保", "环境", "低碳", "绿色", "地球", "垃圾", "一次性", "气候", "节能", "污染")
    return any(k in blob for k in keys)


def _is_biz_topic(plan: VideoPlan) -> bool:
    blob = f"{plan.topic}{plan.industry}"
    keys = ("老板", "企业", "获客", "营销", "增长", "经营", "销售", "团队", "公司", "AI agent", "Agent")
    return any(k in blob for k in keys)


def _local_script_response(plan: VideoPlan) -> str:
    if _is_eco_topic(plan):
        if plan.duration_sec <= 30:
            title = f"{plan.topic}：从小事做起"
            hook = f"{plan.topic}，不用等完美方案，今天就能开始。"
            full_script = (
                f"{plan.topic}，关键在坚持小事，别等完美方案。"
                "少用一次性用品，出门带杯带袋；随手关水关电，办公室家里都能做。"
                "垃圾分类别偷懒，能回收的别混进厨余。"
                "今天就定一个小目标，先坚持七天，再拉朋友一起。"
            )
            cta = "定一个小目标，先坚持七天。"
        else:
            title = f"{plan.topic}：三件小事立刻能做"
            hook = f"{plan.topic}，听起来很大，其实每天顺手就能出一份力。"
            full_script = (
                f"先说结论，{plan.topic}，关键在从小处坚持，不用等完美方案。"
                "第一，减少一次性用品，出门带杯带袋，小事累积影响大。"
                "第二，做好垃圾分类，随手关水关电，办公室家里都能立刻做。"
                "第三，把习惯告诉同事和家人，影响面会放大。"
                "别等号召，今天就选一个小动作，坚持七天，你会看到改变。"
            )
            cta = "今天就选一个小动作，先坚持七天。"
    elif _is_biz_topic(plan):
        title = f"{plan.topic}：必须看懂的3个关键点"
        hook = f"你以为{plan.topic}是概念，其实它已经直接影响获客、效率和成本。"
        full_script = (
            f"先说结论，{plan.topic}不是锦上添花，而是经营效率的分水岭。"
            "第一，先从一个高频、重复、可标准化的流程切入，避免一上来做大而全。"
            "第二，把输入、判断、输出拆清楚，先把数据口径和责任人固定，再谈自动化。"
            "第三，用一周看效率指标，用一个月看业务结果，能复用再扩展到更多场景。"
            "很多团队不是做不成，而是起步太重、验证太慢。"
            "你现在就可以选一个流程，今天立项，明天验证，七天看到第一轮结果。"
        )
        cta = "从一个流程开始，先跑通再放大。"
    else:
        title = f"{plan.topic}：3个实用角度"
        hook = f"{plan.topic}，很多人只停留在表面，其实关键在于可执行。"
        full_script = (
            f"先把结论说清：{plan.topic}，最重要的是能落地、能验证。"
            "第一，先明确一个最小场景，别一上来铺太大。"
            "第二，把步骤写清楚：谁来做、用什么信息、产出是什么。"
            "第三，用小周期复盘：一周看过程，一个月看结果，再决定是否加码。"
            "行动不需要完美，但需要开始。今天就定一个小目标，七天回看一次。"
        )
        cta = "定一个小目标，七天后复盘一次。"

    return json.dumps({
        "title": title,
        "hook": hook,
        "full_script": full_script,
        "cta": cta,
    }, ensure_ascii=False)


def generate_script(plan: VideoPlan) -> ScriptResult:
    """Generate a complete voiceover script from the video plan (local)."""
    if os.environ.get("STUB_MODE") == "1":
        raw = _stub_script_response()
    else:
        raw = _local_script_response(plan)

    logger.debug("Local script raw output: %s", raw[:300])
    data = json.loads(raw)

    result = ScriptResult(
        title=data.get("title", ""),
        hook=data.get("hook", ""),
        full_script=data.get("full_script", ""),
        cta=data.get("cta", ""),
    )
    logger.info("Script generated: title=%r, length=%d chars", result.title, len(result.full_script))
    return result
