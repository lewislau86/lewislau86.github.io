// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// Adapted for this course: small matrices, nonuniform inputs, every value checked.
// Source: NVIDIA/cuda-rust fc74719 cutile-examples/examples/gemm.rs.
use cutile::prelude::*;

#[cutile::module]
mod kernels {
    use cutile::core::*;

    #[cutile::entry()]
    fn matmul<const BM: i32, const BN: i32, const BK: i32, const K: i32>(
        z: &mut Tensor<f32, { [BM, BN] }>,
        x: &Tensor<f32, { [-1, K] }>,
        y: &Tensor<f32, { [K, -1] }>,
    ) {
        let part_x = x.partition(shape![BM, BK]);
        let part_y = y.partition(shape![BK, BN]);
        let pid: (i32, i32, i32) = get_tile_block_id();
        let mut tile_z = load_tile_mut(z);
        for i in 0i32..(K / BK) {
            tile_z = mma(part_x.load([pid.0, i]), part_y.load([i, pid.1]), tile_z);
        }
        z.store(tile_z);
    }
}

fn main() -> Result<(), Error> {
    let device = Device::new(0)?;
    let stream = device.new_stream()?;
    // Fixed divisible shape: no claim of arbitrary K or masked tail support.
    let (m, n, k) = (32, 32, 16);
    let (bm, bn, bk) = (16, 16, 8);
    assert!(m % bm == 0 && n % bn == 0 && k % bk == 0);
    let x: Arc<Tensor<f32>> = api::arange::<f32>(m * k)
        .sync_on(&stream)?
        .reshape(&[m, k])?
        .into();
    let y: Arc<Tensor<f32>> = api::arange::<f32>(k * n)
        .sync_on(&stream)?
        .reshape(&[k, n])?
        .into();
    let z = api::zeros::<f32>(&[m, n]).partition([bm, bn]);
    let generics = [bm, bn, bk, k].map(|v| v.to_string()).to_vec();
    let out: Vec<f32> = kernels::matmul(z, x, y)
        .generics(generics)
        .first()
        .unpartition()
        .to_host_vec()
        .sync_on(&stream)?;
    assert_eq!(out.len(), m * n);
    let mut max_error = 0.0_f64;
    for row in 0..m {
        for col in 0..n {
            let expected: f64 = (0..k)
                .map(|t| (row * k + t) as f64 * (t * n + col) as f64)
                .sum();
            let actual = f64::from(out[row * n + col]);
            assert!(actual.is_finite());
            let error = (actual - expected).abs();
            max_error = max_error.max(error);
            assert!(
                error <= 1e-3 + 1e-5 * expected.abs(),
                "row {row}, col {col}"
            );
        }
    }
    println!(
        "PASS tile_matmul: {m}x{k} @ {k}x{n}, all values checked, max_abs_error={max_error:e}"
    );
    Ok(())
}
