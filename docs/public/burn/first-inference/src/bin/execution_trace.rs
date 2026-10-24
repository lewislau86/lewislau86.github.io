use std::hint::black_box;
use std::time::{Duration, Instant};

use burn::{prelude::*, tensor::Distribution};

const SIZE: usize = 256;
const REPEATS: usize = 20;

fn median(mut values: Vec<Duration>) -> Duration {
    values.sort_unstable();
    values[values.len() / 2]
}

fn main() {
    let device = Device::flex();
    let lhs = Tensor::<2>::random([SIZE, SIZE], Distribution::Default, &device);
    let rhs = Tensor::<2>::random([SIZE, SIZE], Distribution::Default, &device);

    // 预热：首次分配、首次 kernel 初始化不计入下面的中位数。
    for _ in 0..3 {
        let product = lhs.clone().matmul(rhs.clone());
        let _ = black_box(product);
    }
    device.sync().expect("device sync failed");

    let mut submit = Vec::with_capacity(REPEATS);
    for _ in 0..REPEATS {
        let start = Instant::now();
        let product = lhs.clone().matmul(rhs.clone());
        black_box(&product);
        submit.push(start.elapsed());
    }
    device.sync().expect("device sync failed");

    let mut readback = Vec::with_capacity(REPEATS);
    for _ in 0..REPEATS {
        let start = Instant::now();
        let product = lhs.clone().matmul(rhs.clone());
        let values = product.into_data().try_to_vec::<f32>().unwrap();
        black_box(values.iter().sum::<f32>());
        readback.push(start.elapsed());
    }

    let submit = median(submit);
    let readback = median(readback);
    let flops = 2.0 * (SIZE * SIZE * SIZE) as f64;
    let gflops = flops / readback.as_secs_f64() / 1e9;

    println!("matrix: {SIZE} x {SIZE}, dtype f32, device Flex CPU");
    println!("submit median:   {:.3} ms", submit.as_secs_f64() * 1e3);
    println!("readback median: {:.3} ms", readback.as_secs_f64() * 1e3);
    println!("approx {gflops:.2} GFLOPS (readback path)");
    println!("note: CPU backends may execute synchronously; compare the two phases, not absolute numbers.");
}
