---
name: portfolio-review
description: 用户要求组合体检、集中度、收益归因或调仓分析时使用。依次核对估值覆盖、仓位集中与风险，提供有证据和不确定性说明的分析。
---
# 投资组合体检

1. 使用 read_summary 和 read_valuation 检查数据时点、行情覆盖率、现金和市值。行情缺失先声明限制。
2. 使用 analyze_portfolio_concentration 获取仓位占比与集中度，不由语言模型自行计算正式指标。
3. 使用 read_returns、analyze_returns_attribution 及 read_risk_events 区分已实现、未实现、分红和回撤；不足数据不能给出可信收益率。
4. 输出「观察事实 → 风险与局限 → 可选择的行动」，每条结论绑定工具证据，不承诺收益。
5. 调仓仅提供计划草案；未获明确请求不生成提案，更不入账或自动下单。
