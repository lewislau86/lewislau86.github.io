//! 对应第 02、06 章：持有值、借用键、共享资源。
use bytes::Bytes;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

#[derive(Debug)]
struct Entry {
    data: Bytes,
}

fn lookup<'a>(table: &'a HashMap<String, Entry>, key: &str) -> Option<&'a Entry> {
    // 返回引用来自 table，而不是 key；生命周期注解表达这一依赖。
    table.get(key)
}

fn main() {
    let key = String::from("course");
    let independent_key = key.clone();
    let data = Bytes::from_static(b"rust");
    let shared_bytes = data.clone();
    let mut table = HashMap::new();

    // key 和 data 移入表，调用之后不能再使用原变量。
    table.insert(key, Entry { data });
    let entry = lookup(&table, &independent_key).expect("key exists");
    assert_eq!(entry.data, shared_bytes);
    assert_eq!("中".len(), 3);
    println!("借用查询：{:?}", entry.data);

    let shared = Arc::new(Mutex::new(table));
    let second_handle = Arc::clone(&shared);
    assert_eq!(Arc::strong_count(&shared), 2);
    {
        let mut table = second_handle.lock().unwrap();
        table.insert(
            String::from("next"),
            Entry {
                data: Bytes::from_static(b"tokio"),
            },
        );
    } // Guard 在此释放并解锁。
    assert_eq!(shared.lock().unwrap().len(), 2);
    drop(second_handle);
    assert_eq!(Arc::strong_count(&shared), 1);
    println!("ownership OK：移动、借用、Bytes 克隆、Arc 共享、Guard 解锁");
}
