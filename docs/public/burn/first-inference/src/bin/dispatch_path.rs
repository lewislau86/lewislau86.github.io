use burn::prelude::*;

fn main() {
    // 公共类型相同，设备在运行时选择；这里固定使用 Flex CPU。
    let device = Device::flex();
    let x = Tensor::<2>::from_floats([[1.0, 2.0], [3.0, 4.0]], &device);
    let w = Tensor::<2>::from_floats([[1.0, 0.0], [0.0, 1.0]], &device);

    let y = x.clone().matmul(w.clone()) + 0.5;
    assert_eq!(y.dims(), [2, 2]);
    assert_eq!(y.dtype(), x.dtype());

    println!("x dims = {:?}, dtype = {:?}", x.dims(), x.dtype());
    println!("x device = {:?}", x.device());
    println!("y dims = {:?}, dtype = {:?}", y.dims(), y.dtype());
    println!("same public type, different runtime resources: the Device decides where work runs.");
    println!("this example uses the Flex CPU path; no GPU is required.");
}
