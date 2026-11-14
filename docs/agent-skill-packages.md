# Agent Skills 与工具边界

技能遵循 https://agentskills.io/specification：入口为带 YAML frontmatter 的 SKILL.md（name、description），正文为 Markdown 工作步骤。技能不是 function-calling 工具。工具仍负责数据读取和受控提案，保留现有权限与账务边界。

本版支持单个 SKILL.md 导入、正文查看、更新与启停；内置技能以仓库目录为源。附件、脚本执行和 ZIP 安装不在本版范围内，不把脚本作为任意代码执行。自定义技能是用户提供的指令，不得覆盖系统安全约束。

对话初始仅提供已选且启用技能的名称和描述，通过 load_skill 按需加载正文。停用技能既不出现在目录中也不能加载。旧工具选择配置继续兼容；工具能力与技能指令分开管理。

历史会话禁止物理删除：archive/restore 幂等，archived_at 标记；默认列表不显示归档，归档列表可回看并恢复；前端点击直接执行不弹确认框。消息不变，归档操作审计。

模型工具参数必须符合 JSON Schema：required 数组位于对象层，不能将内部布尔标记传给服务商。实际服务商曾因此返回 502；修复后需进行真实工具请求验证，不以 mock 测试替代。
