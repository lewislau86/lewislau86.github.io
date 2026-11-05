//! Compare four update rules on the same scalar objective.

const TARGET: f64 = 3.0;
const STEPS: usize = 120;

fn loss(w: f64) -> f64 {
    (w - TARGET).powi(2)
}

fn grad(w: f64) -> f64 {
    2.0 * (w - TARGET)
}

fn sgd(mut w: f64, lr: f64) -> (f64, Vec<f64>) {
    let mut history = Vec::with_capacity(STEPS);
    for _ in 0..STEPS {
        w -= lr * grad(w);
        history.push(loss(w));
    }
    (w, history)
}

fn momentum(mut w: f64, lr: f64, beta: f64) -> (f64, Vec<f64>) {
    let mut velocity = 0.0;
    let mut history = Vec::with_capacity(STEPS);
    for _ in 0..STEPS {
        velocity = beta * velocity + grad(w);
        w -= lr * velocity;
        history.push(loss(w));
    }
    (w, history)
}

fn adam(mut w: f64, lr: f64, beta1: f64, beta2: f64, eps: f64) -> (f64, Vec<f64>) {
    let mut m = 0.0;
    let mut v = 0.0;
    let mut history = Vec::with_capacity(STEPS);
    for step in 1..=STEPS {
        let g = grad(w);
        m = beta1 * m + (1.0 - beta1) * g;
        v = beta2 * v + (1.0 - beta2) * g * g;
        let m_hat = m / (1.0 - beta1.powi(step as i32));
        let v_hat = v / (1.0 - beta2.powi(step as i32));
        w -= lr * m_hat / (v_hat.sqrt() + eps);
        history.push(loss(w));
    }
    (w, history)
}

fn adamw(mut w: f64, lr: f64, beta1: f64, beta2: f64, eps: f64, weight_decay: f64) -> (f64, Vec<f64>) {
    let mut m = 0.0;
    let mut v = 0.0;
    let mut history = Vec::with_capacity(STEPS);
    for step in 1..=STEPS {
        let g = grad(w);
        m = beta1 * m + (1.0 - beta1) * g;
        v = beta2 * v + (1.0 - beta2) * g * g;
        let m_hat = m / (1.0 - beta1.powi(step as i32));
        let v_hat = v / (1.0 - beta2.powi(step as i32));
        // 解耦衰减：先按自己的学习率收缩参数，再应用自适应梯度。
        w -= lr * weight_decay * w;
        w -= lr * m_hat / (v_hat.sqrt() + eps);
        history.push(loss(w));
    }
    (w, history)
}

fn report(name: &str, w: f64, history: &[f64]) {
    println!(
        "{name:<9} final w = {w:>8.5}  loss = {:>10.6}  first = {:>10.4}",
        history.last().copied().unwrap_or(f64::NAN),
        history.first().copied().unwrap_or(f64::NAN)
    );
}

fn main() {
    let lr = 0.1;
    println!("objective: L(w) = (w - {TARGET})^2, steps = {STEPS}, lr = {lr}");

    let (w, history) = sgd(0.0, lr);
    report("SGD", w, &history);
    let (w, history) = momentum(0.0, lr, 0.9);
    report("Momentum", w, &history);
    let (w, history) = adam(0.0, lr, 0.9, 0.999, 1e-8);
    report("Adam", w, &history);
    let (w, history) = adamw(0.0, lr, 0.9, 0.999, 1e-8, 0.1);
    report("AdamW", w, &history);

    println!("note: AdamW's decoupled weight decay intentionally pulls the parameter toward zero.");
}
