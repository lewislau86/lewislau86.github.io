---
editLink: false
---

# 02 用所有权管理一份数据

[上一章](/mini-redis/01-first-run.md) · [目录](/mini-redis/index.md) · [下一章](/mini-redis/03-request-path.md)

上一章已经运行自己的 hello_tokio 客户端，其中 `let mut client`、`"rust".into()` 和返回的 `Some(...)` 都还只是初见。先从这些代码背后的数据责任开始：服务器需要接收一块数据、保存它、让多个请求读取它，最后释放它。Rust 把这些责任写进类型与函数签名。理解这个过程，比背语法表更容易理解借用检查器；异步执行的细节留到第 05 章。

## 从变量与类型开始

教学示例：

```rust
let port: u16 = 16379;
let mut requests = 0_u64;
requests += 1;
let key = String::from("course");
let bytes = b"rust";
```

`let` 绑定名字，默认不能重新赋值；`mut` 允许修改绑定或经它修改数据。`u16` 是 16 位无符号整数，`u64` 是 64 位无符号整数，`usize` 用于索引和长度，位宽随平台变化。Rust 通常能推断类型。`b"rust"` 是字节串字面量；`"rust"` 是 UTF-8 字符串字面量，两者用途不同。

`let n = n + 1;` 称为遮蔽：创建一个新绑定，可以改变类型。`n += 1` 则修改原绑定，要求原变量可变。在 `connection.rs::write_decimal` 中，你会看到同名 `buf` 从数组变为 `Cursor`，那就是遮蔽。

## 一份 String 的责任转交

```rust
let key = String::from("course");
let owned = key;
println!("{owned}");
```

赋值把 `String` 的所有权移给 `owned`。此后不能再使用 `key`。这样在作用域结束时，只有一个持有者负责释放这份字符串的堆内存。

这段则**故意不能编译**：

```compile_fail
let key = String::from("course");
let owned = key;
println!("{key}"); // E0382：使用已经被移动的值
```

如果只是想检查它，借用即可：

```rust
fn key_len(key: &str) -> usize {
    key.len()
}

let key = String::from("course");
assert_eq!(key_len(&key), 6);
println!("{key}"); // 借用结束，所有权仍在这里
```

`&key` 创建引用，不转移所有权。`&String` 可以在这里转换为 `&str`，让函数既接受拥有的字符串，也接受字符串切片。引用必须在数据仍有效时使用，编译器会检查这一点。

整数等实现 `Copy` 的类型赋值时会复制，原变量仍然可用。`String` 不实现 `Copy`；`key.clone()` 会创建独立字符串。不要把所有 `clone()` 都理解为深拷贝：后面遇到的 `Arc` 与 `Bytes` 会共享底层资源。

## 共享借用与独占借用

`&T` 是共享引用，`&mut T` 是独占的可变引用。在有效借用重叠的范围内，不能同时存在一个可变引用和另一个读写同一值的引用。

```rust
let mut value = String::from("ru");
let edit = &mut value;
edit.push_str("st");
// edit 最后一次使用之后，这次借用可以结束。
let view = &value;
assert_eq!(view, "rust");
```

规则关注引用实际使用的范围，不是机械地要求整个 `{}` 都不能再碰原值。所谓“内部可变性”允许类型在共享引用后面封装修改行为，但仍必须遵守其安全约束；第 06 章的 `Mutex` 会在运行时落实独占访问。

在网络代码中，`Connection::read_frame(&mut self)` 需要改变接收缓冲区，所以要求独占借用；`Db::get(&self)` 只借用数据库句柄，通过内部锁访问状态。

## 字符串、字节与切片

| 类型 | 是否持有数据 | 在本项目中的用途 |
| --- | --- | --- |
| `String` | 拥有 UTF-8 文本 | 命令名称、键、频道名 |
| `&str` | 借用 UTF-8 文本 | 查询时临时借用键 |
| `Vec<u8>` | 拥有可增长字节数组 | 通用二进制容器 |
| `&[u8]` | 借用一段字节 | 解析输入，不必复制 |
| `BytesMut` | 持有可修改字节缓冲 | 连接持续接收数据 |
| `Bytes` | 持有不可变字节视图，可共享底层存储 | 值与 Bulk 帧 |

切片是“对连续区域的引用及长度”。`&data[..]` 表示完整区域，`&data[start..end]` 包含 start，不包含 end。UTF-8 字符可能占多个字节，所以 `"中".len()` 是 3；RESP 长度数的是字节，不能数汉字个数。

本地 `Parse::next_string` 要求键能转成 UTF-8 文本，而 `next_bytes` 允许值是任意字节。真正 Redis 的键也可以是二进制；这一点将在第 11 章比较。

## 用 struct 聚合，用 enum 区分

[Set](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/set.rs) 的源码结构：

```rust
pub struct Set {
    key: String,
    value: Bytes,
    expire: Option<Duration>,
}
```

`struct` 把同时存在的字段放在一起。`Option<Duration>` 是“可能没有”的值：`Some(duration)` 或 `None`。它让“没有 TTL”成为显式状态。

[Frame](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/frame.rs) 则是枚举：

```rust
pub enum Frame {
    Simple(String),
    Error(String),
    Integer(u64),
    Bulk(Bytes),
    Null,
    Array(Vec<Frame>),
}
```

一个 Frame 在某一时刻只属于一个分支，不是同时具有所有字段。`Vec<Frame>` 把动态数组内容放在另一块存储里，因此枚举虽然递归描述帧，类型本身仍有确定大小。

用 `match` 同时判断并取出字段：

```rust
match value {
    Some(bytes) => println!("有 {} 字节", bytes.len()),
    None => println!("键不存在"),
}
```

如果只关心一个分支，可以写 `if let Some(bytes) = value { ... }`。`while let Some(item) = iterator.next()` 则不断取值，直到不存在。`match` 分支中的 `_` 表示忽略；`ref key` 表示在模式中借用字段而不移动它。

## 给类型添加行为

```rust
impl Set {
    pub fn key(&self) -> &str {
        &self.key
    }
}
```

`impl` 添加关联函数与方法。没有 `self` 的 `Set::new(...)` 是关联函数；`set.key()` 是方法。`Self` 指当前实现的类型，`self` 指当前实例。

| 接收者 | 所有权含义 | 本地例子 |
| --- | --- | --- |
| `&self` | 暂时共享借用实例 | `Set::key` |
| `&mut self` | 暂时独占借用，可修改实例 | `Connection::read_frame` |
| `self` | 取得实例所有权 | `Set::into_frame` |
| `mut self` | 取得所有权，并允许修改本地实例 | `Client::subscribe` |

`#[derive(Debug, Clone)]` 请求编译器生成 trait 实现。`Debug` 支持 `{:?}`，`Clone` 支持显式克隆；`derive` 不会自动让一个类型实现 `Copy`。`println!`、`vec!` 是带 `!` 的宏，不是普通函数。

## 真正运行一次

执行 [ownership 实验](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/ownership.rs)：

```sh
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin ownership
```

程序把一个 String 移进小型存储，再借用键查询；同时比较 `String::clone`、`Bytes::clone` 与 `Arc::clone` 的用途。运行后主动修改它：保留一个对表中值的引用，再插入另一条记录，最后使用该引用，观察编译器为什么拒绝潜在失效的借用。

为什么查询函数通常接受 `&str`，而存入表中的键要用 `String`？

<details>
<summary>参考答案</summary>

查询只在调用期间使用键，不必取得它的所有权；表需要让键在函数返回之后继续存在，使用 String 自己持有数据。接收借用后也可以复制为 String，但那是显式分配，不是自动延长引用的生命周期。

</details>

需要系统补充时，阅读 Rust Book 的[所有权](https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html)、[引用和借用](https://doc.rust-lang.org/book/ch04-02-references-and-borrowing.html)、[结构体](https://doc.rust-lang.org/book/ch05-00-structs.html)与[枚举](https://doc.rust-lang.org/book/ch06-00-enums.html)。后续章节继续使用这里的同一套规则。
