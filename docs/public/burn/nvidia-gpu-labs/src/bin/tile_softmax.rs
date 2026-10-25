// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// Adapted for this course: f64 CPU reference, finite/length/value/row-sum checks.
// Source: NVIDIA/cuda-rust fc74719 cutile-examples/examples/softmax.rs.
use cutile::prelude::*;

#[cutile::module]
mod kernels {
    use cutile::core::*;

    #[cutile::entry()]
    fn softmax<const BM: i32, const BN: i32>(
        y: &mut Tensor<f32, { [BM, BN] }>,
        x: &Tensor<f32, { [-1, -1] }>,
    ) {
        let tile_x: Tile<f32, { [BM, BN] }> = x.load_like(y);
        let peak: Tile<f32, { [BM] }> = reduce_max(tile_x, 1i32);
        let peak: Tile<f32, { [BM, BN] }> = peak.reshape(shape![BM, 1]).broadcast(y.shape());
        let num: Tile<f32, { [BM, BN] }> = exp(tile_x - peak);
        let denom: Tile<f32, { [BM] }> = reduce_sum(num, 1);
        let denom = denom.reshape(shape![BM, 1]).broadcast(y.shape());
        y.store(num / denom);
    }
}

fn main() -> Result<(), Error> {
    let device = Device::new(0)?;
    let stream = device.new_stream()?;
    let (m, n) = (4, 8);
    let x: Arc<Tensor<f32>> = api::arange::<f32>(m * n)
        .sync_on(&stream)?
        .reshape(&[m, n])?
        .into();
    let y = api::zeros::<f32>(&[m, n]).partition([2, 8]);
    let out: Vec<f32> = kernels::softmax(y, x)
        .first()
        .unpartition()
        .to_host_vec()
        .sync_on(&stream)?;
    assert_eq!(out.len(), m * n);
    let mut max_error = 0.0_f64;
    for row in 0..m {
        let input: Vec<f64> = (0..n).map(|col| (row * n + col) as f64).collect();
        let peak = input.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        let denom: f64 = input.iter().map(|value| (value - peak).exp()).sum();
        for col in 0..n {
            let expected = (input[col] - peak).exp() / denom;
            let actual = f64::from(out[row * n + col]);
            assert!(actual.is_finite());
            let error = (actual - expected).abs();
            max_error = max_error.max(error);
            assert!(
                error <= 1e-6 + 1e-5 * expected.abs(),
                "row {row}, col {col}"
            );
        }
        let sum: f64 = out[row * n..(row + 1) * n]
            .iter()
            .map(|v| f64::from(*v))
            .sum();
        assert!((sum - 1.0).abs() <= 1e-5, "row sum {sum}");
    }
    println!("PASS tile_softmax: {m}x{n}, every value checked, max_abs_error={max_error:e}");
    Ok(())
}
