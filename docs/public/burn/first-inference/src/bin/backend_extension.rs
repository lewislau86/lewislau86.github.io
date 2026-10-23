use burn::{
    backend::{
        Autodiff, Dispatch, Flex, autodiff::checkpoint::strategy::CheckpointStrategy,
        backend_extension, tensor::FloatTensor,
    },
    tensor::{Device, Tensor},
};

// 第 1 层：声明低层操作，并用已有原语描述 f(x) = x² + x。
// 这里是逐元素计算，输入和输出的形状相同。
#[backend_extension(Autodiff, Flex)]
pub trait SquarePlusInputBackend: burn::backend::Backend {
    fn square_plus_input(input: FloatTensor<Self>) -> FloatTensor<Self> {
        let squared = Self::float_mul(input.clone(), input.clone());
        Self::float_add(squared, input)
    }
}

// 第 2 层：Flex 直接复用上面的默认实现。
impl SquarePlusInputBackend for Flex {}

// Autodiff 也复用默认实现；其中的乘法和加法会记录各自的反向传播。
// 宏负责生成 Dispatch 路由，并不会替自定义内核推导梯度。
impl<B: SquarePlusInputBackend, C: CheckpointStrategy> SquarePlusInputBackend for Autodiff<B, C> {}

// 第 3 层：对模型使用者只暴露 Tensor<D>，不要求其传入后端类型参数。
pub fn square_plus_input<const D: usize>(input: Tensor<D>) -> Tensor<D> {
    Tensor::from_dispatch(Dispatch::square_plus_input(input.into_dispatch()))
}

fn values<const D: usize>(tensor: Tensor<D>) -> Vec<f32> {
    tensor.into_data().try_to_vec::<f32>().unwrap()
}

fn main() {
    // 1. 普通 CPU 前向：逐个元素验证 f(x) = x² + x。
    let device = Device::flex();
    let x = Tensor::<1>::from_floats([-2.0, 0.0, 3.0], &device);
    let forward = values(square_plus_input(x));
    assert_eq!(forward, vec![2.0, 0.0, 12.0]);
    println!("Flex forward: x=[-2, 0, 3], y={forward:?}");

    // 2. 同一个公开函数也接受二维张量，且保持形状和设备。
    let x = Tensor::<2>::from_floats([[-2.0, 0.0, 3.0], [-1.0, 1.0, 2.0]], &device);
    let y = square_plus_input(x);
    assert_eq!(y.dims(), [2, 3]);
    assert_eq!(y.device(), device);
    let forward_2d = values(y);
    assert_eq!(forward_2d, vec![2.0, 0.0, 12.0, 0.0, 2.0, 6.0]);
    println!("2D forward: shape=[2, 3], y={forward_2d:?}");

    // 3. L = sum(f(x))；上游梯度全是 1，所以 dL/dx = 2x + 1。
    let device = Device::flex().autodiff();
    let x = Tensor::<1>::from_floats([-2.0, 0.0, 3.0], &device).require_grad();
    let gradients = square_plus_input(x.clone()).sum().backward();
    let gradient = values(x.grad(&gradients).unwrap());
    assert_eq!(gradient, vec![-3.0, 1.0, 7.0]);
    println!("Autodiff sum: dL/dx={gradient:?}");

    // 4. 重新前向建立计算图：第一次 backward 后，不复用已消费的图。
    // L = sum(f(x) * g)，其中 g 是常量；链式法则给出 dL/dx = g * (2x + 1)。
    let x = Tensor::<1>::from_floats([-2.0, 0.0, 3.0], &device).require_grad();
    let g = Tensor::<1>::from_floats([2.0, -1.0, 0.5], &device);
    let gradients = (square_plus_input(x.clone()) * g).sum().backward();
    let gradient = values(x.grad(&gradients).unwrap());
    assert_eq!(gradient, vec![-6.0, -1.0, 3.5]);
    println!("Autodiff weighted sum: g=[2, -1, 0.5], dL/dx={gradient:?}");
}
