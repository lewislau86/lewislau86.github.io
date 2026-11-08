# R18：工作区隔离独立实验

教程：https://lewislau86.github.io/learn-agent-rust/worktree-isolation

Rust 1.85+（edition 2024）、Git 2.28+。仅用 Rust 标准库调用本地 Git，无需 Cargo 依赖、模型密钥或网络。

```sh
rustc --edition=2024 -D warnings worktree-isolation.rs -o worktree-lab
./worktree-lab parallel ./r18-parallel
./worktree-lab unmerged ./r18-unmerged
./worktree-lab accepted ./r18-accepted
./worktree-lab conflict ./r18-conflict
rustc --edition=2024 -D warnings --test worktree-isolation.rs -o worktree-tests
./worktree-tests --test-threads=1
```

Windows 使用对应 .exe；本章自动验收在 macOS 与 Linux 上运行，符号链接测试限 Unix。
所有场景必须指定一个尚不存在的目录。程序只在这个新目录中创建专用 repository/、workspaces/、空 Git 配置与 hooks 目录，不接收已有仓库地址，不操作当前文档仓库。失败后也保留目录供检查。

19 个场景见源码 SCENARIOS。目录始终保留，方便运行后用 Git 检查。例如：

```sh
git -C ./r18-parallel/repository worktree list --porcelain
git -C ./r18-parallel/workspaces/alpha-a1 status --short
git -C ./r18-unmerged/workspaces/alpha-a1 log --oneline
```

任务与 worktree 的绑定只在本进程的管理器内存中；Git 的 worktree 登记和分支实际落盘。R17 所有权由固定 owner + epoch fixture 模拟；未实现租约、跨进程抢占、注册表恢复或多管理器互斥。

parallel 使用两个真实线程分别写入固定 README。busy 验证线程未 join 时保留目录；stale 在放行 worker 前更新凭据，验证旧凭据无法继续写。Drop 取消仍在等待的 writer 并 join，保留所有 Git 目录与文件。

retire 按顺序检查绑定、线程、工作区变化（含未跟踪和忽略文件）、主工作区状态，以及 HEAD 是否从原 base 派生并已进入 main。仅在检查通过时执行无 --force 的 git worktree remove，分支引用始终保留。保留不代表自动提交或归档；删除失败、锁定和身份不符也会保留。

accepted 由实验驱动明确执行本地 fast-forward，之后才回收。conflict 在专用主工作区保留真实冲突供检查。本实验不 push、不自动合并业务改动。所有文件与提交均为固定练习数据。

worktree 隔离目录、HEAD 与索引，但共享对象、普通分支引用和 common Git 元数据；它不提供进程、网络或安全沙箱。安全检查只适用于本实验的单宿主、固定工具与受控线程，不保证任意外部命令并发修改时的隔离。

实验会去掉继承的 GIT_* 路由/配置变量，并使用自己的空全局配置和 hooks 目录；Git 子进程用 Command 参数数组调用，不经 shell。工具进程没有超时，Git 挂起会阻塞；验证脚本使用外层超时保护。

outputs/ 和 evidence.json 保存实际记录。仓库中运行 python3 scripts/verify-agent-worktrees.py 重新生成；--check 会重跑测试、检查真实 Git/文件状态，并从最终下载包解压编译、复验全部场景。
