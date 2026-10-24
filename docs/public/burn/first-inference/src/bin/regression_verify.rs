use std::path::PathBuf;

use burn::{
    nn::{Initializer, Linear, LinearConfig},
    prelude::*,
};

#[derive(Module, Debug)]
struct RegModel {
    linear: Linear,
}

#[derive(Config, Debug)]
struct RegModelConfig {
    input_dim: usize,
    output_dim: usize,
}

impl RegModelConfig {
    fn init(&self, device: &Device) -> RegModel {
        RegModel {
            linear: LinearConfig::new(self.input_dim, self.output_dim)
                .with_initializer(Initializer::Constant { value: 0.5 })
                .init(device),
        }
    }
}

impl RegModel {
    fn forward(&self, input: Tensor<2>) -> Tensor<2> {
        self.linear.forward(input)
    }
}

const INPUT: [[f32; 1]; 8] = [
    [-2.0],
    [-1.0],
    [0.0],
    [1.0],
    [2.0],
    [3.0],
    [4.0],
    [5.0],
];

fn target_of(x: f32) -> f32 {
    2.0 * x + 1.0
}

struct BaselineRow {
    x: f32,
    target: f32,
    prediction: f32,
}

fn read_baseline(path: &std::path::Path) -> Result<Vec<BaselineRow>, Box<dyn std::error::Error>> {
    let content = std::fs::read_to_string(path)?;
    let mut rows = Vec::new();
    for (index, line) in content.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let fields: Vec<&str> = line.split(',').collect();
        if fields.len() != 3 {
            return Err(format!("line {}: expected x,target,prediction", index + 1).into());
        }
        rows.push(BaselineRow {
            x: fields[0].parse()?,
            target: fields[1].parse()?,
            prediction: fields[2].parse()?,
        });
    }
    Ok(rows)
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let dir = PathBuf::from(
        std::env::args()
            .nth(1)
            .unwrap_or_else(|| "artifacts/regression".to_string()),
    );
    let config_path = dir.join("model_config.json");
    let params_path = dir.join("model.bpk");
    let baseline_path = dir.join("baseline.txt");

    // 只从文件创建结构、读取参数，不重新训练，也不共享训练进程的内存对象。
    let config = RegModelConfig::load(&config_path)?;
    let device = Device::flex();
    let model = config
        .init(&device)
        .try_load_file(&params_path)
        .map_err(|error| format!("failed to load parameters: {error}"))?;
    let model = model.valid();

    let input = Tensor::<2>::from_floats(INPUT, &device);
    let predictions = model
        .forward(input)
        .into_data()
        .try_to_vec::<f32>()
        .unwrap();
    let baseline = read_baseline(&baseline_path)?;

    assert_eq!(predictions.len(), baseline.len());
    let mut max_roundtrip = 0.0_f32;
    let mut max_target = 0.0_f32;
    for (index, (prediction, row)) in predictions.iter().zip(&baseline).enumerate() {
        let expected = row.target;
        assert!(
            (row.x - INPUT[index][0]).abs() < 1e-6,
            "row {index}: baseline input does not match the fixed input"
        );
        assert!(
            (expected - target_of(row.x)).abs() < 1e-6,
            "row {index}: baseline target is not 2x+1"
        );
        max_roundtrip = max_roundtrip.max((prediction - row.prediction).abs());
        max_target = max_target.max((prediction - expected).abs());
        println!(
            "x = {:>4.1}  loaded = {:>8.5}  saved = {:>8.5}  target = {:>8.5}",
            row.x, prediction, row.prediction, expected
        );
        assert!(
            (prediction - row.prediction).abs() < 1e-4,
            "row {index}: loaded prediction differs from saved baseline"
        );
        assert!(
            (prediction - expected).abs() < 1e-3,
            "row {index}: loaded prediction is too far from target"
        );
    }

    println!("max |loaded - saved|  = {max_roundtrip:.6}");
    println!("max |loaded - target| = {max_target:.6}");
    println!("OK: reloaded model reproduces the baseline and the target function");
    Ok(())
}
