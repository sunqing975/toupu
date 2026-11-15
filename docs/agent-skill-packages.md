# Agent Skills 与工具边界

技能遵循 https://agentskills.io/specification：入口为带 YAML frontmatter 的 SKILL.md（name、description），正文为 Markdown 工作步骤。技能不是 function-calling 工具。工具仍负责数据读取和受控提案，保留现有权限与账务边界。

技能是目录，SKILL.md 是入口而非整个技能。支持 ZIP 导入一个完整技能目录，保留 references/、scripts/、assets/ 等任意子目录和二进制资源；ZIP 可以直接包含 SKILL.md，也可以只包一层技能目录。兼容原单入口创建和已有数据。目录文件以相对路径和原始字节（base64）存入 agent_skills.config.files，不解压到服务器文件系统；原 config.content 兼容保留，无需数据库迁移。

技能页支持目录文件选择、文本预览、单文件下载、入口编辑与启停；保存入口不删除其他文件。同名导入返回409，不静默覆盖。暂不提供附件在线编辑、整包替换或批量导入多个技能。内置技能初次入库时读取整个仓库目录，已保存的内置内容不自动覆盖。

ZIP 限制：压缩包10MiB、最多512个条目、单文件5MiB、解压总计20MiB；SKILL.md 和文本预览最多100KB（UTF-8）。拒绝绝对路径、路径穿越、反斜杠、盘符、符号链接/特殊文件、加密ZIP、重复路径（不区分大小写）、文件/目录冲突、多技能及损坏压缩包；忽略 macOS 的 .DS_Store / __MACOSX 元数据。脚本只保存、阅读、下载，绝不执行；导入不安装依赖，也不扩大业务工具权限。自定义技能不得覆盖系统安全约束。

对话初始仅提供全局启用技能的名称和描述，通过 load_skill 按需加载入口和文件清单，通过 read_skill_file(name, path) 按需加载 UTF-8 引用资料或脚本源码；二进制/大文件在管理页下载。停用技能既不出现在目录中也不能通过上述工具读取。尚不支持逐 Agent 绑定指令包。旧工具选择配置继续兼容；工具能力与技能指令分开管理。

API：GET/POST /api/v1/agent/skill-packages；POST /import（multipart file）；PATCH /{id}；GET /{id}/files?path=相对路径；GET /{id}/download?path=相对路径。列表带 files 路径/字节数/是否可预览清单，不在初始上下文中塞入附件正文。

历史会话禁止物理删除：archive/restore 幂等，archived_at 标记；默认列表不显示归档，归档列表可回看并恢复；前端点击直接执行不弹确认框。消息不变，归档操作审计。

模型工具参数必须符合 JSON Schema：required 数组位于对象层，不能将内部布尔标记传给服务商。实际服务商曾因此返回 502；修复后需进行真实工具请求验证，不以 mock 测试替代。
