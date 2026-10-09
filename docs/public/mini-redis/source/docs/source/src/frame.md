# src/frame.rs：协议类型、游标解析与展示

<!-- analyzes: src/frame.rs -->

[打开对应源码](../../../src/frame.rs) · [源码文章索引](../README.md) · [总目录](../../README.md)

Frame 是两端共享的协议数据模型。此文件检查/解析字节并提供展示与构造工具；把 Frame 编码写回 socket 的方法位于 connection.rs。它不会读取 socket，也不会分发 SET。

## 它和哪些代码交互

```text
Connection::parse_frame → Frame::check → Frame::parse → 返回 Frame
命令 into_frame / 响应构造 → array / push_bulk / push_int
日志、错误信息、部分客户端路径 → Display / PartialEq
```

## 枚举先限定了本地表达能力

<!-- source: src/frame.rs:14-31; comments included -->
```rust
#[derive(Clone, Debug)]
pub enum Frame {
    Simple(String),
    Error(String),
    Integer(u64),
    Bulk(Bytes),
    Null,
    Array(Vec<Frame>),
}

#[derive(Debug)]
pub enum Error {
    /// 当前字节不够一帧；Connection 将继续读，不能当成致命格式错误。
    Incomplete,

    /// 格式、数值转换或文本编码等错误。
    Other(crate::Error),
}
```

Integer 使用 u64，Null 是无载荷分支，Array 用 Vec 递归容纳帧。Error::Incomplete 表示需要更多字节；Other 承载其他解析错误。Connection 会将前者转成“继续读取”，因此不能随意把半帧合并为致命错误。

## check 与 parse 的分工

check 消费临时游标以判断一帧是否已经齐全；parse 重新从起点构造 String、Bytes、Vec。两者都按首字节分支，数组递归处理子帧。parse 的未知前缀分支是 unimplemented，所以本地正常调用先 check 再 parse；对外直接调 parse 需要注意这一前置约定。

Bulk 正文按长度处理，不能用 CRLF 切正文。当前实现跳过尾部两个字节而没有核验其内容，也没有统一递归深度/输入尺寸上限。这是实际检查范围，不应仅凭函数名 check 推断所有协议约束都覆盖。

## get_line 返回的是借用

<!-- source: src/frame.rs:263-280; comments included -->
```rust
fn get_line<'a>(src: &mut Cursor<&'a [u8]>) -> Result<&'a [u8], Error> {
    // 从游标当前位置直接扫描输入切片，不分配新字符串。
    let start = src.position() as usize;
    // 扫描到倒数第二字节，给后面的 i + 1 留出位置。
    let end = src.get_ref().len() - 1;

    for i in start..end {
        if src.get_ref()[i] == b'\r' && src.get_ref()[i + 1] == b'\n' {
            // 找到 CRLF 后，把游标推进到下一段内容的起点。
            src.set_position((i + 2) as u64);

            // 返回正文切片，排除 CRLF；切片仍引用原输入数据。
            return Ok(&src.get_ref()[start..i]);
        }
    }

    Err(Error::Incomplete)
}
```

`a` 绑定的是 Cursor 内层字节的有效期，输出来自这一段数据，而不是新分配的字符串。外层可变借用只用于推进位置。peek_u8 看一个字节不前进；get_u8 读取并前进；skip 校验余量再前进；get_decimal 读取行后调用 atoi。parse 根据需要把借来的片段转换为自己持有的数据。

## 辅助 trait 也可能影响业务

array/push_bulk/push_int 用于构造命令和订阅响应，push 对非 Array 会 panic。PartialEq<&str> 仅对 Simple/Bulk 比较，供客户端检查 OK、subscribe 等标记。Display 把帧转为可读形式，to_error 将意外响应包装成错误。

Display 原本适合日志；Subscriber::next_message 却把 content.to_string 再变回 Bytes，导致非 UTF-8 内容可能改变。修改展示格式前必须查这些调用者，不能假定它只影响日志。From<String/&str/UTF8/整数转换错误> 与 std::error::Error/Display 的实现则决定 `?` 如何把失败传出去。

## 这里的 Rust 写法：类型上的能力由 trait 实现补齐

get_line 的 `a` 关联返回切片与原输入字节，不延长数据寿命。`impl Display for Frame` 让 to_string 可用，`impl PartialEq<&str>` 让帧可与协议标记比较；后者的参数出现 &&str，是因为 trait 方法借用了本来已经为 &str 的右操作数。`try_into()?` 是可失败的长度转换，不是忽略溢出的强制截断。

需要拆开语法时，接着读 [Rust 阅读说明的对应小节](../../rust-reading-guide.md#lifetimes)。

## 读完后沿哪里继续

[src/connection.rs](connection.md) → [src/parse.rs](parse.md) → [src/clients/client.rs](clients/client.md) → [tests/frame_validation.rs](../tests/frame_validation.md)。

跨文件串读：[第 04 章：Frame 在连接中的位置](../../04-resp-and-connection.md)。
