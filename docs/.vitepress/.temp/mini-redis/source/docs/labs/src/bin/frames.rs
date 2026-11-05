//! 对应第 04 章：不完整前缀、消费长度与下一帧。
use mini_redis::frame::{Error, Frame};
use std::io::Cursor;

fn main() -> mini_redis::Result<()> {
    let wire = b"*2\r\n$3\r\nGET\r\n$6\r\ncourse\r\n";
    for end in 0..wire.len() {
        let mut cursor = Cursor::new(&wire[..end]);
        assert!(matches!(Frame::check(&mut cursor), Err(Error::Incomplete)));
    }

    let mut cursor = Cursor::new(&wire[..]);
    Frame::check(&mut cursor)?;
    assert_eq!(cursor.position() as usize, wire.len());
    cursor.set_position(0);
    let frame = Frame::parse(&mut cursor)?;
    match &frame {
        Frame::Array(parts) => {
            assert_eq!(parts.len(), 2);
            assert_eq!(parts[0], "GET");
            assert_eq!(parts[1], "course");
        }
        _ => panic!("expected array"),
    }
    println!("完整 GET（{} 字节）：{frame:?}", wire.len());

    let mut null = Cursor::new(&b"$-1\r\n"[..]);
    Frame::check(&mut null)?;
    null.set_position(0);
    assert!(matches!(Frame::parse(&mut null)?, Frame::Null));

    let mut invalid = Cursor::new(&b"$-2\r\n"[..]);
    assert!(matches!(Frame::check(&mut invalid), Err(Error::Other(_))));

    let mut combined = wire.to_vec();
    combined.extend_from_slice(b"+OK\r\n");
    let mut cursor = Cursor::new(&combined[..]);
    Frame::check(&mut cursor)?;
    let consumed = cursor.position() as usize;
    assert_eq!(consumed, wire.len());
    let mut remainder = Cursor::new(&combined[consumed..]);
    Frame::check(&mut remainder)?;
    remainder.set_position(0);
    assert_eq!(Frame::parse(&mut remainder)?, "OK");
    println!("frames OK：全部半帧前缀、完整帧、Null、非法长度、连续帧");
    Ok(())
}
