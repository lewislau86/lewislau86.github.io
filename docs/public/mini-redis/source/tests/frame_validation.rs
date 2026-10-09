use mini_redis::frame::{Error, Frame};
use std::io::Cursor;

#[test]
fn check_rejects_invalid_negative_bulk_length() {
    // 合法 Null Bulk：$-1\r\n；此处直接测 Frame::check，不建立 TCP 连接。
    let mut ok = Cursor::new(&b"$-1\r\n"[..]);
    assert!(Frame::check(&mut ok).is_ok());

    // 非法负长度必须返回 Other，不能误当 Incomplete 让 Connection 继续等待字节。
    let mut bad = Cursor::new(&b"$-2\r\n"[..]);
    let err = Frame::check(&mut bad).unwrap_err();

    match err {
        Error::Other(e) => {
            assert_eq!(e.to_string(), "protocol error; invalid frame format");
        }
        Error::Incomplete => panic!("expected protocol error, got incomplete"),
    }
}
