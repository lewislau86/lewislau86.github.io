# src/parse.rs：从帧数组按顺序取出命令参数

<!-- analyzes: src/parse.rs -->

[打开对应源码](../../../src/parse.rs) · [源码文章索引](../README.md) · [总目录](../../README.md)

Frame 已解决字节边界，Parse 解决参数读取。它持有 Vec<Frame> 的 IntoIter，不借用 socket；每次 next 都会消费一个元素。理解迭代器当前位置，才能读懂具体命令的 parse_frames。

## 它和哪些代码交互

```text
Command::from_frame → Parse::new → next_string 取命令名
 → Get/Set/Ping/...::parse_frames → next_string/bytes/int
 → Command::from_frame 再调用 finish
```

## new 确认顶层必须是数组

<!-- source: src/parse.rs:31-45; comments included -->
```rust
pub(crate) fn new(frame: Frame) -> Result<Parse, ParseError> {
    let array = match frame {
        Frame::Array(array) => array,
        frame => return Err(format!("protocol error; expected array, got {frame:?}").into()),
    };

    Ok(Parse {
        parts: array.into_iter(),
    })
}

/// 消费并返回下一项；ok_or 将 Option::None 转换为 EndOfStream。
fn next(&mut self) -> Result<Frame, ParseError> {
    self.parts.next().ok_or(ParseError::EndOfStream)
}
```

Array 的所有权移动进迭代器。单个 Simple 即使内容是 GET，也不是本地支持的命令请求格式。next 将迭代结束转为 EndOfStream，上层再根据参数是否可选解释它。

## 三种参数读取有不同约束

next_string 接受 Simple 或 Bulk，但 Bulk 必须是 UTF-8，并复制为 String，供键、频道、命令名持有；next_bytes 接受 Simple/Bulk，前者转字节，后者直接交出 Bytes；next_int 接受 Integer 或可经 atoi 读取的文本/字节，结果是 u64。

因此 SET 值可保留任意字节，键与频道名在此路径中要求文本。给 next_string 增加某种容错会同时影响多个命令；只想改变某个命令规则时，应先判断规则应该属于 Parse 还是该命令。

## 结束与错误如何影响连接

<!-- source: src/parse.rs:95-101; comments included -->
```rust
pub(crate) fn finish(&mut self) -> Result<(), ParseError> {
    if self.parts.next().is_none() {
        Ok(())
    } else {
        Err("protocol error; expected end of frame, but there was more".into())
    }
}
```

finish 消费性地尝试再取一项，有多余参数就失败。它由已知命令解析完成后的 Command::from_frame 调用，Unknown 提前返回不走 finish。

Set 读取必需 key/value 时 EndOfStream 是失败，读取可选 TTL 开始处则可表示没有 TTL；Subscribe 至少先读一个频道，之后的 EndOfStream 才结束列表。Parse 本身不能替每条命令做这个决定。Other 和 EndOfStream 经 trait 转换可传到 Handler，已知命令解析 Err 使连接任务结束，而不是自动生成 Error 帧。

## 修改时怎么验证

沿 Command::from_frame 检查迭代器是否已吃掉命令名，再进入具体 parse_frames；不要把命令名重复读取。边界用例至少包含缺必需项、缺可选项、类型不符、多余项，以及非法 UTF-8 键与合法二进制值的区别。

## 这里的 Rust 写法：拥有元素的迭代器与借用迭代不同

`Vec::into_iter` 将元素所有权交给迭代器，每次 next 移出一个 Frame；所以 next_bytes 能直接返回 Bulk 的 Bytes。`ok_or` 把 None 变成错误，`ok_or_else` 只在需要时调用闭包生成错误。`atoi::<u64>` 明确泛型类型，避免把尖括号误读成比较表达式。

需要拆开语法时，接着读 [Rust 阅读说明的对应小节](../../rust-reading-guide.md#iterators)。

## 读完后沿哪里继续

[src/cmd/mod.rs](cmd/mod.md) → [src/cmd/set.rs](cmd/set.md) → [src/cmd/subscribe.rs](cmd/subscribe.md)。

跨文件串读：[第 03 章：命令解析站点](../../03-request-path.md)。
