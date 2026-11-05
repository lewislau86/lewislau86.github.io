// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// Adapted for this course: explicit stream, fixed input, full output assertions.
// Source: NVIDIA/cuda-rust fc74719 README and cutile-examples/async_add.rs.
use cutile::prelude::*;

#[cutile::module]
mod kernels {
    use cutile::core::*;

    #[cutile::entry()]
    fn add<const B: i32>(
        z: &mut Tensor<f32, { [B] }>,
        x: &Tensor<f32, { [-1] }>,
        y: &Tensor<f32, { [-1] }>,
    ) {
        let tx = x.load_like(z);
        let ty = y.load_like(z);
        z.store(tx + ty);
    }
}

fn main() -> Result<(), Error> {
    let device = Device::new(0)?;
    let stream = device.new_stream()?;
    // Deliberately divisible by B; tail masking is a separate experiment.
    const N: usize = 1024;
    let x = api::arange::<f32>(N);
    let y = api::ones::<f32>(&[N]);
    let z = api::zeros::<f32>(&[N]).partition([128]);
    let out: Vec<f32> = kernels::add(z, x, y)
        .first()
        .unpartition()
        .to_host_vec()
        .sync_on(&stream)?;
    assert_eq!(out.len(), N);
    for (i, actual) in out.iter().enumerate() {
        assert_eq!(*actual, i as f32 + 1.0, "element {i}");
    }
    println!("PASS tile_add: all {N} values checked after GPU readback");
    Ok(())
}
