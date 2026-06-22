"""产品专家：商品检索、推荐与事实校验。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.usage import UsageLimits

from agent.hooks import timed_agent_run
from agent.llm.model import get_expert_model as get_model
from agent.prompts.loader import render_skill
from agent.tools.mcp_client import SpecialistDeps, toolset_for

if TYPE_CHECKING:
    from agent.customer_agent import AgentContext

logger = logging.getLogger(__name__)

# 产品推荐通常需要「多关键词检索 + 多商品详情核实 + 结构化输出校验」，
# 单次复杂推荐超过 8 次请求是正常情况，因此产品专家单独给更高上限。
_REQUEST_LIMIT = 16
PostProcess = Callable[["ProductRecommendationOutput", list[str]], "ProductRecommendationOutput"]


class ProductRecommendationItem(BaseModel):
    """产品推荐单项结构，由 PydanticAI 约束模型输出。"""

    product_no: str = Field(default="", description="商品编号，必须来自商品工具返回；没有工具证据时留空")
    name: str = Field(default="", description="商品名称，必须来自商品工具返回；没有工具证据时留空")
    price: str = Field(default="", description="实时价格文本，必须来自工具返回；未知时留空，不得编造")
    stock_status: str = Field(default="", description="库存状态文本，必须来自工具返回；未知时留空，不得编造")
    highlights: list[str] = Field(
        default_factory=list,
        description="与用户诉求直接相关的关键参数、配置或卖点，必须基于工具返回信息",
        max_length=6,
    )
    match_score: int = Field(
        default=0, ge=0, le=100, description="商品与用户诉求的匹配分，0-100"
    )
    reason: str = Field(default="", description="结合用户需求给出的推荐理由")


class ProductRecommendationOutput(BaseModel):
    """产品专家标准 JSON 输出结构。"""

    reply_type: Literal["product_recommendation"] = "product_recommendation"
    status: Literal["ok", "no_match", "out_of_scope"] = Field(
        default="ok",
        description="产品处理状态：ok 有推荐，no_match 未找到可靠匹配，out_of_scope 超出数码商城经营范围",
    )
    summary: str = Field(default="", description="一句话说明本轮推荐或检索的整体判断")
    recommendations: list[ProductRecommendationItem] = Field(
        default_factory=list,
        description="经过工具检索和详情核实后的推荐商品列表；没有可靠匹配时为空",
        max_length=3,
    )
    notes: str = Field(default="", description="补充说明、证据不足提示或需要用户进一步补充的信息")


@dataclass(frozen=True)
class ProductSpec:
    """产品专家声明式配置。"""

    name: str
    label: str
    build_prompt: Callable[[], str]
    postprocess: PostProcess | None = None


def _product_no_match() -> ProductRecommendationOutput:
    """无可靠工具证据时的标准产品专家输出。"""
    return ProductRecommendationOutput(
        status="no_match",
        summary="暂未检索到可靠匹配的商品",
        recommendations=[],
        notes="没有找到符合条件且数据可靠的商品，请补充预算、品类或具体诉求后再试。",
    )


_SUPPORTED_DIGITAL_TERMS = (
    "手机",
    "电脑",
    "笔记本",
    "平板",
    "耳机",
    "手表",
    "相机",
    "键盘",
    "鼠标",
    "充电器",
    "数据线",
    "保护壳",
    "手机壳",
    "贴膜",
    "路由器",
    "显示器",
    "硬盘",
    "车载充电器",
    "行车记录仪",
    "车载支架",
    "蓝牙车充",
    "智能车机",
)
_OUT_OF_SCOPE_TERMS = (
    "汽车",
    "轿车",
    "越野车",
    "suv",
    "新能源车",
    "电动车",
    "摩托车",
    "自行车",
    "房子",
    "衣服",
    "服装",
    "鞋",
    "食品",
    "生鲜",
    "药",
    "家具",
    "沙发",
    "床",
    "化妆品",
    "机票",
)


def _out_of_scope_product(context: str) -> ProductRecommendationOutput | None:
    """识别明确非数码商品需求，避免把超范围请求误当成检索无结果。"""
    text = context.lower()
    if any(term in text for term in _SUPPORTED_DIGITAL_TERMS):
        return None
    matched = next((term for term in _OUT_OF_SCOPE_TERMS if term in text), "")
    if not matched:
        return None
    return ProductRecommendationOutput(
        status="out_of_scope",
        summary="该商品不在智能数码商城经营范围内",
        recommendations=[],
        notes=(
            f"用户想购买“{matched}”相关商品，但本商城只处理数码商品选购与客服问题。"
            "请直接说明当前不支持该品类，不要推荐车载配件、周边配件或其它替代商品；"
            "可引导用户改为咨询手机、电脑、耳机、平板、智能手表等数码商品。"
        ),
    )


def _product_json(output: ProductRecommendationOutput) -> str:
    """把产品专家结构化输出序列化为 JSON 字符串，供下游 summarize 渲染。"""
    return json.dumps(output.model_dump(mode="json"), ensure_ascii=False)


def _extract_tool_outputs(result: Any) -> list[str]:
    """收集 PydanticAI 工具原始返回，用于产品推荐事实校验。"""
    outputs: list[str] = []
    for message in result.all_messages():
        for part in getattr(message, "parts", []):
            if isinstance(part, ToolReturnPart):
                outputs.append(str(part.content))
    return outputs


def ground_product_result(
    result: ProductRecommendationOutput,
    tool_outputs: list[str],
) -> ProductRecommendationOutput:
    """校验推荐商品编号是否真实出现在工具返回中。"""
    evidence = "\n".join(tool_outputs)
    grounded = [
        rec
        for rec in result.recommendations
        if rec.product_no.strip() and rec.product_no.strip() in evidence
    ]

    dropped = len(result.recommendations) - len(grounded)
    if dropped:
        logger.warning("产品推荐事实校验：剔除 %d 条无工具证据支撑的条目。", dropped)

    if not grounded:
        return _product_no_match()

    result.recommendations = grounded
    names = "、".join(rec.name for rec in grounded if rec.name)
    result.summary = f"已基于工具返回商品筛选出 {len(grounded)} 款候选" + (f"：{names}" if names else "。")
    result.notes = (
        "推荐仅基于工具返回的商品；工具结果中未出现的型号不会作为推荐或替代方案。"
        if dropped or result.notes
        else ""
    )
    return result


SPEC = ProductSpec(
    name="product",
    label="产品咨询",
    build_prompt=lambda: render_skill("product"),
    postprocess=ground_product_result,
)


class ProductAgent:
    """产品专家能力：构造选购上下文并执行商品推荐。"""

    name = SPEC.name
    label = SPEC.label

    def __init__(self) -> None:
        self._agent: Agent | None = None

    def _get_agent(self) -> Agent:
        """惰性构建并复用产品专家 Agent，减少每轮 schema/toolset 初始化开销。"""
        if self._agent is None:
            model = get_model()
            if model is None:
                raise RuntimeError(f"LLM 未配置（缺少 OPENAI_API_KEY），无法执行：{SPEC.label}")
            self._agent = Agent(
                model,
                output_type=ProductRecommendationOutput,
                deps_type=SpecialistDeps,
                system_prompt=(
                    f"{SPEC.build_prompt()}\n\n"
                    "## 输出压缩要求\n"
                    "- 只保留用户决策需要的信息，避免复述工具原文、内部过程和重复卖点。\n"
                    "- summary 控制在一句话内；每款 highlights 最多 4 条；notes 无必要可留空。\n"
                    "- 推荐理由优先说明差异点和取舍，不堆砌完整参数。"
                ),
                toolsets=[toolset_for("product")],
            )
        return self._agent

    def build_context(
        self,
        ctx: AgentContext,
        query: str = "",
        previous_results: str = "",
    ) -> str:
        """构造产品专家上下文，只接收规划任务、推荐画像和依赖结果。"""
        lines: list[str] = []
        if ctx.user_profile:
            lines.append(f"【选购偏好】{ctx.user_profile}")
        if previous_results:
            lines.append(f"【前序处理结果】\n{previous_results}")
        lines.append(f"【任务上下文】{query or ctx.user_input}")
        return "\n".join(lines)

    async def run(self, context: str, deps: SpecialistDeps | None = None) -> str:
        """运行产品专家。"""
        out_of_scope = _out_of_scope_product(context)
        if out_of_scope is not None:
            return _product_json(out_of_scope)

        agent = self._get_agent()
        async with agent:
            result = await timed_agent_run(
                agent,
                context,
                SPEC.label,
                deps=deps or SpecialistDeps(),
                usage_limits=UsageLimits(request_limit=_REQUEST_LIMIT),
            )
        output = result.output
        if SPEC.postprocess is not None:
            output = SPEC.postprocess(output, _extract_tool_outputs(result))
        return _product_json(output)
