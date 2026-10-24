use std::path::PathBuf;

use burn::{
    nn::{
        Initializer, Linear, LinearConfig,
        loss::{MseLoss, Reduction},
    },
    optim::{GradientsParams, SgdConfig},
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

fn scalar(value: Tensor<1>) -> f32 {
    value.into_data().try_to_vec::<f32>().unwrap()[0]
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let dir = PathBuf::from(
        std::env::args()
            .nth(1)
            .unwrap_or_else(|| "artifacts/regression".to_string()),
    );
    std::fs::create_dir_all(&dir)?;

    let device = Device::flex().autodiff();
    let config = RegModelConfig {
        input_dim: 1,
        output_dim: 1,
    };
    let mut model = config.init(&device);
    let mut optimizer = SgdConfig::new().init();
    let learning_rate = 0.05_f64;
    let steps = 400;

    let input = Tensor::<2>::from_floats(INPUT, &device);
    let target_values: [[f32; 1]; 8] = INPUT.map(|row| [target_of(row[0])]);
    let targets: Vec<f32> = target_values.iter().map(|row| row[0]).collect();
    let target = Tensor::<2>::from_floats(target_values, &device);

    let loss_fn = MseLoss::new();
    let mut last_loss = f32::NAN;
    for step in 0..steps {
        let prediction = model.forward(input.clone());
        let loss = loss_fn.forward(prediction, target.clone(), Reduction::Mean);
        last_loss = scalar(loss.clone());
        let grads = GradientsParams::from_grads(loss.backward(), &model);
        model = optimizer.step(learning_rate, model, grads);

        if step % 80 == 0 || step + 1 == steps {
            println!("step {:>3}  loss = {:.6}", step + 1, last_loss);
        }
    }

    assert!(
        last_loss.is_finite() && last_loss < 1e-4,
        "training did not converge: loss = {last_loss}"
    );

    // 训练结束后切到推理模式，保存前在固定输入上记录一次预测。
    let model = model.valid();
    let predictions = model
        .forward(input)
        .into_data()
        .try_to_vec::<f32>()
        .unwrap();
    for (prediction, target) in predictions.iter().zip(&targets) {
        assert!(
            (prediction - target).abs() < 1e-3,
            "prediction {prediction} is too far from target {target}"
        );
    }

    config.save(dir.join("model_config.json"))?;
    model
        .clone()
        .save_file(dir.join("model.bpk"))
        .map_err(|error| format!("failed to save parameters: {error}"))?;

    let mut baseline = String::from("# x,target,prediction\n");
    for ((input, target), prediction) in INPUT.iter().zip(&targets).zip(&predictions) {
        baseline.push_str(&format!("{:.6},{:.6},{:.6}\n", input[0], target, prediction));
    }
    std::fs::write(dir.join("baseline.txt"), baseline)?;

    let weights = model
        .linear
        .weight
        .val()
        .into_data()
        .try_to_vec::<f32>()
        .unwrap();
    let bias = model
        .linear
        .bias
        .as_ref()
        .map(|bias| bias.val().into_data().try_to_vec::<f32>().unwrap())
        .unwrap_or_default();

    println!("weights = {weights:?}");
    println!("bias    = {bias:?}");
    println!("predictions = {predictions:?}");
    println!("saved config, parameters and baseline to {}", dir.display());
    Ok(())
}
