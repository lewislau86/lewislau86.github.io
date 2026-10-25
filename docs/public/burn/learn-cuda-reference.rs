//! 第 5/18 章的独立 Rust CPU 数学参考，只依赖标准库。
//! rustc --edition=2021 learn-cuda-reference.rs -o learn-cuda-reference
//! ./learn-cuda-reference
//! 本程序不执行 CUDA，也不模拟 GPU 同步、BF16/FP8 舍入或硬件性能。

type Matrix = Vec<Vec<f64>>;

fn vector_add(a: &[f64], b: &[f64]) -> Result<Vec<f64>, &'static str> {
    if a.len() != b.len() {
        return Err("length mismatch");
    }
    Ok(a.iter().zip(b).map(|(x, y)| x + y).collect())
}

fn shape(a: &Matrix) -> (usize, usize) {
    assert!(
        !a.is_empty() && !a[0].is_empty(),
        "nonempty matrix required"
    );
    assert!(a.iter().all(|row| row.len() == a[0].len()));
    (a.len(), a[0].len())
}

fn matmul(a: &Matrix, b: &Matrix) -> Matrix {
    let (m, k) = shape(a);
    let (kb, n) = shape(b);
    assert_eq!(k, kb, "inner dimensions mismatch");
    (0..m)
        .map(|i| {
            (0..n)
                .map(|j| (0..k).map(|t| a[i][t] * b[t][j]).sum())
                .collect()
        })
        .collect()
}

fn tiled_matmul(a: &Matrix, b: &Matrix, tile: usize) -> Matrix {
    let (m, k) = shape(a);
    let (kb, n) = shape(b);
    assert!(k == kb && tile > 0);
    let mut out = vec![vec![0.0; n]; m];
    for i0 in (0..m).step_by(tile) {
        for j0 in (0..n).step_by(tile) {
            for k0 in (0..k).step_by(tile) {
                for i in i0..(i0 + tile).min(m) {
                    for j in j0..(j0 + tile).min(n) {
                        for t in k0..(k0 + tile).min(k) {
                            out[i][j] += a[i][t] * b[t][j];
                        }
                    }
                }
            }
        }
    }
    out
}

fn tree_sum(values: &[f64]) -> f64 {
    let mut work = values.to_vec();
    while work.len() > 1 {
        work = work.chunks(2).map(|chunk| chunk.iter().sum()).collect();
    }
    work.first().copied().unwrap_or(0.0)
}

fn normalizer(values: &[f64]) -> Result<Option<(f64, f64)>, &'static str> {
    if !values.iter().all(|x| x.is_finite()) {
        return Err("finite inputs required");
    }
    if values.is_empty() {
        return Ok(None); // 显式空状态，避免 -inf - (-inf)。
    }
    let peak = values.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    Ok(Some((peak, values.iter().map(|x| (x - peak).exp()).sum())))
}

fn merge(a: Option<(f64, f64)>, b: Option<(f64, f64)>) -> Option<(f64, f64)> {
    match (a, b) {
        (None, state) | (state, None) => state,
        (Some((ma, la)), Some((mb, lb))) => {
            let peak = ma.max(mb);
            Some((peak, la * (ma - peak).exp() + lb * (mb - peak).exp()))
        }
    }
}

fn safe_softmax(values: &[f64]) -> Result<Vec<f64>, &'static str> {
    let (peak, denom) = normalizer(values)?.ok_or("nonempty row required")?;
    Ok(values.iter().map(|x| (x - peak).exp() / denom).collect())
}

fn online_softmax(values: &[f64], tile: usize) -> Vec<f64> {
    assert!(tile > 0 && !values.is_empty());
    let state = values.chunks(tile).fold(None, |state, part| {
        merge(state, normalizer(part).expect("finite inputs"))
    });
    let (peak, denom) = state.unwrap();
    values.iter().map(|x| (x - peak).exp() / denom).collect()
}

fn attention_shape(q: &Matrix, k: &Matrix, v: &Matrix, causal: bool) -> (usize, usize) {
    let (lq, dim) = shape(q);
    let (lkv, kd) = shape(k);
    let (lv, dv) = shape(v);
    assert!(dim == kd && lv == lkv && (!causal || lq == lkv));
    (dim, dv)
}

fn attention_dense(q: &Matrix, k: &Matrix, v: &Matrix, causal: bool) -> Matrix {
    let (dim, dv) = attention_shape(q, k, v, causal);
    q.iter()
        .enumerate()
        .map(|(i, query)| {
            let count = if causal { i + 1 } else { k.len() };
            let scores: Vec<f64> = k[..count]
                .iter()
                .map(|key| {
                    query.iter().zip(key).map(|(x, y)| x * y).sum::<f64>() / (dim as f64).sqrt()
                })
                .collect();
            let p = safe_softmax(&scores).unwrap();
            (0..dv)
                .map(|d| (0..count).map(|j| p[j] * v[j][d]).sum())
                .collect()
        })
        .collect()
}

fn attention_tiled(q: &Matrix, k: &Matrix, v: &Matrix, tile: usize, causal: bool) -> Matrix {
    let (dim, dv) = attention_shape(q, k, v, causal);
    assert!(tile > 0);
    q.iter()
        .enumerate()
        .map(|(i, query)| {
            let limit = if causal { i + 1 } else { k.len() };
            let mut state: Option<(f64, f64)> = None;
            let mut accum = vec![0.0; dv];
            for start in (0..limit).step_by(tile) {
                let end = (start + tile).min(limit);
                let scores: Vec<f64> = (start..end)
                    .map(|j| {
                        (0..dim).map(|d| query[d] * k[j][d]).sum::<f64>() / (dim as f64).sqrt()
                    })
                    .collect();
                let block_peak = scores.iter().copied().fold(f64::NEG_INFINITY, f64::max);
                let peak = state.map_or(block_peak, |(old, _)| old.max(block_peak));
                let alpha = state.map_or(0.0, |(old, _)| (old - peak).exp());
                let weights: Vec<f64> = scores.iter().map(|x| (x - peak).exp()).collect();
                for d in 0..dv {
                    accum[d] = alpha * accum[d]
                        + (start..end)
                            .map(|j| weights[j - start] * v[j][d])
                            .sum::<f64>();
                }
                let denom = alpha * state.map_or(0.0, |(_, l)| l) + weights.iter().sum::<f64>();
                state = Some((peak, denom));
            }
            let (_, denom) = state.unwrap();
            accum.iter().map(|x| x / denom).collect()
        })
        .collect()
}

fn blur_direct(image: &Matrix, width: usize) -> Matrix {
    let (h, w) = shape(image);
    assert!(width > 0 && width % 2 == 1);
    let radius = width / 2;
    (0..h)
        .map(|i| {
            (0..w)
                .map(|j| {
                    (i.saturating_sub(radius)..(i + radius + 1).min(h))
                        .flat_map(|y| {
                            (j.saturating_sub(radius)..(j + radius + 1).min(w))
                                .map(move |x| image[y][x])
                        })
                        .sum::<f64>()
                        / (width * width) as f64
                })
                .collect()
        })
        .collect()
}

fn sliding_mean(row: &[f64], width: usize) -> Vec<f64> {
    assert!(width > 0 && width % 2 == 1);
    let radius = width / 2;
    let mut total: f64 = row.iter().take(radius).sum();
    let mut out = Vec::with_capacity(row.len());
    for i in 0..row.len() {
        if i + radius < row.len() {
            total += row[i + radius];
        }
        out.push(total / width as f64);
        if i >= radius {
            total -= row[i - radius];
        }
    }
    out
}

fn blur_separable(image: &Matrix, width: usize) -> Matrix {
    let (h, w) = shape(image);
    let horizontal: Matrix = image.iter().map(|row| sliding_mean(row, width)).collect();
    let columns: Matrix = (0..w)
        .map(|j| sliding_mean(&(0..h).map(|i| horizontal[i][j]).collect::<Vec<_>>(), width))
        .collect();
    (0..h)
        .map(|i| (0..w).map(|j| columns[j][i]).collect())
        .collect()
}

fn fp6_decode(code: u8) -> f64 {
    assert!(code < 64);
    let exponent = (code >> 2) & 7;
    let mantissa = code & 3;
    let magnitude = if exponent == 0 {
        f64::from(mantissa) / 16.0
    } else {
        2.0_f64.powi(i32::from(exponent) - 3) * (1.0 + f64::from(mantissa) / 4.0)
    };
    if code & 32 != 0 {
        -magnitude
    } else {
        magnitude
    }
}

fn fp6_encode(value: f64) -> Result<u8, &'static str> {
    if !value.is_finite() || value.abs() >= 30.0 {
        return Err("finite abs(value) < 30 required");
    }
    let sign = if value.is_sign_negative() { 32 } else { 0 };
    // 独立穷举数学参考。相同距离时，最低位为 0 的编码胜出。
    let code = (0u8..32)
        .min_by(|&a, &b| {
            let da = (fp6_decode(a) - value.abs()).abs();
            let db = (fp6_decode(b) - value.abs()).abs();
            da.total_cmp(&db).then_with(|| (a & 1).cmp(&(b & 1)))
        })
        .unwrap();
    Ok(sign | code)
}

fn fp6_pack(codes: &[u8]) -> Result<Vec<u8>, &'static str> {
    if codes.len() % 4 != 0 || codes.iter().any(|&c| c >= 64) {
        return Err("four six-bit codes per group required");
    }
    Ok(codes
        .chunks(4)
        .flat_map(|c| {
            // aaaaaabb bbbbcccc ccdddddd：与 learn-cuda 的高位优先布局一致。
            [
                (c[0] << 2) | (c[1] >> 4),
                (c[1] << 4) | (c[2] >> 2),
                (c[2] << 6) | c[3],
            ]
        })
        .collect())
}

fn fp6_unpack(data: &[u8]) -> Result<Vec<u8>, &'static str> {
    if data.len() % 3 != 0 {
        return Err("three bytes per group required");
    }
    Ok(data
        .chunks(3)
        .flat_map(|b| {
            [
                b[0] >> 2,
                ((b[0] & 3) << 4) | (b[1] >> 4),
                ((b[1] & 15) << 2) | (b[2] >> 6),
                b[2] & 63,
            ]
        })
        .collect())
}

fn row_scaled_mm(a: &Matrix, b: &Matrix, sa: &[f64], sb: &[f64]) -> Matrix {
    let mut out = matmul(a, b);
    assert!(sa.len() == out.len() && sb.len() == out[0].len());
    for (i, row) in out.iter_mut().enumerate() {
        for (j, value) in row.iter_mut().enumerate() {
            *value *= sa[i] * sb[j];
        }
    }
    out
}

fn close(a: f64, b: f64) {
    assert!(a.is_finite() && b.is_finite());
    assert!(
        (a - b).abs() <= 1e-10 * (1.0 + a.abs().max(b.abs())),
        "{a} != {b}"
    );
}

fn close_vec(a: &[f64], b: &[f64]) {
    assert_eq!(a.len(), b.len());
    for (&x, &y) in a.iter().zip(b) {
        close(x, y);
    }
}

fn close_matrix(a: &Matrix, b: &Matrix) {
    assert_eq!(a.len(), b.len());
    for (x, y) in a.iter().zip(b) {
        close_vec(x, y);
    }
}

struct Rng(u32);
impl Rng {
    fn value(&mut self) -> f64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 17;
        self.0 ^= self.0 << 5;
        f64::from(self.0) / f64::from(u32::MAX) * 4.0 - 2.0
    }
    fn matrix(&mut self, rows: usize, cols: usize) -> Matrix {
        (0..rows)
            .map(|_| (0..cols).map(|_| self.value()).collect())
            .collect()
    }
}

fn main() {
    let mut rng = Rng(20261025);
    assert!(vector_add(&[], &[]).unwrap().is_empty());
    close_vec(
        &vector_add(&[1.0, -2.0, 3.0], &[4.0, 2.0, -1.0]).unwrap(),
        &[5.0, 0.0, 2.0],
    );
    assert!(vector_add(&[1.0], &[]).is_err());
    println!("PASS vector addition: values, empty input, length contract");

    let a = vec![vec![1.0, 2.0, 3.0], vec![4.0, 5.0, 6.0]];
    let b = vec![vec![1.0, 2.0], vec![3.0, 4.0], vec![5.0, 6.0]];
    close_matrix(&matmul(&a, &b), &vec![vec![22.0, 28.0], vec![49.0, 64.0]]);
    for (m, n, k) in [(1, 1, 1), (3, 5, 7), (4, 2, 3)] {
        let a = rng.matrix(m, k);
        let b = rng.matrix(k, n);
        for tile in [1, 2, 4, 8] {
            close_matrix(&tiled_matmul(&a, &b, tile), &matmul(&a, &b));
        }
    }
    println!("PASS matmul: fixed values, rectangular shapes, partial tiles");

    for size in [0, 1, 7, 32, 1001] {
        let values: Vec<f64> = (0..size).map(|_| rng.value()).collect();
        close(tree_sum(&values), values.iter().sum());
    }
    println!("PASS reduction: empty identity, odd lengths, reference sums");

    for values in [
        vec![1000.0, 1001.0],
        vec![-1000.0, -1001.0],
        vec![2.0; 17],
        (0..101).map(|_| rng.value() * 25.0).collect(),
    ] {
        let reference = safe_softmax(&values).unwrap();
        close(reference.iter().sum(), 1.0);
        close_vec(
            &safe_softmax(&values.iter().map(|x| x + 1000.0).collect::<Vec<_>>()).unwrap(),
            &reference,
        );
        for tile in [1, 2, 7, 128] {
            close_vec(&online_softmax(&values, tile), &reference);
        }
        let combined = merge(
            normalizer(&values[..1]).unwrap(),
            normalizer(&values[1..]).unwrap(),
        )
        .unwrap();
        let full = normalizer(&values).unwrap().unwrap();
        close(combined.0, full.0);
        close(combined.1, full.1);
    }
    assert!(safe_softmax(&[]).is_err());
    assert!(safe_softmax(&[f64::NEG_INFINITY]).is_err());
    println!("PASS softmax: stability, shift, split states, empty/nonfinite rejection");

    // causal 只是额外数学参考，不代表 learn-cuda 上游 kernel 支持 causal。
    for (lq, lkv, dim, dv) in [(1, 7, 3, 2), (5, 9, 4, 3), (7, 7, 3, 5)] {
        let q = rng.matrix(lq, dim);
        let k = rng.matrix(lkv, dim);
        let v = rng.matrix(lkv, dv);
        for causal in [false, true].into_iter().filter(|&c| !c || lq == lkv) {
            for tile in [1, 2, 4, 16] {
                close_matrix(
                    &attention_tiled(&q, &k, &v, tile, causal),
                    &attention_dense(&q, &k, &v, causal),
                );
            }
        }
    }
    println!("PASS attention: dense/tiled m-l-u, unequal lengths, causal reference");

    close_matrix(
        &blur_direct(&vec![vec![1.0, 2.0], vec![3.0, 4.0]], 3),
        &vec![vec![10.0 / 9.0; 2]; 2],
    );
    for (h, w) in [(1, 1), (2, 3), (7, 9)] {
        let image = rng.matrix(h, w);
        for width in [1, 3, 5] {
            close_matrix(&blur_separable(&image, width), &blur_direct(&image, width));
        }
    }
    println!("PASS box blur: zero padding, corners, separable sliding windows");

    for code in 0u8..64 {
        assert_eq!(fp6_encode(fp6_decode(code)).unwrap(), code);
    }
    for low in 0u8..31 {
        let midpoint = (fp6_decode(low) + fp6_decode(low + 1)) / 2.0;
        let even = if low % 2 == 0 { low } else { low + 1 };
        assert_eq!(fp6_encode(midpoint).unwrap(), even);
        assert_eq!(fp6_encode(-midpoint).unwrap(), even | 32);
    }
    assert_eq!(fp6_encode(1.125).unwrap(), 12);
    assert_eq!(fp6_encode(1.375).unwrap(), 14);
    assert_eq!(fp6_decode(31), 28.0);
    assert_eq!(fp6_decode(1), 1.0 / 16.0);
    assert_eq!(fp6_pack(&[0, 1, 2, 3]).unwrap(), [0x00, 0x10, 0x83]);
    let codes: Vec<u8> = (0..64).collect();
    assert_eq!(fp6_unpack(&fp6_pack(&codes).unwrap()).unwrap(), codes);
    for bad in [30.0, -30.0, f64::INFINITY, f64::NEG_INFINITY, f64::NAN] {
        assert!(fp6_encode(bad).is_err());
    }
    assert!(fp6_pack(&[1, 2]).is_err());
    assert!(fp6_unpack(&[1, 2]).is_err());
    println!("PASS FP6: all 64 codes, signed zero, ties-even, packed layout, invalid values");

    close_matrix(
        &row_scaled_mm(
            &vec![vec![1.0, 2.0], vec![3.0, 4.0]],
            &vec![vec![1.0, 0.0], vec![0.0, 2.0]],
            &[0.5, 1.0],
            &[2.0, 0.25],
        ),
        &vec![vec![1.0, 0.5], vec![6.0, 2.0]],
    );
    close_matrix(
        &matmul(
            &vec![vec![1.0, 2.0, 3.0]],
            &vec![vec![1.0, 4.0], vec![2.0, 5.0], vec![3.0, 6.0]],
        ),
        &vec![vec![14.0, 32.0]],
    );
    println!("PASS row-scaled matmul and GEMV: axes, broadcasting, fixed outputs");
    println!("8 groups passed. Rust CPU math only; GPU execution is NOT verified.");
}
