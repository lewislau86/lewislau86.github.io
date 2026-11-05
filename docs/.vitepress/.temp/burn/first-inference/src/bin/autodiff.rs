use burn::tensor::{Device, Tensor};

fn main() {
    let device = Device::flex().autodiff();
    let x = Tensor::<1>::from_floats([3.0], &device).require_grad();
    let y = x.clone() * x.clone() + x.clone();
    let grads = y.backward();
    let dx = x.grad(&grads).unwrap();
    let values = dx.into_data().try_to_vec::<f32>().unwrap();
    assert_eq!(values, vec![7.0]);
    println!("dy/dx at x=3 = {values:?}");
}
