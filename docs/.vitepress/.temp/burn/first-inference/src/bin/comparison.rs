use burn::tensor::{Device, Tensor, activation::relu};

fn values<const D: usize>(tensor: Tensor<D>) -> Vec<f32> {
    tensor.into_data().try_to_vec::<f32>().unwrap()
}

fn close(actual: &[f32], expected: &[f32]) {
    assert_eq!(actual.len(), expected.len());
    for (a, e) in actual.iter().zip(expected) {
        assert!((a - e).abs() < 1e-5, "actual={a}, expected={e}");
    }
}

fn main() {
    // 同一主线：前向及对 X、W、b 的梯度。所有源叶子独立标记。
    let device = Device::flex().autodiff();
    let x = Tensor::<2>::from_floats([[1.0, 2.0]], &device).require_grad();
    let w = Tensor::<2>::from_floats([[1.0, -1.0], [2.0, 1.0]], &device).require_grad();
    let b = Tensor::<2>::from_floats([[0.0, 1.0]], &device).require_grad();
    let h = relu(x.clone().matmul(w.clone()) + b.clone());
    assert_eq!(h.dims(), [1, 2]);
    let output = values(h.clone());
    close(&output, &[5.0, 2.0]);
    let gradients = h.sum().backward();
    let dx = values(x.grad(&gradients).unwrap());
    let dw = values(w.grad(&gradients).unwrap());
    let db = values(b.grad(&gradients).unwrap());
    close(&dx, &[0.0, 3.0]);
    close(&dw, &[1.0, 1.0, 2.0, 2.0]);
    close(&db, &[1.0, 1.0]);
    println!("H = {output:?}; shape = [1, 2]");
    println!("dX = {dx:?}; dW = {dw:?}; db = {db:?}");

    // 与扩展示例使用同一目标，验证非全 1 的上游梯度。
    let x = Tensor::<1>::from_floats([-2.0, 0.0, 3.0], &device).require_grad();
    let g = Tensor::<1>::from_floats([2.0, -1.0, 0.5], &device);
    let y = x.clone() * x.clone() + x.clone();
    let gradients = (y * g).sum().backward();
    let dx = values(x.grad(&gradients).unwrap());
    close(&dx, &[-6.0, -1.0, 3.5]);
    println!("weighted dX = {dx:?}");

    // 手动做一次 SGD 数学更新，用于理解公式，不是 Burn 优化器 API 教程。
    let w = Tensor::<1>::from_floats([0.0], &device).require_grad();
    let error = w.clone() * 2.0 - 4.0;
    let loss = (error.clone() * error).sum();
    close(&values(loss.clone()), &[16.0]);
    let gradients = loss.backward();
    let dw = w.grad(&gradients).unwrap();
    close(&values(dw.clone()), &[-16.0]);
    let updated = w.detach() - dw * 0.1;
    let new_w = values(updated.clone());
    let error = updated * 2.0 - 4.0;
    let new_loss = values((error.clone() * error).sum());
    close(&new_w, &[1.6]);
    close(&new_loss, &[0.64]);
    println!("SGD w = {new_w:?}; loss after = {new_loss:?}");
}
