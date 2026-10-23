use burn::{
    module::{Module, Param},
    nn::{Linear, LinearConfig},
    tensor::{Device, Tensor, activation::relu},
};

#[derive(Module, Debug)]
struct TinyModel {
    linear: Linear,
}

impl TinyModel {
    fn new(device: &Device) -> Self {
        let mut linear = LinearConfig::new(2, 2).init(device);
        // 覆盖随机初始化，使输出能与书中的手算逐项比较。
        linear.weight =
            Param::from_tensor(Tensor::<2>::from_floats([[1.0, -1.0], [2.0, 1.0]], device));
        linear.bias = Some(Param::from_tensor(Tensor::<1>::from_floats(
            [0.0, 1.0],
            device,
        )));
        Self { linear }
    }

    fn forward(&self, x: Tensor<2>) -> Tensor<2> {
        relu(self.linear.forward(x))
    }
}

fn main() {
    let device = Device::flex();
    let model = TinyModel::new(&device).valid();
    let x = Tensor::<2>::from_floats([[1.0, 2.0]], &device);
    let values = model.forward(x).into_data().try_to_vec::<f32>().unwrap();
    assert_eq!(values, vec![5.0, 2.0]);
    assert_eq!(model.num_params(), 6);
    println!("Module H = {values:?}; parameters = {}", model.num_params());
}
