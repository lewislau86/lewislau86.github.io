use std::hint::black_box;
use std::time::Instant;

use burn::prelude::*;

const N: usize = 1_000_000;
const REPEATS: usize = 10;

fn main() {
    let device = Device::flex();
    let a_host = vec![1.5_f32; N];
    let b_host = vec![2.5_f32; N];
    let c_host = vec![3.0_f32; N];
    let a = Tensor::<1>::from_data(TensorData::from(a_host.as_slice()), &device);
    let b = Tensor::<1>::from_data(TensorData::from(b_host.as_slice()), &device);
    let c = Tensor::<1>::from_data(TensorData::from(c_host.as_slice()), &device);

    // 预热
    for _ in 0..2 {
        let y = (a.clone() + b.clone()) * c.clone();
        black_box(y);
    }
    let start = Instant::now();
    for _ in 0..REPEATS {
        // 朴素写法：加法产生一个临时张量，乘法再产生一个。
        let y = (a.clone() + b.clone()) * c.clone();
        black_box(y);
    }
    let eager = start.elapsed() / REPEATS as u32;

    // 手工融合：一次遍历完成 (a+b)*c，不产生中间数组。
    let mut out = vec![0.0_f32; N];
    let start = Instant::now();
    for _ in 0..REPEATS {
        for index in 0..N {
            out[index] = (a_host[index] + b_host[index]) * c_host[index];
        }
        black_box(&out);
    }
    let fused = start.elapsed() / REPEATS as u32;

    println!("elements = {N}, repeats = {REPEATS}");
    println!("Burn eager (a + b) * c: {:.3} ms/iter", eager.as_secs_f64() * 1e3);
    println!("manual fused loop:      {:.3} ms/iter", fused.as_secs_f64() * 1e3);
    println!("note: this compares an eager graph with a hand-written loop; it is not a kernel benchmark.");
}
