//! 第 05 章：显式创建 runtime，观察 Future 的创建与执行顺序。
use tokio::time::{sleep, Duration};

async fn stage(name: &'static str) -> &'static str {
    println!("执行 {name}");
    sleep(Duration::from_millis(1)).await;
    name
}

fn main() -> mini_redis::Result<()> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;

    runtime.block_on(async {
        let first = stage("SET");
        let second = stage("GET");
        println!("两个 Future 已创建，函数体尚未执行");

        let first_result = first.await;
        println!("{first_result} 完成后才开始等待第二个 Future");
        let second_result = second.await;
        assert_eq!((first_result, second_result), ("SET", "GET"));

        // 尚未被轮询的 async fn Future 被丢弃，函数体不会开始执行。
        let unused = stage("不应出现的阶段");
        drop(unused);
        println!("async_basics OK：创建、依次执行、丢弃未执行 Future");
    });
    Ok(())
}
