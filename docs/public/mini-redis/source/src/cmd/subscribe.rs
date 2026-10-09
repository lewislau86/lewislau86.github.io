use crate::cmd::{Parse, ParseError, Unknown};
use crate::{Command, Connection, Db, Frame, Shutdown};

use bytes::Bytes;
use std::pin::Pin;
use tokio::select;
use tokio::sync::broadcast;
use tokio_stream::{Stream, StreamExt, StreamMap};

/// 让当前连接进入订阅循环。
/// 本版本订阅模式只处理 SUBSCRIBE/UNSUBSCRIBE；其他命令回 Unknown 错误。
/// 不要把完整 Redis 对 PING、QUIT 或模式订阅的支持套到这里。
#[derive(Debug)]
pub struct Subscribe {
    channels: Vec<String>,
}

/// 取消给定频道；空列表表示取消该连接的全部现有频道。
/// 取消最后一个频道后，当前 apply 仍留在订阅循环，不会自动返回普通模式。
#[derive(Clone, Debug)]
pub struct Unsubscribe {
    channels: Vec<String>,
}

/// 频道消息流的统一类型。
/// Box 持有流，dyn Stream 隐藏具体实现，Item = Bytes 约束每次产出，Send 允许跨线程移动。
/// Pin 固定被装箱的流，供轮询需要；它不是锁，也不会自动启动流。
type Messages = Pin<Box<dyn Stream<Item = Bytes> + Send>>;

impl Subscribe {
    /// 接管频道 Vec；每个 String 都由命令拥有。
    pub(crate) fn new(channels: Vec<String>) -> Subscribe {
        Subscribe { channels }
    }

    /// 命令名已消费；至少读取一个频道，再循环读剩余文本。
    /// 参数缺失或类型不符返回 Err，完整格式如下。
    ///
    /// ```text
    /// SUBSCRIBE channel [channel ...]
    /// ```
    pub(crate) fn parse_frames(parse: &mut Parse) -> crate::Result<Subscribe> {
        use ParseError::EndOfStream;

        // 先读必需的第一个频道；vec! 宏创建并拥有这一元素。
        let mut channels = vec![parse.next_string()?];

        // 随后读取零个或多个频道；只有 EndOfStream 才表示列表结束。
        loop {
            match parse.next_string() {
                // 把拥有的 String 移入 Vec，不再依赖 Parse 中的原元素。
                Ok(s) => channels.push(s),
                // 参数已全部读取，break 离开解析循环。
                Err(EndOfStream) => break,
                // 真实解析错误返回 Handler，结束当前连接。
                Err(err) => return Err(err.into()),
            }
        }

        Ok(Subscribe { channels })
    }

    /// 服务端订阅入口，长期接管 Connection 与 Shutdown 的可变借用。
    /// 在同一个循环中处理初始订阅、追加订阅、取消订阅、消息推送和停止。
    pub(crate) async fn apply(
        mut self,
        db: &Db,
        dst: &mut Connection,
        shutdown: &mut Shutdown,
    ) -> crate::Result<()> {
        // 每个频道有一个 broadcast Receiver；StreamMap 按频道名管理流并合并消息。
        // 频道名唯一，同名 insert 会替换原流，不创建同名并列条目。
        let mut subscriptions = StreamMap::new();

        loop {
            // drain(..) 取出并清空待订阅列表，所有 String 移交建立订阅函数。
            // 后续 SUBSCRIBE 会重新往该 Vec 添加项，下轮循环再处理。
            for channel_name in self.channels.drain(..) {
                subscribe_to_channel(channel_name, &mut subscriptions, db, dst).await?;
            }

            // select 同时等待频道消息、socket 命令和停止；选中分支内的 write_frame 仍需 await。
            // 因此等待写回时，这个任务不会同时处理另一分支。
            select! {
                // Some 模式只接收有消息的流结果；空 StreamMap 返回 None 时本轮禁用该分支。
                Some((channel_name, msg)) = subscriptions.next() => {
                    dst.write_frame(&make_message_frame(channel_name, msg)).await?;
                }
                res = dst.read_frame() => {
                    let frame = match res? {
                        Some(frame) => frame,
                        // 对端 EOF 结束订阅；流被释放，Receiver 也随之释放。
                        None => return Ok(())
                    };

                    handle_command(
                        frame,
                        &mut self.channels,
                        &mut subscriptions,
                        dst,
                    ).await?;
                }
                _ = shutdown.recv() => {
                    return Ok(());
                }
            };
        }
    }

    /// 客户端编码 subscribe 与频道数组，按值消费命令。
    pub(crate) fn into_frame(self) -> Frame {
        let mut frame = Frame::array();
        frame.push_bulk(Bytes::from("subscribe".as_bytes()));
        for channel in self.channels {
            frame.push_bulk(Bytes::from(channel.into_bytes()));
        }
        frame
    }
}

async fn subscribe_to_channel(
    channel_name: String,
    subscriptions: &mut StreamMap<String, Messages>,
    db: &Db,
    dst: &mut Connection,
) -> crate::Result<()> {
    let mut rx = db.subscribe(channel_name.clone());

    // stream! 把 recv 循环适配成 Stream；yield 产出一个值后暂停，下一次轮询继续。
    // Box::pin 装箱并固定这个匿名流，Receiver 的所有权随流保存。
    let rx = Box::pin(async_stream::stream! {
        loop {
            match rx.recv().await {
                Ok(msg) => yield msg,
                // 接收落后时跳过已丢消息继续；当前实现不会把丢失数量通知客户端。
                Err(broadcast::error::RecvError::Lagged(_)) => {}
                Err(_) => break,
            }
        }
    });

    // 按频道名存入此连接的 StreamMap；clone 为键保留独立的 String。
    subscriptions.insert(channel_name.clone(), rx);

    // 订阅建立后才发确认，携带该连接当前频道数量。
    let response = make_subscribe_frame(channel_name, subscriptions.len());
    dst.write_frame(&response).await?;

    Ok(())
}

/// 订阅模式内部的命令处理；只允许增加和取消频道。
/// 新增频道先放到 subscribe_to，由外层下一轮建立对应流。
async fn handle_command(
    frame: Frame,
    subscribe_to: &mut Vec<String>,
    subscriptions: &mut StreamMap<String, Messages>,
    dst: &mut Connection,
) -> crate::Result<()> {
    // 仍复用 Command::from_frame 解析，但执行许可由此处的 match 决定。
    match Command::from_frame(frame)? {
        Command::Subscribe(subscribe) => {
            // into_iter 消费频道 Vec，extend 将其元素移入待处理列表。
            subscribe_to.extend(subscribe.channels.into_iter());
        }
        Command::Unsubscribe(mut unsubscribe) => {
            // 空参数代表全部取消；先复制当前 keys 为 Vec，再逐个删除，避免边迭代借用边修改。
            if unsubscribe.channels.is_empty() {
                unsubscribe.channels = subscriptions
                    .keys()
                    .map(|channel_name| channel_name.to_string())
                    .collect();
            }

            for channel_name in unsubscribe.channels {
                subscriptions.remove(&channel_name);

                let response = make_unsubscribe_frame(channel_name, subscriptions.len());
                dst.write_frame(&response).await?;
            }
        }
        command => {
            let cmd = Unknown::new(command.get_name());
            cmd.apply(dst).await?;
        }
    }
    Ok(())
}

/// 构造 [subscribe, 频道, 数量] 确认。
/// 接收 String 的所有权，使 Bytes::from 可复用其分配；调用者决定是否需要 clone。
fn make_subscribe_frame(channel_name: String, num_subs: usize) -> Frame {
    let mut response = Frame::array();
    response.push_bulk(Bytes::from_static(b"subscribe"));
    response.push_bulk(Bytes::from(channel_name));
    response.push_int(num_subs as u64);
    response
}

/// 构造 [unsubscribe, 频道, 剩余数量] 确认。
fn make_unsubscribe_frame(channel_name: String, num_subs: usize) -> Frame {
    let mut response = Frame::array();
    response.push_bulk(Bytes::from_static(b"unsubscribe"));
    response.push_bulk(Bytes::from(channel_name));
    response.push_int(num_subs as u64);
    response
}

/// 构造 [message, 频道, 内容] 推送帧，消息仍以 Bytes 保留。
fn make_message_frame(channel_name: String, msg: Bytes) -> Frame {
    let mut response = Frame::array();
    response.push_bulk(Bytes::from_static(b"message"));
    response.push_bulk(Bytes::from(channel_name));
    response.push_bulk(msg);
    response
}

impl Unsubscribe {
    /// 从借用的频道切片复制出拥有的 Vec；命令不依赖调用者列表继续存活。
    pub(crate) fn new(channels: &[String]) -> Unsubscribe {
        Unsubscribe {
            channels: channels.to_vec(),
        }
    }

    /// 命令名已消费；UNSUBSCRIBE 允许后面没有频道，表示取消全部。
    /// 每项仍必须是文本，格式如下。
    ///
    /// ```text
    /// UNSUBSCRIBE [channel [channel ...]]
    /// ```
    pub(crate) fn parse_frames(parse: &mut Parse) -> Result<Unsubscribe, ParseError> {
        use ParseError::EndOfStream;

        // 从空 Vec 开始，和必须先读一个频道的 Subscribe 不同。
        let mut channels = vec![];

        // 逐项消费参数；EndOfStream 结束，其他错误返回。
        loop {
            match parse.next_string() {
                // 取得 String 后移入待取消列表。
                Ok(s) => channels.push(s),
                // 合法的列表结束，哪怕列表长度为零。
                Err(EndOfStream) => break,
                // 这里返回类型本来就是 ParseError，无须转换为库错误。
                Err(err) => return Err(err),
            }
        }

        Ok(Unsubscribe { channels })
    }

    /// 客户端编码取消命令；没有频道时只包含 unsubscribe 名称。
    pub(crate) fn into_frame(self) -> Frame {
        let mut frame = Frame::array();
        frame.push_bulk(Bytes::from("unsubscribe".as_bytes()));

        for channel in self.channels {
            frame.push_bulk(Bytes::from(channel.into_bytes()));
        }

        frame
    }
}
