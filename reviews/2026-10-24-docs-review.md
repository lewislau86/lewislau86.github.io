# 三套教程评审报告

评审日期：2026-10-24  
评审对象：`docs/burn/`、`docs/mini-redis/`、`docs/tinyllm/`  
评审方式：通读 + 重点章节深读 + 源码/构建/链接/命令的可执行性抽查。未修改任何教程文件。

## 0. 一句话结论

**三套文档的内容质量都明显高于常见的个人技术博客，技术核查和实验记录尤其难得；真正拖后腿的不是知识，而是“承诺与交付的一致性”：有的实验只写进了正文、有的下载入口没有接上、有的课程只完成了四分之一。**

综合评分 **3.7 / 5**（按体量加权）；若只计算已完成的正文，约 **4.3 / 5**。

| 文档 | 规模 | 内容与教学 | 交付与维护 | 综合 |
| --- | --- | --- | --- | --- |
| mini-redis | 约 6.3 万汉字；14 章 + 28 篇源码分析 | 4.5 | 3.0 | **3.9** |
| Burn | 约 5.2 万汉字；15 章 | 4.3 | 3.0 | **3.7** |
| TinyLLM | 约 2.8 万汉字；站点 6 章完成 + 20 章大纲 | 4.3 | 2.2 | **3.0** |

评分不是精确测量，只用于排优先级：**内容与教学**看解释、结构、练习和准确性；**交付与维护**看“读者照着做能不能成功”、版本与验证记录是否自洽、后续同步成本。

## 1. 站点底座：比正文更稳的部分

先确认三套文档共同的工程状态，这些是加分项，也说明问题不在“不会做”：

- `npm run docs:build` 通过，无死链警告。
- 站内 Markdown 链接与锚点共 **726 条，0 条失效**（按构建后的 HTML id 校验，不是只看文件是否存在）。
- 引用到的公共资源（ZIP、notebook、SVG、示例源码）**0 个缺失**。
- 外部链接 **249 个唯一 URL，全部返回 200**。
- mini-redis 的 **83 处 `source:` 源码节选，按文件与行范围逐段比对，全部一致**。
- Burn 学习包的五个 bin 可以实际编译运行，输出与第 13 章记录一致（另在 macOS + Rust 1.99 上复跑通过）。

这是一套“可验证”的文档体系，而不是只靠写作印象。下面的问题，基本都是这个体系里少数没有接上的环节。

## 2. 分册详评

### 2.1 mini-redis：内容最成熟，交付有一个硬缺口

**最强的地方**

1. **调用链教学**：反复区分“同一任务的直接调用”“跨任务通知”“TCP 通信”三种箭头（[index.md](docs/mini-redis/index.md) 与第 03 章），这是很多源码分析最容易混淆的地方。
2. **逐文件文章与主线互补**：28 篇文章按源文件一一对应，主线章节讲行为，文章讲文件职责；两种入口在索引里说清楚了。
3. **验证记录可信**：`validation.md` 记录了失败、根因、修复、故障注入和限制，甚至保留“当时未通过”的历史，没有把“程序能跑”冒充“全部验证”。

**问题**

- **P0：网页上的实验命令跑不通。** [index.md](docs/mini-redis/index.md:97) 和 [labs/index.md](docs/mini-redis/labs/index.md:8) 让读者从“仓库根目录”执行 `cargo run --manifest-path docs/labs/Cargo.toml ...`，但站点仓库里没有 `docs/labs` 目录；真正的实验在 [`mini-redis-study.zip`](docs/public/mini-redis/mini-redis-study.zip) 里，而页面**没有任何指向这个 ZIP 的链接**。导入脚本本来想插入下载段，但替换锚点写的是 `## 阅读顺序`，实际标题是 `## 跨文件章节的阅读顺序`，所以从未命中（[import-mini-redis.py](scripts/import-mini-redis.py:76)）。读者第一步就会失败。（2026-10-24 已修，见第 6 节。）
- **P1：基线哈希有两个版本，解释不够清楚。** 正文写逻辑基线 `3d93b42`（[index.md](docs/mini-redis/index.md:61)、[validation.md](docs/mini-redis/validation.md:17)），发布清单写 `e82795b`（[mini-redis-source.json](scripts/mini-redis-source.json:3)）。`e82795b` 包含后来的中文注释与测试修复，两个哈希并存本身可以解释，但页面没有把“分析基线”和“发布快照”分开，读者 checkout `3d93b42` 复现不了验证记录里的单元测试。
- **P1：节选说明与节选内容矛盾。** 第 03、05、08 章说“去掉/省略注释”，但代码块保留了中文注释，注记也写着 `comments included`（[03-request-path.md](docs/mini-redis/03-request-path.md:57)、[05-tokio-server.md](docs/mini-redis/05-tokio-server.md:188)）。
- **P2：教学简写没有逐处标注。** 第 01 章把入口简化为 `bind("127.0.0.1:16379")`，真实代码是 `port.unwrap_or(DEFAULT_PORT)` 加 `format!`。前文说了“省略日志与参数解析”，但读者对照源码仍会疑惑。
- **P2：`$-1\r\n` 被写成“空 Bulk”**（[04-resp-and-connection.md](docs/mini-redis/04-resp-and-connection.md:54)）。RESP 里它是 Null bulk，空 Bulk 是 `$0\r\n\r\n`；对初学者这是两个不同的边界。
- **P2：目录最新一章没有并进路线。** 索引仍写“下面的 00—12 章”“最后读 08—12”（[index.md](docs/mini-redis/index.md:16)），但表格里已经有第 13 章；同时“各章安排了思考题与参考答案”也没有覆盖第 13 章。把 13 定位成“排障附录”并补一句说明即可。
- **P2：重复代码。** 主线章节与逐文件文章有整段相同的代码（例如第 05 章与 `source/src/server.md`），改一处容易漏另一处。

**判断**：内容 4.5，交付 3.0，综合 3.9。补上 ZIP 链接和一句“解压后 cd mini-redis-study”，P0 就消失；这也是三套里最容易快速回到 4.3 的一套。

### 2.2 Burn：技术密度最高，但有一处“幽灵实验”

**最强的地方**

1. **手算主线**：从 `[[1,2]]`、`W`、`b` 到一次 SGD 更新，数字前后咬合，读者可以完全不跑代码先走一遍。
2. **源码核对到签名级**：`float_add`、`BackendTypes`、`Tensor<D,K>`、`NodeGuard` 等都能在 Burn 0.22.1 源码里对上；还明确警告旧资料的 `Tensor<B, D>` 不要混用。
3. **分层阅读**：`::: tip 本章分两遍读` 和“第一遍/第二遍”表格，主动帮读者跳读，这在长教程里很少见。

**问题**

- **P0：第 7、10 章要求运行两个不存在的程序。** [07-training-to-inference.md](docs/burn/07-training-to-inference.md:111) 和 [10-import-and-deploy.md](docs/burn/10-import-and-deploy.md:80) 都让读者运行 `--bin regression_train` / `regression_verify`，但学习包的 [`src/bin/`](docs/public/burn/first-inference/src/bin) 只有 4 个文件，[`first-inference.zip`](docs/public/burn/first-inference.zip) 也只有 9 个文件，没有这两个 bin；`Cargo.toml` 也没有启用 `train`/`optim` feature。更矛盾的是，[13-learning-labs.md](docs/burn/13-learning-labs.md:58) 仍写“这是后续优先补充的完整实验，当前第 7 章先给流程”，[index.md](docs/burn/index.md:13) 也仍说“模型文件往返……尚未验证”。这恰好是全书唯一缺失的主线闭环：训练 → 保存 → 新进程加载。（2026-10-24 已补，见第 6 节。）
- **P1：第 12 章的调用链多了一层。** 正文写 `Dispatch::linear → B::linear → 默认实现中的 B::float_matmul`（[12-source-reading.md](docs/burn/12-source-reading.md:60)）。0.22.1 的 `impl ModuleOps for Dispatch` 并没有 `linear`，该方法是 trait 默认体，直接在 `Dispatch` 上组合 `float_matmul` / `float_add`；只有 Autodiff 覆盖了 `linear`。把 `B::linear` 画进链路，会让“教人读源码”的样板动作失去准确性。
- **P1：Rust 门槛与开头的承诺有落差。** 开头说“不要求预先懂 Rust”，第 2 章只用了约 3,000 汉字讲 const generic、所有权、trait、关联类型和 Cargo feature；第 5、11 章立刻进入 trait 签名、宏注册、GraphPrimitive、NodeGuard。作者用“第二遍再读”做了缓冲，但真正的 Rust 零基础读者会在第 2 章中段掉队。
- **P2：第 3、4 章各有一条重复导航**（[03-first-inference.md](docs/burn/03-first-inference.md:3)、[04-models-and-modules.md](docs/burn/04-models-and-modules.md:3)），首屏会出现两条内容相近的“上一章/下一章”。
- **P2：版本纪律有一处小裂缝。** `references.md` 说主要 API 链接固定到 PyTorch 2.12，但第 06、07、08 章有 3 条链接指向 `/docs/2.14/`。
- **P2：`Linear` 权重约定默认是 `[in, out]`，但 `LinearLayout::Col` 会改变存储方向**；正文用“特别注意”的绝对语气，补半句“默认 Row；Col 按转置存储”即可。
- **P2：`device.configure(...)` 在 0.22.1 的签名是 `&mut self`**。第 5 章的表格只写了调用形式，没有给出变量声明；若读者照抄成 `let device = ...; device.configure(...)` 会得到 E0596，建议直接写 `let mut device`。
- **P2：第 13 章偏薄**，只有约 1,200 汉字，却承担“实验清单 + 后续计划 + 训练/保存闭环”的兜底职责；在 P0 修好之前，它兜不住。

**判断**：内容 4.3，交付 3.0，综合 3.7。把第 7、10 章改回“计划态”只需几分钟；若补实验，则要同时更新两个 bin、`Cargo.toml` feature、ZIP、README、第 13 章和首页，工作量在 1～2 天。

### 2.3 TinyLLM：单章质量最高，课程完成度最低

**最强的地方**

1. **公式 → PyTorch → 数值实验** 的三段式很扎实。第 0 章的 LayerNorm/RMSNorm/ScaleNorm/QK Norm/DeepNorm 不只给公式，还说明作用位置、参数含义和边界；RMSNorm 的 `eps` 细节与 PyTorch 文档一致。
2. **研究资料新且克制**：第 4 章把 BPE、SuperBPE、TokSuite、CNF-MCE 分开讨论，明确“论文验证过”不等于“主流模型采用”。
3. **承认边界**：第 20、25 章虽然只是导读，但把 KV cache 与 Agent 外部记忆的边界讲清楚了，没有硬凑成完整章节。

**问题**

- **P0（课程层面）：站点 26 章里只有 6 章是完整教案，20 章是 200～300 字的占位页。** 首页开头承诺“从零实现一个能够训练、生成文本并接受基本评估的 TinyLLM”，但构造模型（第 6～9 章）、数据与损失（第 10～11 章）、训练循环与生成（第 16～19 章）都还没有正文。读者按目录无法完成这个闭环。首页确实写了“其余章节以规划或专题导读为主”，但第一句的承诺仍然过重。（本地 TinyLLM 源仓库的第 3 章其实已经写完，但尚未提交/导入，所以站点进度比实际写作进度还慢一章；见下文维护项。）
- **P1：首页让新手先看“Chapter 0 中的小词典”，但第 0 章没有这一节。** [index.md](docs/tinyllm/index.md:5) 的这句话会直接把目标读者带到不存在的锚点。
- **P1：章节连续性错误。** 第 12 章开头说“上一章我们已经知道……`backward()` 再把梯度写入参数的 `.grad`”，但第 11 章只是占位页；真正讲 backward 的是第 1、5 章。读者按顺序读会在第 12 章突然断线。
- **P1：缺少与另外两套同等级的验证记录。** Burn 和 mini-redis 都有环境、命令、输出和限制；TinyLLM 没有对应的验证页。第 5 章结尾说“本章的实验验证查表、单头注意力与 KV 复用……”（[chapter5_embeddings_output.md](docs/tinyllm/chapter5_embeddings_output.md:226)），但 `ch5.ipynb` 与 `ch12.ipynb` 的代码单元全部没有执行计数、也没有输出，读者无法核对当时跑出了什么。
- **P1：`ch15.ipynb` 的保存输出与当前代码不一致。** 第一个代码单元现在会打印“CUDA 可用 / MPS 可用”，但保存的输出还是旧版的“CPU 基础实验；CUDA 可选实验将在后面运行”；后面的 MPS 计时又说明它是在 MPS 上跑的。章节表格列了 7 个实验，notebook 里是“Do 8 + 练习 9”，编号也没有对齐。静态读者会以为输出是伪造的，尽管更可能只是重跑后没保存。
- **P2：排版风格与另外两套不一致。** TinyLLM 正文有近 200 个 `<strong>`，Markdown 粗体只有十余处；这是 GitBook 导入保真的结果（[import-tinyllm.py](scripts/import-tinyllm.py:47) 会把 `**...**` 转成 `<strong>`），渲染没问题，但维护和站内统一性较差，还出现了整段加粗、粗体跨句的情况。
- **P2：`Adafactor` 的表述已过时。** 第 12 章说“PyTorch 核心优化器中并不总是提供 Adafactor”（[chapter12_optimizers.md](docs/tinyllm/chapter12_optimizers.md:178)），但本课锁定的 PyTorch 2.11 已提供 `torch.optim.Adafactor`；应改为“2.11 已提供，旧版或 Transformers 另有实现”。
- **P2：章节编号跳跃（0、1、4、5、12、15）加上 20 个“（规划）”侧栏项**，会让第一次访问的人误以为课程已经基本完成。更清晰的做法是：侧栏只放已完成章节，另设一个“完整课程路线”页。

**判断**：已完成部分 4.3，课程整体 2.2，综合 3.0。它更像“六篇高质量专题 + 一份课程大纲”，还不是一门可以从头读到尾的课。它离“能开课”只差第 9、11、17、19 章这四个最小闭环章节，但差的就是最关键的四个。

## 3. 三套文档的共性问题

### 3.1 承诺比交付大一号

三套都在开头降低了门槛，但实际交付并不等价：

- Burn：“不要求懂 Rust/GPU” → 第 5、11 章需要读 trait 和宏。
- mini-redis：“Rust 初学者” → 第 01 章同时引入 Cargo、路径依赖、宏、`await`、`?`、`Bytes`。
- TinyLLM：“从零实现可训练模型” → 关键的第 6～11、16～19 章尚未写出。

**建议**：把“零基础”改成“有编程经验、愿意边查边学”；在每套开头放一个 5 行的“前置自检”，比事后解释更有效。

### 3.2 防御式写作过量

三套都有大量“不是……”“不能……”“不等于……”的限定。按每万字统计，“不是”约 15～24 次、“不能”约 19～25 次。准确性因此很高，但阅读节奏被切得很碎：读者刚建立一个直觉，紧接着就是三条例外。

**建议**：每节先给“结论句 + 一个最小例子”，把边界收进节末的“边界”提示块；同一页内不重复同一条限制。保留“不夸大”的优点，减少“每句话都要先免责”的负担。

### 3.3 完成度与篇幅不均衡

- Burn 最短的第 3 章约 1,500 汉字，最长的第 11 章约 5,700 汉字，相差近 4 倍。
- TinyLLM 从 200 字的占位页跳到 7,200 字的第 0 章。
- mini-redis 相对均匀，但 47 个页面（14 章 + 28 篇 + 索引/实验/验证）对第一次访问者仍然偏多。

**建议**：给每页加“本章产出 / 前置 / 预计阅读时间”，让读者知道什么时候可以跳过；长章拆成“正文 + 附录”，不要把源码细节全塞进主线。

### 3.4 维护方式不统一，缺少“交付级”检查

三套的生成方式不同：Burn 手写、mini-redis 由脚本导入、TinyLLM 由 GitBook 导入。结果是三种排版习惯、三种验证记录方式，以及这次发现的“幽灵实验”和“失联 ZIP”。

**建议**：把这次手工做的检查固化成 CI：

1. 构建后扫描所有 `cargo run --bin X`，确认目标存在；
2. 校验 `/public` 下的 ZIP、notebook、图片是否都有页面链接；
3. 校验 `<!-- source: file:lines -->` 与源码一致；
4. 校验版本声明（Burn 0.22.1、Tokio 1.32.0、PyTorch 2.x）没有混用；
5. 每周跑一次外部链接检查。

### 3.5 站点层：中文搜索基本不可用

VitePress 默认的 MiniSearch 分词对中文不友好。我用构建产物实测：

- 搜“隐藏向量” → **0 条结果**（正文里出现很多次）；
- 搜“归一化” → 3 条，且主要是标题恰好以它开头；
- 搜“主要可执行程序” → 0 条。

原因是整段中文被当成一个 token，只有前缀能匹配。对一个以中文为主、700+ 小节的站点，这是比排版更影响使用的问题。可考虑自定义 `tokenize`（`Intl.Segmenter` 或中文二元切分）或改用 Pagefind 等支持中文的搜索。

**2026-10-24 已修复**：在 [`config.mts`](docs/.vitepress/config.mts:75) 中为本地搜索加入汉字二元组 `tokenize`，构建通过；浏览器实测“隐藏向量”从 0 条变为有结果，“归一化”“权重共享”“KV cache”等查询均能命中对应章节。搜索索引由 1.1 MB 增至约 1.7 MB，仍在按需加载的范围内。

其他小项：100+ 页面没有 `description`；没有阅读时间/难度标签；4 个 ≥5 列的宽表在手机上需要横向滚动。

## 4. 优先修复清单

| 优先级 | 动作 | 位置 | 预计 |
| --- | --- | --- | --- |
| P0 | Burn：把第 7、10 章的实验改回“计划态”，或补齐两个 bin + `train` feature + ZIP + 第 13 章 + 首页 | [07](docs/burn/07-training-to-inference.md:108)、[10](docs/burn/10-import-and-deploy.md:77)、[13](docs/burn/13-learning-labs.md:56) | 10 分钟 / 1～2 天 |
| P0 | mini-redis：在首页和实验页加 ZIP 下载链接，写明“解压后 cd mini-redis-study”，并修导入脚本锚点 | [index](docs/mini-redis/index.md:97)、[labs](docs/mini-redis/labs/index.md:8)、[脚本](scripts/import-mini-redis.py:76) | 30 分钟 |
| P0 | TinyLLM：把首页第一句改成“站点已完成 6 章 + 20 章路线”，或把侧栏占位页收进单独的路线页 | [index](docs/tinyllm/index.md:5) | 1 小时 |
| P1 | Burn：修正第 12 章 `Dispatch::linear` 链路，补 `B::linear` 只属于 Autodiff 的说明 | [12](docs/burn/12-source-reading.md:60) | 30 分钟 |
| P1 | mini-redis：统一基线哈希表述；修正“去掉注释”与 `comments included` 的矛盾 | [index](docs/mini-redis/index.md:61)、[03](docs/mini-redis/03-request-path.md:57) | 1 小时 |
| P1 | TinyLLM：补“小词典”或删掉这句引用；修第 12 章“上一章”；重跑并保存 ch5/ch12/ch15 输出；把已写完的第 3 章导入站点 | [index](docs/tinyllm/index.md:5)、[ch12](docs/tinyllm/chapter12_optimizers.md:3)、[ch5](docs/tinyllm/chapter5_embeddings_output.md:226) | 半天 |
| P1 | 站点：中文搜索已修（2026-10-24）；`description` 仍待补 | [config.mts](docs/.vitepress/config.mts:75) | 半天 |
| P2 | 三套：清理重复导航、统一 PyTorch 链接版本、补 `LinearLayout` 说明、减少重复代码 | 见各节 | 1 天 |

## 5. 如果只改三件事

1. **让“读者照着做的第一步”成立**：Burn 的两个 bin、mini-redis 的 ZIP、TinyLLM 的课程承诺。这三处修完，三套文档的信任度会立刻回到内容本身的水准。
2. **修 Burn 第 12 章的调用链**：这是全书教“怎么读源码”的样板，错一层会误导方法，而不只是一个事实。
3. **给 TinyLLM 一个诚实的完成度呈现**：把站点 6 章完成品、已写完但未导入的第 3 章、20 章大纲分开，不要让读者在“第 6 章只有 200 字”时才意识到课程没写完。

## 6. 修复记录（2026-10-24）

- **Burn 的幽灵实验已补**：新增 `regression_train` / `regression_verify` 两个 bin，`Cargo.toml` 启用 `optim` feature；训练 `Linear(1,1)` 拟合 `y=2x+1`（400 步、lr 0.05、MSE），保存 `model_config.json`、`model.bpk`、`baseline.txt`，第二个进程只读文件重建模型。已实测：`weights=[2.0000002]`、`bias=[0.9999994]`，往返最大差 `0.000000`，与目标最大差 `0.000001`。同步更新了第 7、10、13 章，首页边界说明、`references.md`、学习包 README 与 ZIP。
- **mini-redis 的实验入口已修**：修正导入脚本的替换锚点（`## 跨文件章节的阅读顺序`），在教程首页生成“下载源码与实验”段，在实验页加 ZIP 提示；重新导入后，两处都指向 `/mini-redis/mini-redis-study.zip`。已从构建产物解压并实际运行 `ownership` 实验，输出 `ownership OK`。
- 中文搜索的修复见第 3.5 节。
- **第二轮（同日）**：mini-redis 补充分析基线/发布快照说明，并修正“去掉注释”的旧表述；Burn 第 12 章改为 `Dispatch::linear` 默认体 → `float_matmul` 的真实链路，首页增加 Rust 读前自检、第 2 章增加“读到什么程度”表；TinyLLM 修正“小词典”与“上一章”的悬空引用，执行并保存 ch5/ch12/ch15 notebook，ch15 表格与 notebook 编号对齐。

## 附录：本次检查记录

- 构建：`npm run docs:build`，通过。
- 站内链接/锚点：726 条，0 失效（对照 `dist` HTML 的 `id`）。
- 外部链接：249 个唯一 URL，0 非 200。
- 公共资源：0 缺失。
- mini-redis 源码节选：83/83 与源文件一致。
- Burn 源码断言：抽查 19 条，16 条逐字一致；`Dispatch::linear` 链路不符，`LinearLayout::Col` 未覆盖；`regression_*` 已于 2026-10-24 补齐并实测。
- TinyLLM：站点 6 章完整、20 章占位；本地源仓库第 3 章已写完但未导入；`ch5`/`ch12` notebook 无输出，`ch15` 保存输出与当前代码不一致；首页“小词典”不存在；第 12 章“上一章”指向占位页。
- 搜索：修复前用构建后的 MiniSearch 索引实测“隐藏向量”“主要可执行程序”均为 0 结果；修复后在 Chrome 中实测“隐藏向量”“归一化”“KV cache”等查询均返回对应章节。

> 说明：本报告是评审意见，不是教程的一部分。2026-10-24 已按第 6 节修复 Burn、mini-redis 的 P0 与中文搜索；其余教程文件未改动。评分与问题均已尽量给出可复核的位置；标注“抽查”的结论只代表本次检查范围。
