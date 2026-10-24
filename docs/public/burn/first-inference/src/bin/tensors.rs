use burn::prelude::*;

fn values<const D: usize>(tensor: Tensor<D>) -> Vec<f32> {
    tensor.into_data().try_to_vec::<f32>().unwrap()
}

fn main() {
    let device = Device::flex();

    // A: [2, 3], B: [3, 2] -> C: [2, 2]
    let a = Tensor::<2>::from_floats([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], &device);
    let b = Tensor::<2>::from_floats([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]], &device);
    let c = a.clone().matmul(b);
    assert_eq!(c.dims(), [2, 2]);
    assert_eq!(values(c.clone()), vec![22.0, 28.0, 49.0, 64.0]);

    // 形状变化不改变元素个数；reshape 与 transpose 的轴顺序不同。
    let reshaped = a.clone().reshape([3, 2]);
    let transposed = a.clone().transpose();
    assert_eq!(reshaped.dims(), [3, 2]);
    assert_eq!(transposed.dims(), [3, 2]);
    assert_eq!(values(reshaped), vec![1.0, 2.0, 3.0, 4.0, 5.0, 6.0]);
    assert_eq!(values(transposed), vec![1.0, 4.0, 2.0, 5.0, 3.0, 6.0]);

    // [2, 3] + [1, 3] 广播到每一行。
    let row = Tensor::<2>::from_floats([[10.0, 20.0, 30.0]], &device);
    let shifted = a.clone() + row;
    assert_eq!(values(shifted.clone()), vec![11.0, 22.0, 33.0, 14.0, 25.0, 36.0]);

    println!("A dims = {:?}, dtype = {:?}", a.dims(), a.dtype());
    println!("A @ B = {:?}", values(c));
    println!("reshape = {:?}", values(a.clone().reshape([3, 2])));
    println!("transpose = {:?}", values(a.clone().transpose()));
    println!("A + row = {:?}", values(shifted));
    println!("elements = {}, reshape keeps = {}", a.dims().iter().product::<usize>(), 2 * 3);
}
