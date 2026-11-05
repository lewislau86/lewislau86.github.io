use std::hint::black_box;
use std::time::Instant;

const N: usize = 4_000_000;

fn add_chunk(a: &[f32], b: &[f32], out: &mut [f32]) {
    for ((slot, lhs), rhs) in out.iter_mut().zip(a).zip(b) {
        *slot = lhs + rhs;
    }
}

fn main() {
    let a = vec![1.5_f32; N];
    let b = vec![2.25_f32; N];
    let mut out = vec![0.0_f32; N];

    // 单线程：一个执行项处理全部元素。
    let start = Instant::now();
    add_chunk(&a, &b, &mut out);
    black_box(&out);
    let single = start.elapsed();

    // 多线程：把数组切成多个块，模拟“多个工作项分别处理不同位置”。
    // 这里用 CPU 线程演示工作划分；真正的 GPU 内核把同样的思路映射到设备线程。
    let threads = 4;
    let chunk = N / threads;
    let start = Instant::now();
    std::thread::scope(|scope| {
        for (index, out_chunk) in out.chunks_mut(chunk).enumerate() {
            let begin = index * chunk;
            let end = begin + out_chunk.len();
            let a_chunk = &a[begin..end];
            let b_chunk = &b[begin..end];
            scope.spawn(move || add_chunk(a_chunk, b_chunk, out_chunk));
        }
    });
    black_box(&out);
    let parallel = start.elapsed();

    let speedup = single.as_secs_f64() / parallel.as_secs_f64();
    println!("elements = {N}, threads = {threads}");
    println!("single-thread: {:.3} ms", single.as_secs_f64() * 1e3);
    println!("multi-thread:  {:.3} ms", parallel.as_secs_f64() * 1e3);
    println!("speedup: {speedup:.2}x (CPU simulation, not a GPU benchmark)");
    println!("note: a GPU uses many work items; startup and memory bandwidth still set the lower bound.");
}
