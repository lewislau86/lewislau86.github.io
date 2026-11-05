use burn::tensor::{Device, Tensor, activation::relu};

fn main() {
    // Flex 在 CPU 上执行，不需要配置 GPU。
    let device = Device::flex();
    let x = Tensor::<2>::from_floats([[1.0, 2.0]], &device);
    let w = Tensor::<2>::from_floats([[1.0, -1.0], [2.0, 1.0]], &device);
    // 用 [1, 2] 表示一行偏置，便于直观看到批次维的广播。
    let b = Tensor::<2>::from_floats([[0.0, 1.0]], &device);

    let h = relu(x.matmul(w) + b);
    assert_eq!(h.dims(), [1, 2]);
    let values = h.into_data().try_to_vec::<f32>().unwrap();
    assert_eq!(values, vec![5.0, 2.0]);
    println!("H = {values:?}");
}
