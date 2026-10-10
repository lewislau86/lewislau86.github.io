use mini_redis::{server, Connection, Frame};

use std::net::SocketAddr;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::time::{self, Duration};

/// 直接通过 TcpStream 发送 RESP 并比较原始响应，绕过 Client 编解码。
/// 覆盖缺失值、写入读取以及写半关闭后的剩余响应。
#[tokio::test]
async fn key_value_get_set() {
    let addr = start_server().await;

    // 连接本测试绑定的临时端口。
    let mut stream = TcpStream::connect(addr).await.unwrap();

    // 请求尚不存在的 hello。
    stream
        .write_all(b"*2\r\n$3\r\nGET\r\n$5\r\nhello\r\n")
        .await
        .unwrap();

    // 按 Null 的固定长度读取并比较字节。
    let mut response = [0; 5];
    stream.read_exact(&mut response).await.unwrap();
    assert_eq!(b"$-1\r\n", &response);

    // 写入 hello=world。
    stream
        .write_all(b"*3\r\n$3\r\nSET\r\n$5\r\nhello\r\n$5\r\nworld\r\n")
        .await
        .unwrap();

    // 读取 Simple OK，确认这次命令已得到成功响应。
    let mut response = [0; 5];
    stream.read_exact(&mut response).await.unwrap();
    assert_eq!(b"+OK\r\n", &response);

    // 再次读取，预期得到已写入的值。
    stream
        .write_all(b"*2\r\n$3\r\nGET\r\n$5\r\nhello\r\n")
        .await
        .unwrap();

    // 仅关闭写方向，仍允许从同一 socket 读取服务端响应。
    stream.shutdown().await.unwrap();

    // 读取 Bulk world，即使客户端已不再发送新请求。
    let mut response = [0; 11];
    stream.read_exact(&mut response).await.unwrap();
    assert_eq!(b"$5\r\nworld\r\n", &response);

    // AsyncRead 返回 0 表示 EOF；这里直接读 socket，不是 Connection 的 Option 返回值。
    assert_eq!(0, stream.read(&mut response).await.unwrap());
}

/// 用真实时间验证 SET EX 的端到端过期行为；精确时间边界由 db 模块单元测试覆盖。
/// 按完整帧读取，Null 即使早于预期到达也不会卡在固定长度 read_exact 上。
#[tokio::test]
async fn key_value_timeout() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let (stop_tx, stop_rx) = tokio::sync::oneshot::channel::<()>();
    let server_task = tokio::spawn(server::run(listener, async {
        let _ = stop_rx.await;
    }));

    // 当前 runtime 的时钟不暂停；总上限同时覆盖建连、写入、读取和条件轮询。
    let result = time::timeout(Duration::from_secs(5), async {
        let mut stream = TcpStream::connect(addr).await.expect("TTL 测试建连失败");
        // 保留原测试的 EX 秒选项及原始 RESP 输入，不借助客户端编码掩盖协议差异。
        stream
            .write_all(
                b"*5\r\n$3\r\nSET\r\n$5\r\nhello\r\n$5\r\nworld\r\n\
                     +EX\r\n:1\r\n",
            )
            .await
            .expect("SET EX 写入失败");

        let mut connection = Connection::new(stream);
        let response = connection.read_frame().await.expect("SET 响应读取失败");
        assert!(
            matches!(&response, Some(Frame::Simple(value)) if value == "OK"),
            "SET 应返回 OK，实际为 {:?}",
            response
        );

        let get = Frame::Array(vec![Frame::Bulk("GET".into()), Frame::Bulk("hello".into())]);
        loop {
            connection.write_frame(&get).await.expect("GET 写入失败");
            let response = connection.read_frame().await.expect("GET 响应读取失败");
            match response {
                // 即使测试被长时间抢占、第一次 GET 已到期，也能正常识别完整 Null。
                Some(Frame::Null) => break,
                Some(Frame::Bulk(value)) => assert_eq!(value.as_ref(), b"world"),
                other => panic!("GET 应返回 world 或 Null，实际为 {:?}", other),
            }
            // 等待的是可观察的删除结果，sleep 仅限制轮询频率，不作为完成证明。
            time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await;

    // 正常完成或总超时后都请求停止，并确认服务器任务已退出。
    stop_tx.send(()).expect("服务端提前退出");
    time::timeout(Duration::from_secs(1), server_task)
        .await
        .expect("TTL 测试服务停机超时")
        .expect("TTL 测试服务任务 panic");
    result.expect("TTL 场景超过 5 秒：检查网络响应及后台过期清理");
}

#[tokio::test]
async fn pub_sub() {
    let addr = start_server().await;

    let mut publisher = TcpStream::connect(addr).await.unwrap();

    // 尚无订阅者，PUBLISH 应返回 Integer 0。
    publisher
        .write_all(b"*3\r\n$7\r\nPUBLISH\r\n$5\r\nhello\r\n$5\r\nworld\r\n")
        .await
        .unwrap();

    let mut response = [0; 4];
    publisher.read_exact(&mut response).await.unwrap();
    assert_eq!(b":0\r\n", &response);

    // 第一个连接仅订阅 hello。
    let mut sub1 = TcpStream::connect(addr).await.unwrap();
    sub1.write_all(b"*2\r\n$9\r\nSUBSCRIBE\r\n$5\r\nhello\r\n")
        .await
        .unwrap();

    // 读取订阅确认；后续发布建立在确认之后。
    let mut response = [0; 34];
    sub1.read_exact(&mut response).await.unwrap();
    assert_eq!(
        &b"*3\r\n$9\r\nsubscribe\r\n$5\r\nhello\r\n:1\r\n"[..],
        &response[..]
    );

    // 已有一个接收者，再向 hello 发布。
    publisher
        .write_all(b"*3\r\n$7\r\nPUBLISH\r\n$5\r\nhello\r\n$5\r\nworld\r\n")
        .await
        .unwrap();

    let mut response = [0; 4];
    publisher.read_exact(&mut response).await.unwrap();
    assert_eq!(b":1\r\n", &response);

    // 第一条订阅连接应收到 hello 的推送。
    let mut response = [0; 39];
    sub1.read_exact(&mut response).await.unwrap();
    assert_eq!(
        &b"*3\r\n$7\r\nmessage\r\n$5\r\nhello\r\n$5\r\nworld\r\n"[..],
        &response[..]
    );

    // 第二个订阅连接同时订阅 hello 和 foo。
    let mut sub2 = TcpStream::connect(addr).await.unwrap();
    sub2.write_all(b"*3\r\n$9\r\nSUBSCRIBE\r\n$5\r\nhello\r\n$3\r\nfoo\r\n")
        .await
        .unwrap();

    // 逐个读取订阅确认。
    let mut response = [0; 34];
    sub2.read_exact(&mut response).await.unwrap();
    assert_eq!(
        &b"*3\r\n$9\r\nsubscribe\r\n$5\r\nhello\r\n:1\r\n"[..],
        &response[..]
    );
    let mut response = [0; 32];
    sub2.read_exact(&mut response).await.unwrap();
    assert_eq!(
        &b"*3\r\n$9\r\nsubscribe\r\n$3\r\nfoo\r\n:2\r\n"[..],
        &response[..]
    );

    // 向 hello 发布，此时有两个接收者。
    publisher
        .write_all(b"*3\r\n$7\r\nPUBLISH\r\n$5\r\nhello\r\n$5\r\njazzy\r\n")
        .await
        .unwrap();

    let mut response = [0; 4];
    publisher.read_exact(&mut response).await.unwrap();
    assert_eq!(b":2\r\n", &response);

    // 向 foo 发布，此时只有第二个接收者。
    publisher
        .write_all(b"*3\r\n$7\r\nPUBLISH\r\n$3\r\nfoo\r\n$3\r\nbar\r\n")
        .await
        .unwrap();

    let mut response = [0; 4];
    publisher.read_exact(&mut response).await.unwrap();
    assert_eq!(b":1\r\n", &response);

    // 第一条订阅连接收到 hello 消息。
    let mut response = [0; 39];
    sub1.read_exact(&mut response).await.unwrap();
    assert_eq!(
        &b"*3\r\n$7\r\nmessage\r\n$5\r\nhello\r\n$5\r\njazzy\r\n"[..],
        &response[..]
    );

    // 第二条订阅连接也收到 hello 消息。
    let mut response = [0; 39];
    sub2.read_exact(&mut response).await.unwrap();
    assert_eq!(
        &b"*3\r\n$7\r\nmessage\r\n$5\r\nhello\r\n$5\r\njazzy\r\n"[..],
        &response[..]
    );

    // 在限定时间内检查第一条连接没有收到 foo 消息；这只是该观察窗口的断言。
    let mut response = [0; 1];
    time::timeout(Duration::from_millis(100), sub1.read(&mut response))
        .await
        .unwrap_err();

    // 第二条连接应收到 foo 消息。
    let mut response = [0; 35];
    sub2.read_exact(&mut response).await.unwrap();
    assert_eq!(
        &b"*3\r\n$7\r\nmessage\r\n$3\r\nfoo\r\n$3\r\nbar\r\n"[..],
        &response[..]
    );
}

#[tokio::test]
async fn manage_subscription() {
    let addr = start_server().await;

    let mut publisher = TcpStream::connect(addr).await.unwrap();

    // 建立一条订阅连接，稍后在同一连接上增删频道。
    let mut sub = TcpStream::connect(addr).await.unwrap();
    sub.write_all(b"*2\r\n$9\r\nSUBSCRIBE\r\n$5\r\nhello\r\n")
        .await
        .unwrap();

    // 读取初始确认。
    let mut response = [0; 34];
    sub.read_exact(&mut response).await.unwrap();
    assert_eq!(
        &b"*3\r\n$9\r\nsubscribe\r\n$5\r\nhello\r\n:1\r\n"[..],
        &response[..]
    );

    // 追加订阅 foo，并读取新的数量确认。
    sub.write_all(b"*2\r\n$9\r\nSUBSCRIBE\r\n$3\r\nfoo\r\n")
        .await
        .unwrap();

    let mut response = [0; 32];
    sub.read_exact(&mut response).await.unwrap();
    assert_eq!(
        &b"*3\r\n$9\r\nsubscribe\r\n$3\r\nfoo\r\n:2\r\n"[..],
        &response[..]
    );

    // 取消 hello，保留 foo。
    sub.write_all(b"*2\r\n$11\r\nUNSUBSCRIBE\r\n$5\r\nhello\r\n")
        .await
        .unwrap();

    let mut response = [0; 37];
    sub.read_exact(&mut response).await.unwrap();
    assert_eq!(
        &b"*3\r\n$11\r\nunsubscribe\r\n$5\r\nhello\r\n:1\r\n"[..],
        &response[..]
    );

    // 分别向 hello 与 foo 发布，检查取消是否影响路由。
    publisher
        .write_all(b"*3\r\n$7\r\nPUBLISH\r\n$5\r\nhello\r\n$5\r\nworld\r\n")
        .await
        .unwrap();
    let mut response = [0; 4];
    publisher.read_exact(&mut response).await.unwrap();
    assert_eq!(b":0\r\n", &response);

    publisher
        .write_all(b"*3\r\n$7\r\nPUBLISH\r\n$3\r\nfoo\r\n$3\r\nbar\r\n")
        .await
        .unwrap();
    let mut response = [0; 4];
    publisher.read_exact(&mut response).await.unwrap();
    assert_eq!(b":1\r\n", &response);

    // 当前连接只保留 foo，因此应仅收到 foo 的推送。
    let mut response = [0; 35];
    sub.read_exact(&mut response).await.unwrap();
    assert_eq!(
        &b"*3\r\n$7\r\nmessage\r\n$3\r\nfoo\r\n$3\r\nbar\r\n"[..],
        &response[..]
    );

    // 用有上界的等待检查没有额外消息，避免无限等待否定事件。
    let mut response = [0; 1];
    time::timeout(Duration::from_millis(100), sub.read(&mut response))
        .await
        .unwrap_err();

    // 不带频道参数，取消这条连接的全部频道。
    sub.write_all(b"*1\r\n$11\r\nunsubscribe\r\n")
        .await
        .unwrap();

    let mut response = [0; 35];
    sub.read_exact(&mut response).await.unwrap();
    assert_eq!(
        &b"*3\r\n$11\r\nunsubscribe\r\n$3\r\nfoo\r\n:0\r\n"[..],
        &response[..]
    );
}

// 发送未知命令，精确比较 Error 响应；成功写错误帧不等于服务端函数返回 Err。
#[tokio::test]
async fn send_error_unknown_command() {
    let addr = start_server().await;

    // 建立测试连接。
    let mut stream = TcpStream::connect(addr).await.unwrap();

    // 发送未知命令名称，验证错误文本包含该名称。
    stream
        .write_all(b"*2\r\n$3\r\nFOO\r\n$5\r\nhello\r\n")
        .await
        .unwrap();

    let mut response = [0; 28];

    stream.read_exact(&mut response).await.unwrap();

    assert_eq!(b"-ERR unknown command \'foo\'\r\n", &response);
}

// 进入订阅模式后发送 GET/SET，断言它们被作为不支持的操作拒绝。
#[tokio::test]
async fn send_error_get_set_after_subscribe() {
    let addr = start_server().await;

    let mut stream = TcpStream::connect(addr).await.unwrap();

    // 发送 SUBSCRIBE 并等待确认，明确进入订阅模式。
    stream
        .write_all(b"*2\r\n$9\r\nsubscribe\r\n$5\r\nhello\r\n")
        .await
        .unwrap();

    let mut response = [0; 34];

    stream.read_exact(&mut response).await.unwrap();

    assert_eq!(
        &b"*3\r\n$9\r\nsubscribe\r\n$5\r\nhello\r\n:1\r\n"[..],
        &response[..]
    );

    stream
        .write_all(b"*3\r\n$3\r\nSET\r\n$5\r\nhello\r\n$5\r\nworld\r\n")
        .await
        .unwrap();

    let mut response = [0; 28];

    stream.read_exact(&mut response).await.unwrap();
    assert_eq!(b"-ERR unknown command \'set\'\r\n", &response);

    stream
        .write_all(b"*2\r\n$3\r\nGET\r\n$5\r\nhello\r\n")
        .await
        .unwrap();

    let mut response = [0; 28];

    stream.read_exact(&mut response).await.unwrap();
    assert_eq!(b"-ERR unknown command \'get\'\r\n", &response);
}

// 订阅模式的 PUBLISH 应返回包含 publish 名称的 Error，不能悄悄执行广播。
#[tokio::test]
async fn send_error_publish_after_subscribe() {
    let addr = start_server().await;

    let mut stream = TcpStream::connect(addr).await.unwrap();

    stream
        .write_all(b"*2\r\n$9\r\nsubscribe\r\n$5\r\nhello\r\n")
        .await
        .unwrap();

    let mut response = [0; 34];

    stream.read_exact(&mut response).await.unwrap();

    assert_eq!(
        &b"*3\r\n$9\r\nsubscribe\r\n$5\r\nhello\r\n:1\r\n"[..],
        &response[..]
    );

    stream
        .write_all(b"*3\r\n$7\r\nPUBLISH\r\n$5\r\nhello\r\n$5\r\nworld\r\n")
        .await
        .unwrap();

    let mut response = [0; 32];
    let bytes_read = time::timeout(Duration::from_secs(1), stream.read(&mut response))
        .await
        .unwrap()
        .unwrap();

    assert_eq!(
        b"-ERR unknown command \'publish\'\r\n",
        &response[..bytes_read]
    );
}

async fn start_server() -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    tokio::spawn(async move { server::run(listener, tokio::signal::ctrl_c()).await });

    addr
}
