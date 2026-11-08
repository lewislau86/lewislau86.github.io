场景：changed-readme；模型：父子均为固定规则替身；运行：同进程、单个子线程
父模型上下文（只有结构化子任务报告进入工具结果）：
父 1 | system | PARENT_ONLY_NOTE=release-check
父 2 | user | 读取 README，告诉我项目启动命令。
父 3 | assistant | call_id=parent/delegate-1 delegate("读取 README，告诉我项目启动命令。")
父 4 | tool | call_id=parent/delegate-1 status=ok | session=child-1 status=Completed summary=启动命令：cargo run --release child_models=2 child_tools=1
父 5 | assistant | 项目启动命令：cargo run --release
宿主诊断：子上下文（不发送给父模型）：
子 1 | system | 只读 README；只回传启动命令；不允许再次委派。
子 2 | user | 读取 README，告诉我项目启动命令。
子 3 | assistant | call_id=child-1/read-1 read_file("README.md")
子 4 | tool | call_id=child-1/read-1 status=ok | # 练习项目 / 启动命令：cargo run --release / CHILD_RAW_ONLY=fixture-detail
子 5 | assistant | 启动命令：cargo run --release
子统计：models=2 tools=1 messages=5 stop=Completed
总统计：models=4 tools=2 reads=1 successes=1 parent_messages=5 parent_stop=Completed
边界：context_isolated=true fixture_goal_met=true
清理：active_workers=0 scratch_removed=true workspace_removed=true
